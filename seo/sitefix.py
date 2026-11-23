"""Turn today's findings into small, safe code changes in the website repo, on a branch, as a pull request.

Rules:
- Only fixes listed here are ever made. Each is deterministic, idempotent and small.
- PHP files are syntax-checked with `php -l`; a fix that fails the check is dropped.
- Nothing is merged or deployed here. Merging the PR is the human approval step.
"""
import json
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


HOST_MARK = f"Canonical host: https, no www ({MARK})"
HOST_BLOCK = (f"    # {HOST_MARK}\n"
              "    RewriteCond %{REQUEST_URI} !^/\\.well-known/ [NC]\n"
              "    RewriteCond %{HTTP_HOST} ^www\\.(.+)$ [NC]\n"
              "    RewriteRule ^ https://%1%{REQUEST_URI} [L,R=301]\n"
              "    RewriteCond %{REQUEST_URI} !^/\\.well-known/ [NC]\n"
              "    RewriteCond %{HTTPS} !=on\n"
              "    RewriteCond %{HTTP:X-Forwarded-Proto} !=https\n"
              "    RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]\n\n")

OVERRIDES_PATH = "resources/seo/overrides.json"
HEAD_HOOK = ("{!! function_exists('seo_head') ? seo_head($__env->yieldContent('headtags')) "
             ": $__env->yieldContent('headtags') !!}")

# Appended once to app/helpers.php. Reads resources/seo/overrides.json and swaps the page's title, description
# and canonical for listed paths. Any error returns the page head unchanged.
SEO_HEAD_PHP = r"""

if (!function_exists('seo_head')) {
    /**
     * Per-page SEO overrides (StaplerLabs SEO bot). Paths listed in resources/seo/overrides.json get the
     * title, meta description and canonical given there; everything else is left exactly as it was.
     * Delete a path from the JSON file to go back to the text set in the admin panel.
     */
    function seo_head(string $html): string
    {
        try {
            static $all = null;
            if ($all === null) {
                $file = resource_path('seo/overrides.json');
                $all = is_file($file) ? (json_decode((string) file_get_contents($file), true) ?: []) : [];
            }
            $host = preg_replace('/^www\./', '', strtolower((string) request()->getHost()));
            $path = '/' . trim((string) request()->path(), '/');
            $o = $all[$host][$path] ?? null;
            if (!is_array($o)) {
                return $html;
            }
            $esc = function ($s) {
                return htmlspecialchars((string) $s, ENT_QUOTES, 'UTF-8');
            };
            $put = function ($pattern, $value, $html) {
                return preg_replace_callback($pattern, function ($m) use ($value) {
                    return $m[1] . $value . $m[2];
                }, $html);
            };
            if (!empty($o['title'])) {
                $t = $esc($o['title']);
                $n = 0;
                $html = preg_replace_callback('~<title>.*?</title>~is', function () use ($t) {
                    return '<title>' . $t . '</title>';
                }, $html, 1, $n);
                if (!$n) {
                    $html = '<title>' . $t . "</title>\n" . $html;
                }
                $html = $put('~(<meta\s+(?:property|name)="(?:og|twitter):title"\s+content=")[^"]*(")~i', $t, $html);
            }
            if (!empty($o['description'])) {
                $d = $esc($o['description']);
                $n = 0;
                $html = preg_replace_callback('~(<meta\s+name="description"\s+content=")[^"]*(")~i', function ($m) use ($d) {
                    return $m[1] . $d . $m[2];
                }, $html, -1, $n);
                if (!$n) {
                    $html = '<meta name="description" content="' . $d . "\" />\n" . $html;
                }
                $html = $put('~(<meta\s+(?:property|name)="(?:og|twitter):description"\s+content=")[^"]*(")~i', $d, $html);
            }
            if (!empty($o['canonical'])) {
                $c = $esc($o['canonical']);
                $n = 0;
                $html = preg_replace_callback('~(<link\s+rel="canonical"\s+href=")[^"]*(")~i', function ($m) use ($c) {
                    return $m[1] . $c . $m[2];
                }, $html, -1, $n);
                if (!$n) {
                    $html = '<link rel="canonical" href="' . $c . "\" />\n" . $html;
                }
            }
            return $html;
        } catch (\Throwable $e) {
            return $html;
        }
    }
}
"""


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
    if "Block build and documentation files" in txt:
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


def fix_host_redirects(repo, rules):
    """www and http copies of both sites load with 200. One 301 to https without www, right after RewriteEngine On.
    Works for both domains because it keeps the requested host. /.well-known/ is left alone for SSL renewals."""
    if not rules & {"host_duplicate", "host_redirect_wrong"}:
        return None
    p = repo / ".htaccess"
    if not p.exists():
        return None
    txt = p.read_text(encoding="utf-8")
    if HOST_MARK in txt:
        return None
    lines = txt.splitlines(keepends=True)
    idx = next((i for i, l in enumerate(lines) if l.strip().lower() == "rewriteengine on"), None)
    if idx is None:
        return None
    lines.insert(idx + 1, "\n" + HOST_BLOCK)
    p.write_text("".join(lines), encoding="utf-8")
    return {"id": "host_redirects", "files": [".htaccess"], "deleted": [],
            "title": "301 www and http to https without www, on both domains",
            "why": "Today every page loads four ways (http/https, with/without www), and the www copy even sets "
                   "its own canonical. Google splits signals between the copies. The deploy's live check "
                   "follows redirects, so a redirect loop would fail it and roll back."}


def fix_seo_overrides(repo, overrides):
    """Install the overrides helper (once) and sync resources/seo/overrides.json with data/overrides.json."""
    if not overrides:
        return None
    changed, notes = [], []
    helpers = repo / "app/helpers.php"
    layout = repo / "resources/views/layouts/frontMaster.blade.php"
    if not helpers.exists() or not layout.exists():
        return None
    h = helpers.read_text(encoding="utf-8")
    if "function seo_head(" not in h:
        helpers.write_text(h.rstrip() + "\n" + SEO_HEAD_PHP, encoding="utf-8")
        if not _php_ok(helpers):
            helpers.write_text(h, encoding="utf-8")
            return None
        changed.append("app/helpers.php")
        notes.append("adds `seo_head()` to app/helpers.php")
    lt = layout.read_text(encoding="utf-8")
    if "seo_head(" not in lt:
        if lt.count("@yield('headtags')") != 1:
            return None
        layout.write_text(lt.replace("@yield('headtags')", HEAD_HOOK, 1), encoding="utf-8")
        changed.append("resources/views/layouts/frontMaster.blade.php")
        notes.append("frontMaster passes the page head through `seo_head()`")
    target = repo / OVERRIDES_PATH
    new = json.dumps(overrides, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    old = target.read_text(encoding="utf-8") if target.exists() else ""
    if new != old:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new, encoding="utf-8")
        changed.append(OVERRIDES_PATH)
    if not changed:
        return None
    before = json.loads(old) if old.strip() else {}
    lines = []
    for host, paths in overrides.items():
        for path, o in paths.items():
            was = before.get(host, {}).get(path, {})
            for k in ("title", "description", "canonical"):
                if o.get(k) and o.get(k) != was.get(k):
                    lines.append(f"- `{host}{path}` {k}: {o[k]}")
    detail = ("\n\nChanged entries:\n" + "\n".join(lines[:80]) + ("\n- ..." if len(lines) > 80 else "")) if lines else ""
    return {"id": "seo_overrides", "files": changed, "deleted": [],
            "title": f"Page titles, descriptions and canonicals ({len(lines)} changes)",
            "why": "Titles and descriptions live in the admin panel database, which the bot never touches. "
                   "These overrides sit in one JSON file and win over the database text for the listed paths only. "
                   "Foundation copies of clinic pages point their canonical to the clinic site. "
                   "Remove a path from the file to undo it." + (" Setup: " + "; ".join(notes) + "." if notes else "")
                   + detail}


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


def apply_fixes(repo_dir, issues, generated_dir, overrides=None):
    repo = Path(repo_dir)
    rules = _rules(issues)
    out = []
    for fn in (lambda: fix_static_sitemap_robots(repo, rules), lambda: fix_host_redirects(repo, rules),
               lambda: fix_htaccess_block(repo, rules), lambda: fix_twitter_card(repo, rules),
               lambda: fix_llms(repo, rules, generated_dir), lambda: fix_seo_overrides(repo, overrides)):
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
