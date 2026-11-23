"""Open (at most one at a time) a pull request in the website repo with today's safe code fixes.

Needs SITE_REPO_TOKEN: a fine-grained GitHub token limited to the website repo with
Contents: read/write and Pull requests: read/write. Without it, this step is skipped.
"""
import os
import sys
import tempfile

import requests

from seo.overrides import export
from seo.overrides import load as load_overrides
from seo.sitefix import apply_fixes, git, pr_body
from seo.store import DATA, audit_on_or_before, today, write_json

REPO = os.environ.get("SITE_REPO", "DevStaplerLabs/shambhave-wellness-backend")
BASE = os.environ.get("SITE_BRANCH", "main")
API = "https://api.github.com"


def gh(method, path, token, **kw):
    r = requests.request(method, API + path, timeout=60, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"}, **kw)
    r.raise_for_status()
    return r.json()


def main():
    token = os.environ.get("SITE_REPO_TOKEN")
    url = os.environ.get("SITE_REPO_URL") or (f"https://x-access-token:{token}@github.com/{REPO}.git" if token else None)
    if not url:
        print("SITE_REPO_TOKEN not set: site fixer skipped")
        return
    day = today()
    audit = audit_on_or_before(day)
    if not audit:
        print("No audit yet")
        return
    issues = [i for s in audit["sites"] for i in s["issues"]]

    if token and not os.environ.get("SITE_REPO_URL"):
        open_prs = gh("GET", f"/repos/{REPO}/pulls?state=open&per_page=50", token)
        mine = [p for p in open_prs if p["head"]["ref"].startswith("seo-bot/")]
        if mine:
            print(f"A bot pull request is already open ({mine[0]['html_url']}); not opening another.")
            return

    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "site")
        r = git(tmp, "clone", "--depth", "1", "--branch", BASE, url, repo, check=False)
        if r.returncode:
            print("Clone failed:", r.stderr.replace(token or "~~", "***")[:300])
            sys.exit(1)
        branch = f"seo-bot/{day}"
        git(repo, "checkout", "-b", branch)
        fixes = apply_fixes(repo, issues, DATA / "generated", overrides=export(load_overrides()))
        if not git(repo, "status", "--porcelain").stdout.strip():
            print("Nothing to fix in code today")
            return
        git(repo, "add", "-A")
        git(repo, "-c", "user.name=StaplerLabs SEO Bot", "-c", "user.email=seo-bot@users.noreply.github.com",
            "commit", "-q", "-m", "SEO fixes: " + "; ".join(f["title"] for f in fixes))
        p = git(repo, "push", "-q", "origin", branch, check=False)
        if p.returncode:
            print("Push failed:", p.stderr.replace(token or "~~", "***")[:300])
            sys.exit(1)
        title = f"SEO fixes {day}: " + ", ".join(f["id"] for f in fixes)
        if token and not os.environ.get("SITE_REPO_URL"):
            pr = gh("POST", f"/repos/{REPO}/pulls", token,
                    json={"title": title, "head": branch, "base": BASE, "body": pr_body(fixes, day)})
            print("Opened", pr["html_url"])
            link = pr["html_url"]
        else:
            print("Pushed", branch)
            link = branch
        write_json(f"sitefix/{day}.json", {"pr": link, "fixes": fixes})


if __name__ == "__main__":
    main()
