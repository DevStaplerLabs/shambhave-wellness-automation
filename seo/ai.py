"""Thin wrapper around the Anthropic API with a monthly budget guard and usage log.

Security notes:
- The API key is read from the ANTHROPIC_API_KEY environment variable (a GitHub Actions secret). It is never logged.
- Only public website content and our own audit data are sent. No client records, no credentials.
- Website text is untrusted: prompts tell Claude to treat it as data, and Claude's output is only
  saved and emailed. It is never executed or deployed automatically.
"""
import os
from datetime import date

import anthropic

from .store import now_iso, read_json, write_json

# Server-side refusal fallback (Claude API). Not supported on Haiku 5.5, so only used for the others.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5"}

HOUSE_RULES = """House rules for anything you write (StaplerLabs, writing for a mental health clinic and its NGO):
- Plain Indian English. Short sentences. No em dashes or en dashes.
- Never use these words: leverage, seamless, robust, transform, unlock, empower, synergy, ecosystem, holistic,
  growth, marketing, agency, package, harness, cutting edge, game changer, delve, navigate, tapestry,
  supercharge, revolutionise, compounding.
- No treatment claims, no cure or recovery promises, no guaranteed outcomes, nothing that could identify a patient.
- No self-applied superlatives such as "best", "No. 1", "world-class".
- No prices or fees.
- Respect the clinic's experience; write as one professional to another."""


class BudgetExceeded(Exception):
    pass


class AI:
    def __init__(self, cfg, enabled=True):
        self.cfg = cfg["ai"]
        self.enabled = enabled and bool(os.environ.get("ANTHROPIC_API_KEY"))
        self.client = anthropic.Anthropic(max_retries=3, timeout=600) if self.enabled else None
        self.month = date.today().strftime("%Y-%m")
        self.log = read_json(f"usage/{self.month}.json", {"calls": [], "total_usd": 0.0})

    # ---- cost tracking ----
    def _cost(self, model, usage):
        p = self.cfg["prices"].get(model, {"input": 5, "output": 25, "cache_read": 0.5})
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        return (usage.input_tokens * p["input"] + cache_write * p["input"] * 1.25
                + cache_read * p["cache_read"] + usage.output_tokens * p["output"]) / 1_000_000

    def spent(self):
        return round(self.log["total_usd"], 4)

    def _record(self, purpose, model, resp, extra_usd=0.0):
        usd = self._cost(model, resp.usage) + extra_usd
        self.log["calls"].append({"at": now_iso(), "purpose": purpose, "model": model,
                                  "in": resp.usage.input_tokens, "out": resp.usage.output_tokens,
                                  "cache_read": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
                                  "usd": round(usd, 5), "request_id": getattr(resp, "_request_id", None)})
        self.log["total_usd"] = round(self.log["total_usd"] + usd, 5)
        write_json(f"usage/{self.month}.json", self.log)

    def _check_budget(self):
        if self.log["total_usd"] >= self.cfg["monthly_budget_usd"]:
            raise BudgetExceeded(f"Monthly AI budget of ${self.cfg['monthly_budget_usd']} reached")

    # ---- calls ----
    def ask(self, purpose, model, system, user, max_tokens=8000, effort="low", tools=None):
        """One request. Returns (text, response). Raises BudgetExceeded or anthropic errors."""
        if not self.enabled:
            return None, None
        self._check_budget()
        kwargs = dict(model=model, max_tokens=max_tokens,
                      system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                      messages=[{"role": "user", "content": user}],
                      output_config={"effort": effort})
        if tools:
            kwargs["tools"] = tools
        if model in FALLBACK_MODELS:
            resp = self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        else:
            resp = self.client.messages.create(**kwargs)

        # Server tools (web search) may pause after many steps; resume a few times at most.
        for _ in range(4):
            if resp.stop_reason != "pause_turn":
                break
            self._record(purpose, model, resp)
            kwargs["messages"] = [kwargs["messages"][0], {"role": "assistant", "content": resp.content}]
            resp = (self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
                    if model in FALLBACK_MODELS else self.client.messages.create(**kwargs))

        searches = 0
        su = getattr(resp.usage, "server_tool_use", None)
        if su is not None:
            searches = getattr(su, "web_search_requests", 0) or 0
        self._record(purpose, model, resp, extra_usd=searches * 0.01)  # web search billed per search

        if resp.stop_reason == "refusal":
            cat = getattr(getattr(resp, "stop_details", None), "category", None)
            return f"[Declined by the model, category: {cat}]", resp
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        if resp.stop_reason == "max_tokens":
            text += "\n\n[Output cut off at the token limit]"
        return text, resp
