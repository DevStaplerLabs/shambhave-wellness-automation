"""Daily run: crawl both sites, compare with yesterday, write fixes, alert on new critical problems.

Usage: python run_daily.py [--no-ai]
"""
import argparse
import html

from seo.ai import AI
from seo.crawl import diff, run_audit, score
from seo.generate import write_generated
from seo.notify import send_email
from seo.store import DATA, audit_on_or_before, load_config, today, write_json, write_text
from seo.suggest import run_suggestions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ai", action="store_true", help="skip all Claude calls")
    args = ap.parse_args()
    cfg, day = load_config(), today()

    audit = run_audit(cfg)
    prev = audit_on_or_before(day)  # read before saving, so a same-day re-run compares with the earlier run
    write_json(f"audits/{day}.json", audit)
    d = diff(prev, audit)

    write_generated(cfg, audit)
    ai = AI(cfg, enabled=not args.no_ai)
    md, n_static, n_ai = run_suggestions(cfg, audit, day, ai)
    # A second run on the same day must not wipe the fixes already written that morning.
    if n_static or n_ai or not (DATA / f"suggestions/{day}.md").exists():
        write_text(f"suggestions/{day}.md", md)

    summary = ", ".join(f"{s['name']}: score {score(s)}, {len(s['issues'])} issues, {s['page_count']} pages"
                        for s in audit["sites"])
    print(f"[{day}] {summary}. New: {len(d['new'])}, resolved: {len(d['resolved'])}. "
          f"Fixes written: {n_static} rule based, {n_ai} by AI. AI spend this month: ${ai.spent()}")

    critical = [i for i in d["new"] if i["severity"] == "critical"]
    if critical:
        items = "".join(f"<li><b>{html.escape(i['rule'])}</b>: {html.escape(i['detail'])}<br>{html.escape(i['url'])}</li>"
                        for i in critical)
        text = "\n".join(f"- {i['rule']}: {i['detail']} ({i['url']})" for i in critical)
        print(send_email(f"ALERT: {len(critical)} new critical issue(s) on Shambhave sites",
                         f"<p>New today ({day}):</p><ul>{items}</ul>", text, f"alert-{day}"))


if __name__ == "__main__":
    main()
