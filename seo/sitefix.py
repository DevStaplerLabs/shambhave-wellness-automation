"""Turn today's findings into small, safe code changes in the website repo, on a branch, as a pull request.

Rules:
- Only fixes listed here are ever made. Each is deterministic, idempotent and small.
- PHP files are syntax-checked with `php -l`; a fix that fails the check is dropped.
- Nothing is merged or deployed here. Merging the PR is the human approval step.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

MARK = "StaplerLabs SEO bot"

LLMS_ROUTE = """
// llms.txt per domain ({mark})
Route::get('/llms.txt', function () {{
    $site = (function_exists('is_foundation_site') && is_foundation_site()) ? 'foundation' : 'wellness';
    $file = resource_path('llms/' . $site . '.txt');
    abort_unless(is_file($file), 404);
    return response(file_get_contents($file), 200)->header('Content-Type', 'text/plain; charset=UTF-8');
}});
""".format(mark=MARK)

HTACCESS_BLOCK = (f"    # Block build and documentation files ({MARK})\n"
                  "    RewriteRule ^(composer\\.(json|lock|phar)|Dockerfile|docker-compose\\.yml|README\\.md|"
                  "security\\.conf|package(-lock)?\\.json|vite\\.config\\.js|artisan|phpunit\\.xml)$ - [F,L,NC]\n")


def _rules(issues):
    return {re.sub(r"_\d+$", "", i["rule"]) for i in issues}


def _php_ok(path):
    if not shutil.which("php"):
        return True
    r = subprocess.run(["php", "-l", str(path)], capture_output=True, text=True)
    return r.returncode == 0


def fix_static_sitemap_robots(repo, rules):
    """Static sitemap.xml/robots.txt in the web root override the per-domain routes. Remove them."""
    if not rules & {"sitemap_wrong_host", "robots_sitemap_wrong_host"}:
        return None
    web = (repo / "routes/web.php").read_text(encoding="utf-8")
    if "Route::get('/sitemap.xml'" not in web or "Route::get('/robots.txt'" not in web:
        return None  # only safe if the dynamic routes exist
    removed = [f for f in ("sitemap.xml", "robots.txt") if (repo / f).exists()]
    for f in removed:
        (repo / f).unlink()
    if not removed:
        return None
    return {"id": "static_sitemap_robots", "files": removed, "deleted": removed,
            "title": "Remove static sitemap.xml and robots.txt so each domain gets its own",
            "why": "Apache serves real files before Laravel routes, so both domains were serving the old main-site "
                   "sitemap (www URLs, 45 pages). The foundation's own pages were not submitted to Google."}


def fix_llms(repo, rules, generated_dir):
    """Per-domain llms.txt served by a small route (both domains share one web root)."""
    srcs = {k: Path(generated_dir) / k / "llms.txt" for k in ("wellness", "foundation")}
    if not all(p.exists() for p in srcs.values()):
        return None
    changed = []
    dest = repo / "resources/llms"
    dest.mkdir(parents=True, exist_ok=True)
    for k, src in srcs.items():
        new = src.read_text(encoding="utf-8")
        target = dest / f"{k}.txt"
        if not target.exists() or target.read_text(encoding="utf-8") != new:
            target.write_text(new, encoding="utf-8")
            changed.append(f"resources/llms/{k}.txt")
    web_p = repo / "routes/web.php"
    web = web_p.read_text(encoding="utf-8")
    if "Route::get('/llms.txt'" not in web:
        anchor = "Route::get('/robots.txt', [SitemapController::class, 'robots']);"
        if anchor not in web:
            return None
        backup = web
        web_p.write_text(web.replace(anchor, anchor + "\n" + LLMS_ROUTE, 1), encoding="utf-8")
        if not _php_ok(web_p):
            web_p.write_text(backup, encoding="utf-8")
            return None
        changed.append("routes/web.php")
    if not changed:
        return None
    return {"id": "llms_txt", "files": changed, "deleted": [],
            "title": "Add llms.txt for both domains",
            "why": "Gives AI assistants a clean summary of each site and its key pages. Rebuilt from live pages daily."}


def fix_htaccess_block(repo, rules):
    if "exposed_file" not in rules:
        return None
    p = repo / ".htaccess"
    if not p.exists():
        return None
    txt = p.read_text(encoding="utf-8")
    if MARK in txt:
        return None
    lines = txt.splitlines(keepends=True)
    idx = next((i for i, l in enumerate(lines) if "RewriteRule ^scratch" in l), None)
    if idx is None:
        idx = next((i for i, l in enumerate(lines) if l.strip().lower() == "rewriteengine on"), None)
    if idx is None:
        return None
    lines.insert(idx + 1, HTACCESS_BLOCK)
    p.write_text("".join(lines), encoding="utf-8")
    return {"id": "htaccess_block", "files": [".htaccess"], "deleted": [],
            "title": "Block public access to build files (composer.lock, Dockerfile, README.md and similar)",
            "why": "These files reveal package versions and server setup. They are never needed by visitors."}


def fix_twitter_card(repo, rules):
    if "twitter_card_missing" not in rules:
        return None
    p = repo / "resources/views/layouts/frontMaster.blade.php"
    if not p.exists():
        return None
    txt = p.read_text(encoding="utf-8")
    if "twitter:card" in txt:
        return None
    m = re.search(r"^([ \t]*)<meta property=\"og:image:alt\"[^\n]*\n", txt, re.M) or \
        re.search(r"^([ \t]*)<meta property=\"og:image\"[^\n]*\n", txt, re.M)
    if not m:
        return None
    tag = f'{m.group(1)}<meta name="twitter:card" content="summary_large_image" />\n'
    p.write_text(txt[: m.end()] + tag + txt[m.end():], encoding="utf-8")
    return {"id": "twitter_card", "files": ["resources/views/layouts/frontMaster.blade.php"], "deleted": [],
            "title": "Add twitter:card so shared links show a large preview",
            "why": "X/Twitter, Slack and some messaging apps use it; it falls back to the existing og: tags."}


def apply_fixes(repo_dir, issues, generated_dir):
    repo = Path(repo_dir)
    rules = _rules(issues)
    out = []
    for fn in (lambda: fix_static_sitemap_robots(repo, rules), lambda: fix_htaccess_block(repo, rules),
               lambda: fix_twitter_card(repo, rules), lambda: fix_llms(repo, rules, generated_dir)):
        try:
            r = fn()
        except Exception as e:  # one bad fix must not block the others
            r = None
            print(f"fix skipped: {type(e).__name__}: {e}")
        if r:
            out.append(r)
    return out


def pr_body(fixes, day):
    parts = [f"Automated SEO fixes found by the daily check on {day}.\n",
             "**Merging this PR deploys the changed files to the live sites by FTP** (backup first, live check after, "
             "automatic rollback if either site fails to load).\n"]
    for f in fixes:
        parts.append(f"### {f['title']}\n{f['why']}\n\nFiles: " + ", ".join(f"`{x}`" for x in f["files"])
                     + (" (deleted)" if f["deleted"] else "") + "\n")
    parts.append("\n_Generated by the StaplerLabs SEO automation. Review the diff before merging._")
    return "\n".join(parts)


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
