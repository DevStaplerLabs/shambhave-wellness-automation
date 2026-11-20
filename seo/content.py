"""Weekly article drafts written for both Google and AI answers: answer-first, clear H2s, FAQ, schema.
Drafts are saved for human review in data/content/. Nothing is published automatically."""
import re
from datetime import date

from .ai import HOUSE_RULES, AI, BudgetExceeded
from .store import audit_on_or_before, read_json, today, write_json, write_text


def slugify(t):
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:70]


def pick_topics(cfg):
    done = read_json("content/done.json", {})
    picks = []
    gsc = read_json("gsc/latest.json", {})
    for key, d in (gsc.get("sites") or {}).items():
        for s in d.get("striking_distance", []):
            # Queries we almost rank for but where no article exists yet
            if "/blog/" not in s["page"] and s["query"] not in done and len(s["query"].split()) >= 3:
                picks.append({"site": key, "topic": s["query"], "source": "Search Console demand"})
    for t in cfg["content"]["topics"]:
        if t["topic"] not in done:
            picks.append({**t, "source": "topic plan"})
    seen, out = set(), []
    for p in picks:
        if p["topic"].lower() not in seen:
            seen.add(p["topic"].lower())
            out.append(p)
    return out[: cfg["content"]["per_week"]]


def _site_links(site_key):
    audit = audit_on_or_before(today()) or {"sites": []}
    for s in audit["sites"]:
        if s["site"] == site_key:
            return [{"title": p.get("title"), "url": p["url"]} for p in s["pages"]
                    if p.get("status") == 200 and ("/service/" in p["url"] or "/blog/" in p["url"]
                                                   or p["url"].rstrip("/").endswith(("about-us", "contact-us")))][:40]
    return []


PROMPT = """Write a blog article draft for {site_name}.

Topic or search query: {topic}

Requirements:
- Audience: adults in India (and Indians abroad) looking for help. Warm, plain, respectful. Not salesy.
- 900 to 1,200 words.
- Start with a 2 to 3 sentence direct answer to the topic (this is what AI search tools quote).
- 5 to 7 H2 sections; use questions people actually search as some H2s.
- Include India-specific context where it is genuinely relevant.
- End with a short section on when to seek professional support, plus: "If you are in crisis, call Tele-MANAS on 14416."
- Then an FAQ with 4 questions and 40 to 70 word answers.
- Add 2 to 4 internal links in the text, using only URLs from this list: {links}
- No treatment promises, no statistics unless widely established, no invented quotes, no patient stories.
- Byline: "Reviewed by Dr. Amita Puri, Clinical Psychologist" placeholder at the top, marked [needs her review].

Output exactly in this format:
TITLE: <55-60 character title>
META: <145-155 character meta description>
SLUG: <url-slug>
---
<article in markdown, starting with the byline line>
---
FAQ_JSON:
<a JSON array of {{"q": "...", "a": "..."}} objects matching the FAQ>"""


def run_content(cfg, ai: AI):
    results = []
    done = read_json("content/done.json", {})
    names = {s["key"]: s["name"] for s in cfg["sites"]}
    for t in pick_topics(cfg):
        try:
            text, _ = ai.ask("weekly_article", cfg["content"]["model"], HOUSE_RULES,
                             PROMPT.format(site_name=names.get(t["site"], t["site"]), topic=t["topic"],
                                           links=_site_links(t["site"])),
                             max_tokens=10000, effort="medium")
        except BudgetExceeded as e:
            results.append({"topic": t["topic"], "error": str(e)})
            break
        except Exception as e:
            results.append({"topic": t["topic"], "error": f"{type(e).__name__}: {str(e)[:120]}"})
            continue
        if not text:
            results.append({"topic": t["topic"], "error": "AI off"})
            continue
        m = re.search(r"SLUG:\s*(\S+)", text)
        slug = slugify(m.group(1) if m else t["topic"])
        path = write_text(f"content/{date.today().isoformat()}-{slug}.md",
                          f"<!-- site: {t['site']} | source: {t['source']} | topic: {t['topic']} -->\n\n{text}\n")
        done[t["topic"]] = date.today().isoformat()
        results.append({"topic": t["topic"], "site": t["site"], "source": t["source"], "file": path.name})
    write_json("content/done.json", done)
    return results
