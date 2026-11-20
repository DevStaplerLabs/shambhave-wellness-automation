"""Weekly run: PageSpeed, AI search visibility, then the email report.

Usage: python run_weekly.py [--no-ai] [--skip-psi] [--skip-geo]
"""
import argparse
import re

from seo.ai import AI
from seo.content import run_content
from seo.geo import run_geo
from seo.gsc import run_gsc
from seo.notify import send_email
from seo.psi import run_pagespeed
from seo.report import ai_summary, build_facts, render
from seo.store import load_config, today, write_json, write_text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--skip-psi", action="store_true")
    ap.add_argument("--skip-geo", action="store_true")
    ap.add_argument("--skip-content", action="store_true")
    args = ap.parse_args()
    cfg, day = load_config(), today()
    ai = AI(cfg, enabled=not args.no_ai)

    gsc = run_gsc(cfg)
    if gsc.get("sites"):
        write_json("gsc/latest.json", gsc)
        write_json(f"gsc/{day}.json", gsc)
    psi = [] if args.skip_psi else run_pagespeed(cfg)
    geo = [] if (args.skip_geo or args.no_ai) else run_geo(cfg, ai)
    content = [] if (args.skip_content or args.no_ai) else run_content(cfg, ai)
    facts = build_facts(cfg, day, psi, geo, ai, gsc=gsc, content=content)
    summary = ai_summary(cfg, facts, ai)
    facts["ai_spend_month_usd"] = ai.spent()
    page = render(cfg, facts, summary)

    write_json(f"weekly/{day}.json", facts)
    write_json("weekly/last.json", {"pagespeed": psi, "geo": geo})
    write_text(f"weekly/{day}.html", page)
    text = re.sub(r"<[^>]+>", " ", page)
    print(send_email(f"{cfg['report']['subject_prefix']} | {day}", page, text, f"weekly-{day}"))


if __name__ == "__main__":
    main()
