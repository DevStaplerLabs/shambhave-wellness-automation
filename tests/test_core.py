"""Fast unit tests. Run: python -m pytest -q"""
import json

from seo.crawl import diff, parse_jsonld, robots_blocks, score
from seo.generate import build_llms_txt, build_schema
from seo.gsc import expected_ctr, gsc_issues
from bs4 import BeautifulSoup
import yaml

CFG = yaml.safe_load(open("config.yaml"))


def test_robots_blocks():
    txt = "User-agent: *\nAllow: /\n\nUser-agent: GPTBot\nDisallow: /\n"
    assert robots_blocks(txt, "GPTBot")
    assert not robots_blocks(txt, "ClaudeBot")
    assert robots_blocks("User-agent: *\nDisallow: /\n", "ClaudeBot")
    assert not robots_blocks("User-agent: *\nDisallow: /admin/\n", "ClaudeBot")


def test_jsonld_php_leak_and_context():
    html = ('<script type="application/ld+json">{"<?php $x ?>": "https://schema.org", "@type": "MedicalClinic"}</script>'
            '<script type="application/ld+json">{"@context": "https://schema.org", "@graph": [{"@type": "Person"}]}</script>'
            '<script type="application/ld+json">{bad json</script>')
    b = parse_jsonld(BeautifulSoup(html, "lxml"))
    assert b[0]["php_leak"] and b[0]["valid_json"] and not b[0]["has_context"]
    assert b[1]["has_context"] and b[1]["types"] == ["Person"]
    assert not b[2]["valid_json"]


def test_score_and_diff():
    mk = lambda rule, sev, url: {"id": f"w|{rule}|{url}", "site": "w", "rule": rule, "severity": sev, "url": url, "detail": ""}
    a = {"page_count": 10, "issues": [mk("schema_php_leak_0", "critical", "/"), mk("title_length", "low", "/a")]}
    b = {"page_count": 10, "issues": [mk("title_length", "low", "/a")]}
    assert score(b) > score(a)
    assert score({"page_count": 5, "issues": []}) == 100
    d = diff({"sites": [a]}, {"sites": [b]})
    assert len(d["resolved"]) == 1 and not d["new"]


def test_schema_pack_is_valid_and_clean():
    for site in CFG["sites"]:
        s = build_schema(site, CFG["entity"])
        txt = json.dumps(s)
        assert s["@context"] == "https://schema.org"
        assert "aggregateRating" not in txt and "Physician" not in txt and "<?php" not in txt


def test_llms_txt_lists_services():
    pages = [{"url": "https://shambhavewellness.org/", "status": 200, "title": "Home", "description": "d"},
             {"url": "https://shambhavewellness.org/service/x", "status": 200, "title": "X Therapy | Shambhave Wellness",
              "description": "About X"}]
    out = build_llms_txt(CFG["sites"][0], pages, CFG["entity"])
    assert out.startswith("# Shambhave Wellness") and "[X Therapy](https://shambhavewellness.org/service/x): About X" in out


def test_gsc_issue_conversion():
    assert expected_ctr(1) > expected_ctr(9)
    g = {"sites": {"wellness": {"low_ctr_pages": [{"page": "/p", "position": 3.2, "impressions": 400, "ctr_pct": 1.0, "expected_pct": 10}],
                                "striking_distance": [{"query": "q one two", "page": "/p", "position": 11.0, "impressions": 90, "clicks": 1}]}}}
    rules = sorted(i["rule"] for i in gsc_issues(g))
    assert rules == ["low_ctr", "striking_distance"]
