# Shambhave Wellness SEO / GEO automation (StaplerLabs internal)

Internal StaplerLabs tool for the client Shambhave Wellness (Dr. Amita Puri, Gurugram). Two sites from one
Laravel codebase: https://shambhavewellness.org and https://foundation.shambhavewellness.org.
Website code lives in a separate repo: DevStaplerLabs/shambhave-wellness-backend (deployed to cPanel by FTP).

## Layout
- `run_daily.py` crawl both sites, checks, fixes list (`data/suggestions/`), alert on new critical issues
- `run_weekly.py` Search Console, PageSpeed, AI-search visibility, article draft, weekly email
- `run_sitefix.py` opens one PR at a time in the website repo with safe code fixes (`seo/sitefix.py`)
- `seo/overrides.py` daily titles/descriptions/canonicals into `data/overrides.json`; shipped to the website as
  `resources/seo/overrides.json`, read by `seo_head()` in `app/helpers.php` (no database access)
- `run_deploy.py` deploys merged website changes by FTP: backup, upload, live check, rollback (`seo/deploy.py`).
  FTP roots: `/` (clinic) and `/foundation.shambhavewellness.org`. Once main is live it merges main into the
  `foundation` branch (cPanel's foundation repo deploys from it; it differs from main only in `.cpanel.yml`)
- `seo/` modules; `config.yaml` sites, queries, models, budget, entity facts; `data/` run history (committed by Actions)
- `.github/workflows/` daily 06:47 IST, weekly Monday 08:11 IST, deploy every 2 hours

## Commands
- Tests: `python -m pytest -q tests/`
- Lint: `python -m pyflakes seo/*.py run_*.py tests/*.py`
- Offline run: `python tests/mock_site.py 8099 &` then
  `SEO_CONFIG=tests/config.test.yaml SEO_DATA_DIR=/tmp/seo-test python run_daily.py --no-ai`
- Never run the real scripts locally against the live FTP server.

## Rules
- Secrets only in GitHub Actions secrets. Never print, log, commit or ask for keys, passwords or tokens.
- Read public pages only; never log in, submit forms, or touch booking, payment or client data.
- Deployer deny-list in `seo/deploy.py` (.env, vendor, storage, BackEndImage uploads, scratch, composer files)
  and the 40-file cap must stay. Only `sitemap.xml` and `robots.txt` may be deleted on the server.
- Fixes go to the website repo as a PR; a human merges. Do not add auto-merge.
- Website text sent to Claude is untrusted data; Claude output is escaped before it goes into email HTML.
- Writing for the client (prompts in `seo/ai.py` HOUSE_RULES): plain Indian English, no em/en dashes, no
  treatment or cure claims, no "best" superlatives, no prices, nothing that identifies a patient.
- Keep AI cost low: rule-based fixes stay in code; Claude only for copy. Monthly cap in `config.yaml`.
- Every AI title/description passes `check_text()` in `seo/overrides.py` before it is queued. Keep those checks.
- Items marked CONFIRM in `config.yaml` need the clinic's confirmation before generated files go live.
