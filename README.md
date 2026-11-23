# Shambhave Wellness SEO and GEO automation (StaplerLabs internal)

Internal tool. Not for the client. Nothing here is installed on their cPanel or in their code repo.

## What it does

| When | Job | AI cost |
| --- | --- | --- |
| Every day, 06:47 IST | Crawls both sites from their sitemaps. Checks titles, descriptions, canonicals, H1s, schema (incl. leaked PHP), alt text, thin pages, duplicate URLs, www/http redirects, robots.txt, AI crawler access, llms.txt and exposed files. Saves results, compares with the last run, writes fixes to `data/suggestions/<date>.md`. Emails an alert only if a new critical problem appears. | Up to 8 copy fixes a day on Sonnet 5.5 |
| Monday, 08:11 IST | Search Console data, Google PageSpeed (mobile) for key pages, AI search visibility for the questions in `config.yaml`, then the weekly email report with score changes, fixed and new problems, and a short to-do list. | Haiku 5.5 for the summary, Sonnet 5.5 + web search for visibility |

Technical fixes with a known answer (schema, redirects, exposed files) are written by code, not AI, so they cost nothing.

### What gets checked

- **Indexing:** status codes, noindex (meta and header), canonicals, sitemap health, fake lastmod dates, www/http duplicates, root-level duplicate URLs, the same page served on both domains.
- **On-page:** titles, descriptions (length, duplicates, "best" claims), H1s, thin pages, alt text, images without dimensions, heavy images, mixed content.
- **Schema:** invalid JSON-LD, leaked PHP, missing @context, service pages without FAQPage, articles without BlogPosting.
- **Links:** broken internal links, orphan pages.
- **GEO / AI search:** robots.txt rules for AI crawlers, real access test with AI user agents, llms.txt, weekly check of which sites AI answers cite (us and competitors).
- **Search Console (once connected):** clicks, impressions, CTR, position; queries where we sit on page 2 ("striking distance"); pages with poor CTR. These get fixed first because they have real demand.
- **Security:** publicly downloadable files that should not be.

### What it produces

| File | What |
| --- | --- |
| `data/suggestions/<date>.md` | Today's fixes: exact code changes and ready-to-paste titles, descriptions, FAQs |
| `data/generated/<site>/llms.txt` | Upload to the site root as-is (rebuilt daily from live pages) |
| `data/generated/<site>/schema.blade.php` | Clean JSON-LD to replace the broken blocks in `frontMaster.blade.php` |
| `data/content/<date>-<slug>.md` | Weekly article draft with meta title, description, FAQ and FAQ JSON. Needs Dr. Puri's review before publishing |
| `data/weekly/<date>.html` | Copy of the weekly email |
| `data/usage/<month>.json` | Every AI call with tokens and cost |

## Fix and deploy (second automation)

1. **Daily, after the check:** `run_sitefix.py` makes small, known-safe code changes in the website repo and opens
   one pull request at a time (branch `seo-bot/<date>`): remove the static sitemap/robots files that hide the
   per-domain ones, 301 www/http to https without www, per-domain llms.txt route, block build files in .htaccess,
   twitter:card, and the page overrides below. PHP is syntax-checked.
   **Page overrides:** titles and descriptions live in the admin panel database, which the bot never touches. So the
   daily run writes new titles/descriptions (Claude, then checked in code for length, house rules, claims, prices
   and duplicates) and canonicals into `data/overrides.json`. The PR copies them to `resources/seo/overrides.json`
   in the website repo, where a small `seo_head()` helper in `app/helpers.php` swaps the head tags for those paths
   only. Foundation copies of clinic service/course pages get a canonical to the clinic URL. Remove a path from
   the file to undo. Settings: `overrides` and `cross_site` in `config.yaml`.
2. **You review and click Merge.** That is the approval step.
3. **Every 2 hours:** `run_deploy.py` uploads what was merged by FTP(S): backup first, only allowed files
   (never `.env`, `vendor/`, `storage/`, uploads in `BackEndImage/`, `scratch/`, composer files), at most 40 files,
   clears Laravel's route/config cache when routes change, then loads key pages on both sites. If a page fails,
   the old files are put back automatically and you get a "ROLLED BACK" email. Backups are kept 30 days as
   workflow artifacts. The first run only checks the FTP login and records a baseline.

Extra secrets for this part:

| Secret | Value |
| --- | --- |
| `SITE_REPO_TOKEN` | Fine-grained token for the website repo only: Contents read/write, Pull requests read/write |
| `FTP_HOST` | FTP server name from cPanel, e.g. `ftp.shambhavewellness.org` |
| `FTP_USER` | A dedicated FTP account (not the main cPanel login) |
| `FTP_PASSWORD` | Its password |
| `FTP_REMOTE_ROOTS` | Folder(s) as the FTP account sees them, e.g. `/public_html` (comma separate if the foundation has its own folder) |
| `FTP_PORT` / `FTP_TLS` | Optional: `21` / `1`. Set `FTP_TLS` to `0` only if the host has no FTPS |

## Safety

- Reads public pages only. Never logs in, never submits forms, never touches booking, payment or client data.
- Never changes the live website on its own. Website changes go in as a pull request; nothing ships until a
  person merges it, and the deployer backs up, checks and rolls back. Content edits stay suggestions.
- All keys live in GitHub Actions secrets. None are in this repo.
- Website text sent to Claude is marked as untrusted data, and Claude's output is HTML-escaped before it goes into an email.
- Monthly AI budget cap in `config.yaml` (`monthly_budget_usd`). Spend is logged in `data/usage/`.

## Setup (one time)

Add these in GitHub: repo Settings > Secrets and variables > Actions > New repository secret.

| Secret | Value |
| --- | --- |
| `ANTHROPIC_API_KEY` | Key from a dedicated Anthropic workspace with a spend limit |
| `RESEND_API_KEY` | Option A for email (easiest): free key from resend.com. Sign up with the address that should receive the reports. Then skip the SMTP rows |
| `SMTP_HOST` | Option B for email: `smtp.gmail.com` for Google Workspace |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | Sending mailbox, e.g. `work@staplerlabs.com` |
| `SMTP_PASSWORD` | A Google app password for that mailbox (not the normal password) |
| `REPORT_TO` | Who receives reports, comma separated |
| `REPORT_FROM` | Optional, defaults to `SMTP_USER` |
| `PSI_API_KEY` | Optional, free Google PageSpeed key for higher limits |
| `GSC_SERVICE_ACCOUNT_JSON` | Optional but recommended. Full JSON key of a Google service account added to Search Console with "Restricted" access (see `seo/gsc.py`) |

Then: Actions tab > "Daily SEO and GEO check" > Run workflow. Check the log, then run the weekly one once.

If SMTP secrets are missing, emails are saved to `data/outbox/` instead.

## Run locally

```bash
pip install -r requirements.txt
python run_daily.py --no-ai          # crawl and rule-based fixes only
python run_weekly.py --no-ai --skip-geo
python -m pytest -q tests/test_core.py   # unit tests
```

Offline test against a mock site: `python tests/mock_site.py 8099 &` then
`SEO_CONFIG=tests/config.test.yaml SEO_DATA_DIR=/tmp/seo-test python run_daily.py --no-ai`.

## Change things

Edit `config.yaml`: sites, AI-visibility questions, models, daily fix count, budget. The report layout lives in
`seo/report.py` (`render`) and will be replaced with the StaplerLabs format.
