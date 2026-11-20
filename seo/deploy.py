"""Deploy merged website changes to cPanel by FTP(S), with backup, live check and automatic rollback.

Flow:
1. Compare the website repo's main branch with the last deployed commit.
2. Keep only deployable files (deny-list below). Refuse if too many files changed at once.
3. Download a backup of every remote file about to change.
4. Upload changes (and the few allowed deletions). Clear Laravel's cached routes/config if needed.
5. Load key pages on both sites. If any fails, put the backups back and alert.
"""
import fnmatch
import io
import posixpath
import time
from ftplib import FTP, FTP_TLS, error_perm
from pathlib import Path

import requests

# Never deployed by the bot, whatever the repo says.
DENY = [".env*", ".git/*", ".git*", ".github/*", "scratch/*", "storage/*", "vendor/*", "node_modules/*", "tests/*",
        "database/*", "BackEndImage/*", "public/BackEndImage/*", "composer.*", "package*.json", "Dockerfile",
        "docker-*", "*.md", "phpunit.xml", ".cpanel.yml", "security.conf", ".editorconfig", "*.sql", "*.zip",
        "*.log", "add_*.php", "cookie*"]
# Deletions the bot may carry out on the server. Anything else deleted in the repo is reported, not deleted live.
ALLOWED_DELETIONS = {"sitemap.xml", "robots.txt"}


def deployable(path):
    return not any(fnmatch.fnmatch(path, pat) for pat in DENY)


class Remote:
    def __init__(self, host, user, password, port=21, tls=True):
        self.ftp = FTP_TLS(timeout=60) if tls else FTP(timeout=60)
        self.ftp.connect(host, port)
        self.ftp.login(user, password)
        if tls:
            self.ftp.prot_p()
        self.ftp.set_pasv(True)

    def read(self, path):
        buf = io.BytesIO()
        try:
            self.ftp.retrbinary(f"RETR {path}", buf.write)
            return buf.getvalue()
        except error_perm:
            return None  # file does not exist

    def mkdirs(self, d):
        parts, cur = [p for p in d.split("/") if p], ""
        for p in parts:
            cur += "/" + p
            try:
                self.ftp.mkd(cur)
            except error_perm:
                pass

    def write(self, path, data):
        self.mkdirs(posixpath.dirname(path))
        self.ftp.storbinary(f"STOR {path}", io.BytesIO(data))

    def delete(self, path):
        try:
            self.ftp.delete(path)
        except error_perm:
            pass

    def list(self, d):
        try:
            return self.ftp.nlst(d)
        except error_perm:
            return []

    def close(self):
        try:
            self.ftp.quit()
        except Exception:
            pass


def plan(changes, max_files):
    """changes: list of (status, path) from git. Returns uploads, deletions, skipped, refusal reason."""
    uploads, deletes, skipped = [], [], []
    for st, path in changes:
        if not deployable(path):
            skipped.append(path)
        elif st == "D":
            (deletes if path in ALLOWED_DELETIONS else skipped).append(path)
        else:
            uploads.append(path)
    if len(uploads) + len(deletes) > max_files:
        return uploads, deletes, skipped, (f"{len(uploads) + len(deletes)} files changed, above the safety limit of "
                                           f"{max_files}. Deploy this one by hand.")
    return uploads, deletes, skipped, None


def health(urls, ua, tries=2):
    bad = []
    for u in urls:
        ok, why = False, ""
        for _ in range(tries):
            try:
                r = requests.get(u, timeout=40, headers={"User-Agent": ua, "Cache-Control": "no-cache"})
                body = r.text[:200000].lower()
                if r.status_code == 200 and "whoops" not in body and "server error" not in body:
                    ok = True
                    break
                why = f"HTTP {r.status_code}"
            except requests.RequestException as e:
                why = type(e).__name__
            time.sleep(8)
        if not ok:
            bad.append(f"{u} ({why})")
    return bad


def deploy(repo_dir, uploads, deletes, roots, remote, backup_dir, clear_cache):
    """Returns a journal so the change can be undone."""
    journal = []  # (root, path, old_bytes_or_None)
    for root in roots:
        for path in uploads + deletes:
            rp = posixpath.join(root, path)
            old = remote.read(rp)
            journal.append((root, path, old))
            if old is not None:
                b = Path(backup_dir) / root.strip("/").replace("/", "_") / path
                b.parent.mkdir(parents=True, exist_ok=True)
                b.write_bytes(old)
        for path in uploads:
            remote.write(posixpath.join(root, path), (Path(repo_dir) / path).read_bytes())
        for path in deletes:
            remote.delete(posixpath.join(root, path))
        if clear_cache:
            # Same as the repo's .cpanel.yml: Laravel rebuilds these on the next request.
            for f in remote.list(posixpath.join(root, "bootstrap/cache")):
                name = posixpath.basename(f)
                if name.endswith(".php"):
                    rp = posixpath.join(root, "bootstrap/cache", name)
                    journal.append((root, f"bootstrap/cache/{name}", remote.read(rp)))
                    remote.delete(rp)
    return journal


def rollback(journal, remote):
    for root, path, old in reversed(journal):
        rp = posixpath.join(root, path)
        if old is None:
            remote.delete(rp)
        else:
            remote.write(rp, old)
