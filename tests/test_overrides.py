"""Tests for the auto-applied titles/descriptions/canonicals and the website fixes that carry them."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from seo import overrides as ov
from seo.crawl import cross_site_issues
from seo.sitefix import apply_fixes

CFG = yaml.safe_load(open("config.yaml"))
LIM = CFG["limits"]


def test_check_text_rules():
    ok = "Narcissistic Abuse Recovery Therapy | Shambhave Wellness"
    assert ov.check_text("title", ok, LIM) == []
    assert ov.check_text("title", "Best Narcissistic Abuse Therapist | Shambhave Wellness", LIM)
    assert ov.check_text("title", "Abuse Recovery Therapy — Gurugram | Shambhave Wellness", LIM)
    assert ov.check_text("title", "Short", LIM)
    assert ov.check_text("title", "Therapy Sessions from Rs. 3500 | Shambhave Wellness", LIM)
    assert ov.check_text("title", "Anxiety Therapy That Cures Panic | Shambhave Wellness", LIM)
    assert ov.check_text("title", "Anxiety vs Stress: Key Differences | Shambave Wellness", LIM)
    # A banned word is allowed only when it is the clinic's own service name.
    t = "Personality Profiling, Growth Coaching | Shambhave Wellness"
    assert ov.check_text("title", t, LIM)
    assert ov.check_text("title", t, LIM, allowed_words="Personality Profiling & Personal Growth Coaching") == []


def _site(key, pages, issues=None):
    return {"site": key, "pages": pages, "issues": issues or []}


def test_cross_site_duplicates_get_canonicals():
    pg = lambda host, path, title, canon=None: {"url": f"https://{host}{path}", "status": 200, "title": title,
                                                 "canonical": canon or f"https://{host}{path}"}
    w = _site("wellness", [pg("www.shambhavewellness.org", "/family-therapy", "Family Therapy Gurgaon"),
                           pg("www.shambhavewellness.org", "/about-us", "About the clinic")])
    f = _site("foundation", [pg("foundation.shambhavewellness.org", "/family-therapy", "Family Therapy Gurgaon"),
                             pg("foundation.shambhavewellness.org", "/about-us", "About the foundation"),
                             pg("foundation.shambhavewellness.org", "/", "Home")])
    cross_site_issues(CFG, [w, f])
    assert [i["url"] for i in f["issues"]] == ["https://foundation.shambhavewellness.org/family-therapy"]
    assert not w["issues"]
    data = {}
    added = ov.cross_site_canonicals(CFG, {"sites": [w, f]}, data, "2026-11-23")
    assert added and data["foundation.shambhavewellness.org"]["/family-therapy"]["canonical"] == \
        "https://shambhavewellness.org/family-therapy"
    # Already canonicalised pages are not flagged again.
    f2 = _site("foundation", [pg("foundation.shambhavewellness.org", "/family-therapy", "Family Therapy Gurgaon",
                                 "https://shambhavewellness.org/family-therapy")])
    cross_site_issues(CFG, [w, f2])
    assert not f2["issues"]


class FakeAI:
    def __init__(self, reply):
        self.reply = reply

    def ask(self, *a, **k):
        return self.reply, None


def test_propose_copy_validates_and_queues():
    url = "https://foundation.shambhavewellness.org/blog/how-therapy-helps-build-emotional-resilience"
    url2 = "https://foundation.shambhavewellness.org/course/youth-parenting-relationship-training"
    pages = [{"url": url, "status": 200, "title": "How Therapy Helps Build Emotional Resilience | Shambave Wellness Foundation",
              "description": "x" * 120, "h1": ["How therapy helps"], "text_sample": "..."},
             {"url": url2, "status": 200, "title": "Youth, Parenting & Relationship Training | Shambhave Foundation",
              "description": "", "h1": ["Youth training"], "text_sample": "..."}]
    issues = [{"rule": "title_length", "severity": "low", "url": url, "detail": "Title is 68 chars"},
              {"rule": "description_missing", "severity": "high", "url": url2, "detail": "No meta description"}]
    audit = {"sites": [_site("foundation", pages, issues)]}
    reply = json.dumps([
        {"url": url, "title": "Therapy and Emotional Resilience | Shambhave Foundation"},
        {"url": url2, "description": "The best youth course in India, guaranteed results for every family."},
    ])
    data = {}
    queued, rejected, note = ov.propose_copy(CFG, audit, data, "2026-11-23", FakeAI(reply))
    assert note is None
    assert [q["field"] for q in queued] == ["title"]
    assert rejected and rejected[0]["field"] == "description"
    host = data["foundation.shambhavewellness.org"]
    assert host["/blog/how-therapy-helps-build-emotional-resilience"]["title"].startswith("Therapy and")
    assert "/course/youth-parenting-relationship-training" not in host
    # Next day: the title is already overridden, so only the rejected description is asked again.
    todo, _ = ov.pick_pages(audit, data, 8)
    assert [(t["url"], sorted(t["fields"])) for t in todo] == [(url2, ["description"])]
    assert ov.export(data) == {"foundation.shambhavewellness.org": {
        "/blog/how-therapy-helps-build-emotional-resilience": {
            "title": "Therapy and Emotional Resilience | Shambhave Foundation"}}}


def test_ai_off_is_reported():
    audit = {"sites": [_site("wellness", [{"url": "https://shambhavewellness.org/x", "status": 200, "title": "X"}],
                             [{"rule": "title_length", "severity": "low", "url": "https://shambhavewellness.org/x",
                               "detail": "short"}])]}
    _, _, note = ov.propose_copy(CFG, audit, {}, "2026-11-23", FakeAI(None))
    assert "AI is off" in note


HTACCESS = "<IfModule mod_rewrite.c>\n    RewriteEngine On\n\n    RewriteRule ^scratch(/.*)?$ - [F,L,NC]\n</IfModule>\n"
LAYOUT = "<head>\n    @yield('headtags')\n</head>\n"
HELPERS = "<?php\n\nif (!function_exists('x')) {\n    function x() { return 1; }\n}\n"


def _fake_repo(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "resources/views/layouts").mkdir(parents=True)
    (tmp_path / "routes").mkdir()
    (tmp_path / ".htaccess").write_text(HTACCESS)
    (tmp_path / "resources/views/layouts/frontMaster.blade.php").write_text(LAYOUT)
    (tmp_path / "app/helpers.php").write_text(HELPERS)
    (tmp_path / "routes/web.php").write_text("<?php\n")
    return tmp_path


def test_sitefix_host_redirect_and_overrides_are_idempotent(tmp_path):
    repo = _fake_repo(tmp_path)
    data = {"shambhavewellness.org": {"/a": {"title": "A title | Shambhave Wellness"}}}
    fixes = apply_fixes(repo, [{"rule": "host_duplicate"}, {"rule": "exposed_file"}], tmp_path / "none", data)
    ids = [f["id"] for f in fixes]
    assert ids == ["host_redirects", "htaccess_block", "seo_overrides"]
    ht = (repo / ".htaccess").read_text()
    assert ht.index("Canonical host") < ht.index("RewriteRule ^scratch") and "well-known" in ht
    assert "seo_head(" in (repo / "resources/views/layouts/frontMaster.blade.php").read_text()
    assert json.loads((repo / "resources/seo/overrides.json").read_text()) == data
    # Same input again: nothing to do.
    assert apply_fixes(repo, [{"rule": "host_duplicate"}, {"rule": "exposed_file"}], tmp_path / "none", data) == []
    # A changed override only touches the JSON file.
    data["shambhavewellness.org"]["/a"]["description"] = "d" * 120
    again = apply_fixes(repo, [], tmp_path / "none", data)
    assert [f["files"] for f in again] == [["resources/seo/overrides.json"]]


PHP_HARNESS = r"""<?php
$GLOBALS['H'] = $argv[2]; $GLOBALS['P'] = $argv[3];
class R { function getHost() { return $GLOBALS['H']; } function path() { return $GLOBALS['P']; } }
function request() { return new R; }
function resource_path($p) { return $GLOBALS['ROOT'] . '/resources/' . $p; }
$GLOBALS['ROOT'] = $argv[4];
$src = file_get_contents($argv[1]);
eval(substr($src, strpos($src, "if (!function_exists('seo_head'))")));
echo seo_head('<title>Old</title><meta name="description" content="old" />'
    . '<link rel="canonical" href="https://www.x.org/a" /><meta property="og:title" content="old" />');
"""


@pytest.mark.skipif(not shutil.which("php"), reason="php not installed")
def test_php_seo_head_runs(tmp_path):
    repo = _fake_repo(tmp_path)
    data = {"shambhavewellness.org": {"/a": {"title": "New & $1 title | Shambhave Wellness",
                                             "canonical": "https://shambhavewellness.org/a"}}}
    apply_fixes(repo, [], tmp_path / "none", data)
    h = Path(tmp_path / "h.php")
    h.write_text(PHP_HARNESS)
    run = lambda host, path: subprocess.run(["php", str(h), str(repo / "app/helpers.php"), host, path, str(repo)],
                                            capture_output=True, text=True, check=True).stdout
    out = run("www.shambhavewellness.org", "a")
    assert "<title>New &amp; $1 title | Shambhave Wellness</title>" in out
    assert 'href="https://shambhavewellness.org/a"' in out and 'og:title" content="New &amp; $1' in out
    assert 'content="old" />' in out  # description not overridden, left alone
    assert "<title>Old</title>" in run("shambhavewellness.org", "b")


def test_pagespeed_retries_on_429(monkeypatch):
    from seo import psi

    class Resp:
        def __init__(self, code):
            self.status_code = code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"{self.status_code} error")

        def json(self):
            return {"lighthouse": {"result": {"categories": {"performance": {"score": 0.5}}, "audits": {
                "largest-contentful-paint": {"numericValue": 3000}, "cumulative-layout-shift": {"numericValue": 0.1},
                "total-blocking-time": {"numericValue": 200}}}}}

    codes = iter([429, 429, 200])
    monkeypatch.setattr(psi.requests, "get", lambda *a, **k: Resp(next(codes)))
    out = psi.run_pagespeed({"pagespeed": {"urls": ["https://x.org/"]}}, sleep=lambda s: None)
    assert out[0]["score"] == 50
