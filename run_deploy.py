"""Deploy what has been merged into the website repo's main branch since the last deploy.

First run only records a baseline (assumes the live site matches main today) and checks the FTP login.
Secrets: FTP_HOST, FTP_USER, FTP_PASSWORD, optional FTP_PORT (21), FTP_TLS (1), FTP_REMOTE_ROOTS
(comma separated, default /public_html), SITE_REPO_TOKEN.
"""
import os
import sys
import tempfile
from datetime import datetime, timezone

from seo.deploy import Remote, deploy, health, plan, rollback
from seo.notify import send_email
from seo.sitefix import git
from seo.store import audit_on_or_before, load_config, now_iso, read_json, today, write_json

REPO = os.environ.get("SITE_REPO", "DevStaplerLabs/shambhave-wellness-backend")
BASE = os.environ.get("SITE_BRANCH", "main")


def alert(subject, lines):
    body = "\n".join(lines)
    html = "<p>" + "</p><p>".join(l.replace("<", "&lt;") for l in lines) + "</p>"
    print(subject, "|", send_email(subject, html, body, f"deploy-{datetime.now(timezone.utc):%Y%m%d%H%M%S}"))


def health_urls(cfg):
    urls = []
    audit = audit_on_or_before(today()) or {"sites": []}
    for s in cfg["sites"]:
        b = s["base_url"].rstrip("/")
        urls += [b + "/", b + "/sitemap.xml"]
    for s in audit["sites"]:
        svc = next((p["url"] for p in s["pages"] if "/service/" in p["url"] and p.get("status") == 200), None)
        if svc:
            urls.append(svc)
            break
    return list(dict.fromkeys(urls))


def main():
    cfg = load_config()
    token = os.environ.get("SITE_REPO_TOKEN")
    url = os.environ.get("SITE_REPO_URL") or (f"https://x-access-token:{token}@github.com/{REPO}.git" if token else None)
    host, user, pwd = os.environ.get("FTP_HOST"), os.environ.get("FTP_USER"), os.environ.get("FTP_PASSWORD")
    if not (url and host and user and pwd):
        print("Deploy not configured (SITE_REPO_TOKEN and FTP_* secrets needed): skipped")
        return
    roots = [r.strip() for r in os.environ.get("FTP_REMOTE_ROOTS", "/public_html").split(",") if r.strip()]
    port, tls = int(os.environ.get("FTP_PORT") or 21), os.environ.get("FTP_TLS", "1") != "0"
    max_files = int(os.environ.get("DEPLOY_MAX_FILES") or 40)
    state = read_json("deploy/state.json", {"history": []})

    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "site")
        r = git(tmp, "clone", "--depth", "60", "--branch", BASE, url, repo, check=False)
        if r.returncode:
            print("Clone failed:", r.stderr.replace(token or "~~", "***")[:300])
            sys.exit(1)
        head = git(repo, "rev-parse", "HEAD").stdout.strip()
        last = state.get("last_sha")

        if not last:
            remote = Remote(host, user, pwd, port, tls)  # proves the login works
            missing = [rt for rt in roots if not remote.list(rt)]
            remote.close()
            if missing:
                alert("Deployer: FTP folder not found", [f"These FTP_REMOTE_ROOTS look empty or missing: {missing}"])
                sys.exit(1)
            state.update(last_sha=head, baseline_at=now_iso())
            write_json("deploy/state.json", state)
            alert("Deployer connected (baseline set)", [f"FTP login works. Baseline commit {head[:8]}.",
                                                       "From now on, anything merged into main is deployed hourly."])
            return
        if head == last or head == state.get("failed_sha") or head == state.get("refused_sha"):
            print("Nothing new to deploy")
            return
        if git(repo, "cat-file", "-e", last, check=False).returncode:
            git(repo, "fetch", "-q", "--deepen", "400", "origin", BASE, check=False)
            if git(repo, "cat-file", "-e", last, check=False).returncode:
                alert("Deployer: history gap", [f"Cannot find last deployed commit {last[:8]}. Deploy by hand, then "
                                                "set data/deploy/state.json last_sha to the live commit."])
                state["refused_sha"] = head
                write_json("deploy/state.json", state)
                return
        diff = git(repo, "diff", "--name-status", "--no-renames", last, head).stdout
        changes = [tuple(l.split("\t", 1)) for l in diff.splitlines() if "\t" in l]
        changes = [(st[0], p) for st, p in changes]
        uploads, deletes, skipped, refusal = plan(changes, max_files)
        commits = git(repo, "log", "--format=%h %s", f"{last}..{head}").stdout.strip().splitlines()

        if refusal:
            state["refused_sha"] = head
            write_json("deploy/state.json", state)
            alert("Deployer: NOT deployed (safety limit)", [refusal] + commits[:10])
            return
        if not uploads and not deletes:
            state["last_sha"] = head
            state["history"].append({"at": now_iso(), "sha": head, "files": 0, "skipped": skipped})
            write_json("deploy/state.json", state)
            print("Only non-deployable files changed:", skipped)
            return

        clear_cache = any(p.startswith(("routes/", "config/", "bootstrap/")) for p in uploads + deletes)
        backup_dir = os.environ.get("DEPLOY_BACKUP_DIR", "deploy_backup") + f"/{head[:8]}"
        remote = Remote(host, user, pwd, port, tls)
        journal = []
        try:
            journal = deploy(repo, uploads, deletes, roots, remote, backup_dir, clear_cache)
        except Exception as e:
            rollback(journal, remote)
            remote.close()
            state["failed_sha"] = head
            write_json("deploy/state.json", state)
            alert("Deployer: upload failed, rolled back", [f"{type(e).__name__}: {e}"] + commits[:10])
            sys.exit(1)

        bad = health(health_urls(cfg), cfg["crawl"]["user_agent"])
        if bad:
            rollback(journal, remote)
            after = health(health_urls(cfg), cfg["crawl"]["user_agent"])
            remote.close()
            state["failed_sha"] = head
            write_json("deploy/state.json", state)
            alert("ROLLED BACK: deploy broke the site", ["These pages failed after the deploy: " + "; ".join(bad),
                  "The previous files were restored. " + ("Site is OK again." if not after else
                                                          "STILL FAILING after rollback: " + "; ".join(after)),
                  "Changed files: " + ", ".join(uploads + deletes)] + commits[:10])
            sys.exit(1)
        remote.close()
        state["last_sha"] = head
        state.pop("failed_sha", None)
        state["history"].append({"at": now_iso(), "sha": head, "uploaded": uploads, "deleted": deletes,
                                 "skipped": skipped, "roots": roots})
        write_json("deploy/state.json", state)
        alert(f"Deployed {len(uploads) + len(deletes)} file(s) to the live site",
              ["Live check passed on: " + ", ".join(health_urls(cfg)),
               "Uploaded: " + (", ".join(uploads) or "none"), "Deleted: " + (", ".join(deletes) or "none"),
               ("Not deployed (manual only): " + ", ".join(skipped)) if skipped else ""] + commits[:10])


if __name__ == "__main__":
    main()
