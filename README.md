# Shambhave Wellness SEO and GEO automation (StaplerLabs internal)

Internal tool. Not for the client. Nothing here is installed on their cPanel or in their code repo.

## What it does

| When | Job | AI cost |
| --- | --- | --- |
| Every day, 06:47 IST | Crawls both sites from their sitemaps. Checks titles, descriptions, canonicals, H1s, schema (incl. leaked PHP), alt text, thin pages, duplicate URLs, www/http redirects, robots.txt, AI crawler access, llms.txt and exposed files. Saves results, compares with the last run, writes fixes to `data/suggestions/<date>.md`. Emails an alert only if a new critical problem appears. | Up to 8 copy fixes a day on Sonnet 5.5 |
| Monday, 08:11 IST | Google PageSpeed (mobile) for key pages, AI search visibility for the questions in `config.yaml`, then the weekly email report with score changes, fixed and new problems, and a short to-do list. | Haiku 5.5 for the summary, Sonnet 5.5 + web search for visibility |

Technical fixes with a known answer (schema, redirects, exposed files) are written by code, not AI, so they cost nothing.

## Safety

- Reads public pages only. Never logs in, never submits forms, never touches booking, payment or client data.
- Never edits or deploys the website. Fixes are suggestions you review and apply yourself.
- All keys live in GitHub Actions secrets. None are in this repo.
- Website text sent to Claude is marked as untrusted data, and Claude's output is HTML-escaped before it goes into an email.
- Monthly AI budget cap in `config.yaml` (`monthly_budget_usd`). Spend is logged in `data/usage/`.

## Setup (one time)

Add these in GitHub: repo Settings > Secrets and variables > Actions > New repository secret.

| Secret | Value |
| --- | --- |
| `ANTHROPIC_API_KEY` | Key from a dedicated Anthropic workspace with a spend limit |
| `SMTP_HOST` | `smtp.gmail.com` for Google Workspace |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | Sending mailbox, e.g. `work@staplerlabs.com` |
| `SMTP_PASSWORD` | A Google app password for that mailbox (not the normal password) |
| `REPORT_TO` | Who receives reports, comma separated |
| `REPORT_FROM` | Optional, defaults to `SMTP_USER` |
| `PSI_API_KEY` | Optional, free Google PageSpeed key for higher limits |

Then: Actions tab > "Daily SEO and GEO check" > Run workflow. Check the log, then run the weekly one once.

If SMTP secrets are missing, emails are saved to `data/outbox/` instead.

## Run locally

```bash
pip install -r requirements.txt
python run_daily.py --no-ai          # crawl and rule-based fixes only
python run_weekly.py --no-ai --skip-geo
```

Offline test against a mock site: `python tests/mock_site.py 8099 &` then
`SEO_CONFIG=tests/config.test.yaml SEO_DATA_DIR=/tmp/seo-test python run_daily.py --no-ai`.

## Change things

Edit `config.yaml`: sites, AI-visibility questions, models, daily fix count, budget. The report layout lives in
`seo/report.py` (`render`) and will be replaced with the StaplerLabs format.
