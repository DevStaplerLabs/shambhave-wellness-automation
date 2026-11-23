"""Crawl each site's sitemap and run technical SEO / GEO checks. No AI, no cost.

Only public pages are requested. Nothing is ever submitted, posted or logged into.
"""
import json
import re
import time
from collections import defaultdict
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .store import now_iso

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class Fetcher:
    def __init__(self, cfg):
        c = cfg["crawl"]
        self.timeout = c["timeout_seconds"]
        self.delay = c["delay_seconds"]
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": c["user_agent"], "Accept-Language": "en-IN,en;q=0.9"})
        self._last = 0.0

    def get(self, url, ua=None, allow_redirects=True, method="GET"):
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        headers = {"User-Agent": ua} if ua else None
        result = None
        for attempt in range(2):  # one retry for flaky hosting
            t0 = time.time()
            try:
                r = self.s.request(method, url, timeout=self.timeout, allow_redirects=allow_redirects, headers=headers)
                r.elapsed_ms = int((time.time() - t0) * 1000)
                result = r
                if r.status_code < 500:
                    return r
            except requests.RequestException as e:
                result = e
            if attempt == 0:
                time.sleep(3)
        return result


def issue(site, rule, severity, url, detail):
    return {"id": f"{site}|{rule}|{url}", "site": site, "rule": rule,
            "severity": severity, "url": url, "detail": detail}


# ---------- sitemap ----------

def sitemap_urls(fetcher, sitemap_url, limit, lastmods=None):
    urls, seen_maps = [], set()
    queue = [sitemap_url]
    while queue and len(urls) < limit:
        sm = queue.pop(0)
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        r = fetcher.get(sm)
        if isinstance(r, Exception) or r.status_code != 200:
            continue
        soup = BeautifulSoup(r.content, "xml")
        if soup.find("sitemapindex"):
            queue += [l.text.strip() for l in soup.find_all("loc")]
        else:
            for u in soup.find_all("url"):
                loc = u.find("loc")
                if loc:
                    urls.append(loc.text.strip())
                    lm = u.find("lastmod")
                    if lastmods is not None and lm:
                        lastmods.append(lm.text.strip()[:10])
    # keep order, drop duplicates
    out, seen = [], set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:limit]


# ---------- page checks ----------

def parse_jsonld(soup):
    blocks = []
    for s in soup.find_all("script", type="application/ld+json"):
        raw = s.string or s.get_text() or ""
        b = {"valid_json": False, "has_context": False, "types": [], "php_leak": "<?php" in raw}
        try:
            data = json.loads(raw)
            b["valid_json"] = True
            items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
            if isinstance(data, dict):
                b["has_context"] = "@context" in data
            elif isinstance(data, list):
                b["has_context"] = all(isinstance(i, dict) and "@context" in i for i in data)
            for it in items:
                if isinstance(it, dict):
                    t = it.get("@type")
                    b["types"] += t if isinstance(t, list) else [t] if t else []
        except (json.JSONDecodeError, AttributeError):
            pass
        blocks.append(b)
    return blocks


def page_facts(url, r):
    soup = BeautifulSoup(r.content, "lxml")
    for t in soup(["script", "style", "noscript", "svg"]):
        if t.name != "script" or t.get("type") != "application/ld+json":
            t.extract()
    meta = lambda **kw: (soup.find("meta", attrs=kw) or {}).get("content")
    canon = soup.find("link", rel="canonical")
    imgs = soup.find_all("img")
    text = soup.get_text(" ", strip=True)
    return {
        "url": url,
        "final_url": r.url,
        "status": r.status_code,
        "redirects": len(r.history),
        "ms": getattr(r, "elapsed_ms", None),
        "html_kb": round(len(r.content) / 1024, 1),
        "title": (soup.title.get_text(strip=True) if soup.title else "") or "",
        "description": (meta(name="description") or "").strip(),
        "canonical": canon.get("href") if canon else None,
        "robots": (meta(name="robots") or "").lower(),
        "h1": [h.get_text(" ", strip=True) for h in soup.find_all("h1")],
        "h2_count": len(soup.find_all("h2")),
        "img_total": len(imgs),
        "img_no_alt": sum(1 for i in imgs if i.get("alt") is None),
        "preloader_alt": next((i.get("alt") for i in imgs if "please wait" in (i.get("alt") or "").lower()), None),
        "og_title": meta(property="og:title"),
        "og_image": meta(property="og:image"),
        "twitter_card": meta(name="twitter:card") or meta(property="twitter:card"),
        "lang": (soup.html.get("lang") if soup.html else None),
        "x_robots": (r.headers.get("X-Robots-Tag") or "").lower(),
        "img_no_size": sum(1 for i in imgs if not (i.get("width") and i.get("height"))),
        "img_srcs": [urljoin(url, i["src"]) for i in imgs if i.get("src") and not i["src"].startswith("data:")][:40],
        "mixed_content": sum(1 for t in BeautifulSoup(r.content, "lxml").find_all(["img", "script", "link", "iframe"])
                             if url.startswith("https://") and (t.get("src") or t.get("href") or "").startswith("http://")),
        "jsonld": parse_jsonld(BeautifulSoup(r.content, "lxml")),
        "words": len(text.split()),
        "first_text": text[:160],
        "text_sample": text[:1500],
        "internal_links": sorted({urljoin(url, a["href"]).split("#")[0]
                                  for a in soup.find_all("a", href=True)
                                  if urlparse(urljoin(url, a["href"])).netloc == urlparse(url).netloc}),
    }


def page_issues(site, f, lim):
    out = []
    u = f["url"]
    if f["status"] >= 400:
        sev = "critical" if f["status"] >= 500 else "high"
        return [issue(site, "page_status", sev, u, f"Returns HTTP {f['status']}")]
    if f["redirects"]:
        out.append(issue(site, "sitemap_redirect", "low", u, f"Sitemap URL redirects to {f['final_url']}"))
    if "noindex" in f.get("x_robots", ""):
        out.append(issue(site, "noindex_header", "critical", u, "X-Robots-Tag header says noindex"))
    if f.get("mixed_content"):
        out.append(issue(site, "mixed_content", "medium", u, f"{f['mixed_content']} resources load over http on an https page"))
    if f.get("img_no_size", 0) > 5:
        out.append(issue(site, "img_no_dimensions", "low", u,
                         f"{f['img_no_size']} images have no width/height, which causes layout shift (CLS)"))
    if "noindex" in f["robots"]:
        out.append(issue(site, "noindex", "critical", u, "Page is set to noindex"))
    t = f["title"]
    if not t:
        out.append(issue(site, "title_missing", "high", u, "No <title>"))
    elif not lim["title_min"] <= len(t) <= lim["title_max"]:
        out.append(issue(site, "title_length", "low", u, f"Title is {len(t)} chars: {t}"))
    if re.search(r"\bbest\b", t, re.I):
        out.append(issue(site, "title_superlative", "low", u, f"Self-applied 'best' in title: {t}"))
    d = f["description"]
    if not d:
        out.append(issue(site, "description_missing", "high", u, "No meta description"))
    elif not lim["description_min"] <= len(d) <= lim["description_max"]:
        out.append(issue(site, "description_length", "low", u, f"Description is {len(d)} chars"))
    if not f["canonical"]:
        out.append(issue(site, "canonical_missing", "medium", u, "No canonical tag"))
    elif f["canonical"].rstrip("/") != f["final_url"].rstrip("/"):
        out.append(issue(site, "canonical_other", "low", u, f"Canonical points to {f['canonical']}"))
    if len(f["h1"]) == 0:
        out.append(issue(site, "h1_missing", "medium", u, "No H1"))
    elif len(f["h1"]) > 1:
        out.append(issue(site, "h1_multiple", "low", u, f"{len(f['h1'])} H1 tags"))
    if f["img_no_alt"]:
        out.append(issue(site, "img_alt_missing", "low", u, f"{f['img_no_alt']} of {f['img_total']} images have no alt"))
    if f["html_kb"] > lim["max_html_kb"]:
        out.append(issue(site, "html_heavy", "medium", u, f"HTML is {f['html_kb']} KB"))
    if not f["og_image"]:
        out.append(issue(site, "og_image_missing", "low", u, "No og:image"))
    if not f["twitter_card"]:
        out.append(issue(site, "twitter_card_missing", "low", u, "No twitter:card"))
    for i, b in enumerate(f["jsonld"]):
        if b["php_leak"]:
            out.append(issue(site, f"schema_php_leak_{i}", "critical", u,
                             f"JSON-LD block {i + 1} contains leaked PHP template code (types: {b['types']})"))
        elif not b["valid_json"]:
            out.append(issue(site, f"schema_invalid_{i}", "high", u, f"JSON-LD block {i + 1} is not valid JSON"))
        elif not b["has_context"]:
            out.append(issue(site, f"schema_no_context_{i}", "high", u,
                             f"JSON-LD block {i + 1} has no @context (types: {b['types']})"))
    if "please wait" in f["first_text"].lower() or f.get("preloader_alt"):
        out.append(issue(site, "preloader_text", "medium", u,
                         "Preloader text can appear in search snippets: " + (f.get("preloader_alt") or f["first_text"][:60])))
    path = urlparse(u).path
    if ("/service/" in path or "/blog/" in path) and f["words"] < lim["min_words_service_page"]:
        out.append(issue(site, "thin_content", "medium", u, f"About {f['words']} words of visible text"))
    types = {t for b in f["jsonld"] for t in b["types"]}
    if "/service/" in path and "FAQPage" not in types:
        out.append(issue(site, "faq_schema_missing", "medium", u,
                         "Service page has no FAQ section with FAQPage schema (strong signal for AI answers)"))
    if path.startswith("/blog/") and not types & {"BlogPosting", "Article", "MedicalWebPage"}:
        out.append(issue(site, "article_schema_missing", "medium", u, "Article page has no BlogPosting/Article schema"))
    return out


# ---------- site checks ----------

def robots_blocks(robots_txt, bot):
    """True if robots.txt disallows '/' for this bot (simple group parser)."""
    groups, agents, rules = [], [], []
    for line in robots_txt.splitlines():
        line = line.split("#")[0].strip()
        if not line or ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        k = k.lower()
        if k == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(v.lower())
        elif k in ("allow", "disallow"):
            rules.append((k, v))
    if agents:
        groups.append((agents, rules))
    match = [g for g in groups if bot.lower() in g[0]] or [g for g in groups if "*" in g[0]]
    for _, rs in match:
        if ("disallow", "/") in rs and ("allow", "/") not in rs:
            return True
    return False


def site_checks(fetcher, cfg, site, page_urls):
    key, base = site["key"], site["base_url"].rstrip("/")
    host = urlparse(base).netloc
    out, facts = [], {}

    # robots.txt and AI crawlers
    r = fetcher.get(base + "/robots.txt")
    robots = r.text if not isinstance(r, Exception) and r.status_code == 200 else ""
    facts["robots_txt"] = robots[:2000]
    if not robots:
        out.append(issue(key, "robots_missing", "medium", base + "/robots.txt", "robots.txt not found"))
    for line in robots.splitlines():
        if line.lower().startswith("sitemap:"):
            sm_host = urlparse(line.split(":", 1)[1].strip()).netloc.removeprefix("www.")
            if sm_host and sm_host != host.removeprefix("www."):
                out.append(issue(key, "robots_sitemap_wrong_host", "critical", base + "/robots.txt",
                                 f"robots.txt points to another domain's sitemap: {line.strip()}"))
    blocked = [b for b in cfg["crawl"]["ai_bots"] if robots and robots_blocks(robots, b)]
    if blocked:
        out.append(issue(key, "robots_blocks_ai", "high", base + "/robots.txt", "robots.txt blocks: " + ", ".join(blocked)))

    # Real access test with AI crawler user agents (firewalls can block them even when robots.txt allows)
    normal = fetcher.get(base + "/")
    normal_ok = not isinstance(normal, Exception) and normal.status_code == 200
    facts["home_ok"] = normal_ok
    if not normal_ok:
        out.append(issue(key, "home_down", "critical", base + "/",
                         f"Homepage not reachable: {normal if isinstance(normal, Exception) else normal.status_code}"))
    refused = []
    for bot in ("GPTBot", "ClaudeBot", "PerplexityBot"):
        rr = fetcher.get(base + "/", ua=f"Mozilla/5.0 (compatible; {bot}/1.0)")
        if isinstance(rr, Exception) or rr.status_code >= 400:
            refused.append(f"{bot} ({'error' if isinstance(rr, Exception) else rr.status_code})")
    facts["ai_bots_refused"] = refused
    if normal_ok and refused:
        out.append(issue(key, "ai_bots_refused", "critical", base + "/", "Server refuses AI crawlers: " + ", ".join(refused)))

    # llms.txt
    r = fetcher.get(base + "/llms.txt")
    has_llms = not isinstance(r, Exception) and r.status_code == 200 and "text/html" not in r.headers.get("content-type", "")
    facts["llms_txt"] = has_llms
    if not has_llms:
        out.append(issue(key, "llms_missing", "medium", base + "/llms.txt", "No llms.txt"))

    # www and http redirects
    for variant in (f"https://www.{host}/", f"http://{host}/"):
        if host.startswith("www.") or variant.rstrip("/") == base or urlparse(variant).hostname.startswith("www.127"):
            continue
        rr = fetcher.get(variant, allow_redirects=False)
        if isinstance(rr, Exception):
            continue
        loc = rr.headers.get("location", "")
        if rr.status_code == 200:
            out.append(issue(key, "host_duplicate", "high", variant,
                             f"{variant} loads with 200 as well as {base}/. Pick one version and 301 the other."))
        elif rr.status_code in (301, 308) and urlparse(loc).netloc not in (host, ""):
            out.append(issue(key, "host_redirect_wrong", "medium", variant, f"Redirects to {loc}"))

    # Root-level duplicates of /service/<slug>
    dups = []
    for u in page_urls:
        p = urlparse(u).path
        if p.startswith("/service/"):
            alt = base + "/" + p.split("/service/", 1)[1]
            rr = fetcher.get(alt, allow_redirects=False)
            if not isinstance(rr, Exception) and rr.status_code == 200:
                dups.append(alt)
    for d in dups:
        out.append(issue(key, "duplicate_url", "high", d, "Loads with 200 instead of 301 to the /service/ URL"))

    # Sensitive files
    for p in cfg["crawl"]["sensitive_paths"]:
        rr = fetcher.get(base + p, allow_redirects=False, method="HEAD")
        if not isinstance(rr, Exception) and rr.status_code == 200:
            out.append(issue(key, "exposed_file", "critical" if p in ("/.env", "/.git/config", "/scratch/") else "medium",
                             base + p, "Publicly downloadable"))
    return out, facts


def cross_page_issues(site, pages):
    out = []
    for field, rule in (("title", "title_duplicate"), ("description", "description_duplicate")):
        groups = defaultdict(list)
        for f in pages:
            if f.get("status") == 200 and f.get(field):
                groups[f[field]].append(f["url"])
        for val, urls in groups.items():
            if len(urls) > 1:
                for u in urls:
                    out.append(issue(site, rule, "medium", u, f"Same {field} on {len(urls)} pages: {val[:80]}"))
    return out


SKIP_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".pdf", ".mp4", ".css", ".js", ".ico", ".zip")


def norm(u):
    p = urlparse(u)
    return f"{p.scheme}://{p.netloc.removeprefix('www.')}{p.path.rstrip('/') or '/'}"


def link_issues(fetcher, cfg, site, sitemap, pages):
    """Broken internal links and orphan pages (in the sitemap but linked from nowhere)."""
    key, out = site["key"], []
    in_sitemap = {norm(u) for u in sitemap}
    linked_from = defaultdict(set)
    for f in pages:
        for l in f.get("internal_links", []):
            if l.lower().endswith(SKIP_EXT) or "javascript:" in l:
                continue
            linked_from[norm(l)].add(f["url"])
    ok_status = {norm(f["url"]): f.get("status") for f in pages}
    # Check links that point outside the sitemap (limit for politeness)
    to_check = [l for l in linked_from if l not in in_sitemap and not any(x in l for x in ("/login", "/admin", "/student", "/payment", "/api/", "/cdn-cgi/"))]
    for l in to_check[: cfg["crawl"].get("max_link_checks", 120)]:
        r = fetcher.get(l, method="HEAD")
        st = r.status_code if not isinstance(r, Exception) else 0
        if st == 405:
            r = fetcher.get(l)
            st = r.status_code if not isinstance(r, Exception) else 0
        ok_status[l] = st
        if st >= 400 or st == 0:
            src = sorted(linked_from[l])[:3]
            out.append(issue(key, "broken_link", "high", l, f"Linked from {len(linked_from[l])} page(s), e.g. {src[0]}, returns {st or 'error'}"))
    home = norm(site["base_url"])
    live = {f["url"] for f in pages if f.get("status") == 200}
    for u in sitemap:
        n = norm(u)
        if u in live and n != home and not (linked_from.get(n, set()) - {u}):
            out.append(issue(key, "orphan_page", "medium", u, "In the sitemap but no other page links to it"))
    return out


def image_issues(fetcher, site, pages, limit_kb=300):
    """HEAD the images on the homepage and up to 4 other pages; flag heavy ones."""
    out, seen = [], set()
    sample = [p for p in pages if p.get("img_srcs")][:5]
    for p in sample:
        for src in p["img_srcs"][:15]:
            if src in seen:
                continue
            seen.add(src)
            r = fetcher.get(src, method="HEAD")
            if isinstance(r, Exception):
                continue
            kb = int(r.headers.get("content-length", 0) or 0) / 1024
            if kb > limit_kb:
                out.append(issue(site["key"], "image_heavy", "medium", src, f"{round(kb)} KB image on {p['url']}"))
    return out


def discover(fetcher, base_url, limit):
    """Fallback when the sitemap is unusable: follow internal links from the homepage."""
    start = base_url.rstrip("/") + "/"
    seen, queue = [], [start]
    while queue and len(seen) < min(limit, 80):
        u = queue.pop(0)
        if u in seen:
            continue
        seen.append(u)
        r = fetcher.get(u)
        if isinstance(r, Exception) or r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            continue
        soup = BeautifulSoup(r.content, "lxml")
        for a in soup.find_all("a", href=True):
            l = urljoin(u, a["href"]).split("#")[0].split("?")[0]
            if urlparse(l).netloc == urlparse(start).netloc and not l.lower().endswith(SKIP_EXT) \
                    and not any(x in l for x in ("/login", "admin", "/student", "/payment", "/api/")) and l not in seen:
                queue.append(l)
    return seen


def audit_site(fetcher, cfg, site):
    lim = cfg["limits"]
    lastmods = []
    limit = cfg["crawl"]["max_pages_per_site"]
    urls = sitemap_urls(fetcher, site["sitemap"], limit, lastmods)
    issues, pages = [], []
    host = urlparse(site["base_url"]).netloc.removeprefix("www.")
    foreign = [u for u in urls if urlparse(u).netloc.removeprefix("www.") != host]
    if foreign:
        issues.append(issue(site["key"], "sitemap_wrong_host", "critical", site["sitemap"],
                            f"{len(foreign)} of {len(urls)} sitemap URLs belong to another domain "
                            f"(e.g. {foreign[0]}). This site's own pages are not being submitted to Google."))
        urls = [u for u in urls if u not in foreign]
    if not urls:
        if not foreign:
            issues.append(issue(site["key"], "sitemap_empty", "critical", site["sitemap"], "Sitemap missing, empty or unreachable"))
        urls = discover(fetcher, site["base_url"], limit)
    for u in urls:
        r = fetcher.get(u)
        if isinstance(r, Exception):
            issues.append(issue(site["key"], "page_error", "high", u, f"Request failed: {type(r).__name__}"))
            continue
        if r.status_code >= 400 or "html" not in r.headers.get("content-type", "html"):
            f = {"url": u, "status": r.status_code, "final_url": r.url}
        else:
            f = page_facts(u, r)
        pages.append(f)
        issues += page_issues(site["key"], f, lim) if "title" in f else [
            issue(site["key"], "page_status", "critical" if r.status_code >= 500 else "high", u, f"Returns HTTP {r.status_code}")]
    issues += cross_page_issues(site["key"], pages)
    issues += link_issues(fetcher, cfg, site, urls, pages)
    issues += image_issues(fetcher, site, pages)
    today_str = time.strftime("%Y-%m-%d")
    if lastmods and sum(1 for d in lastmods if d == today_str) / len(lastmods) > 0.8 and len(lastmods) > 5:
        issues.append(issue(site["key"], "lastmod_unreliable", "low", site["sitemap"],
                            "Most sitemap lastmod dates are today's date; Google learns to ignore them. Use real edit dates."))
    s_issues, facts = site_checks(fetcher, cfg, site, urls)
    issues += s_issues
    issues.sort(key=lambda i: (SEVERITY_ORDER[i["severity"]], i["rule"], i["url"]))
    return {"site": site["key"], "name": site["name"], "pages": pages, "issues": issues, "facts": facts,
            "page_count": len(pages)}


def page_path(url):
    return urlparse(url).path.rstrip("/") or "/"


def cross_site_issues(cfg, sites):
    """Pages served on both domains with the same title (the clinic's service and course pages also load on
    the foundation domain). Google then has to pick one; the copy on the other domain should point its
    canonical at the owner site. `cross_site.canonical_owner` in config.yaml names the owner."""
    owner_key = (cfg.get("cross_site") or {}).get("canonical_owner")
    by = {s["site"]: s for s in sites}
    owner_cfg = next((c for c in cfg["sites"] if c["key"] == owner_key), None)
    if not owner_cfg or owner_key not in by:
        return
    base = owner_cfg["base_url"].rstrip("/")
    own = {page_path(p["url"]): p for p in by[owner_key]["pages"] if p.get("status") == 200 and p.get("title")}
    for s in sites:
        if s["site"] == owner_key:
            continue
        for p in s["pages"]:
            path = page_path(p["url"])
            o = own.get(path)
            if path == "/" or p.get("status") != 200 or not o or o["title"] != p.get("title"):
                continue
            target = base + path
            if norm(p.get("canonical") or "") == norm(target):
                continue  # already points at the owner
            s["issues"].append(issue(s["site"], "cross_site_duplicate", "high", p["url"],
                                     f"Same page as {target} (same title). Point this page's canonical there."))


def run_audit(cfg):
    fetcher = Fetcher(cfg)
    sites = [audit_site(fetcher, cfg, s) for s in cfg["sites"]]
    cross_site_issues(cfg, sites)
    for s in sites:
        s["issues"].sort(key=lambda i: (SEVERITY_ORDER[i["severity"]], i["rule"], i["url"]))
    return {"run_at": now_iso(), "sites": sites}


def score(site_audit):
    """0-100 health score. Each kind of problem costs points by severity; more pages with the
    same problem cost a little more (log scale), so fixing a whole kind of problem moves the score."""
    import math
    w = {"critical": 12, "high": 5, "medium": 2, "low": 0.7}
    groups = defaultdict(list)
    for i in site_audit["issues"]:
        groups[(re.sub(r"_\d+$", "", i["rule"]), i["severity"])].append(i)
    penalty = sum(w[sev] * (1 + math.log2(len(items))) for (_, sev), items in groups.items())
    return max(0, round(100 - penalty))


def diff(prev, cur):
    """New and resolved issue ids between two audits."""
    p = {i["id"]: i for s in (prev or {}).get("sites", []) for i in s["issues"]}
    c = {i["id"]: i for s in cur["sites"] for i in s["issues"]}
    return {"new": [c[k] for k in c if k not in p], "resolved": [p[k] for k in p if k not in c]}
