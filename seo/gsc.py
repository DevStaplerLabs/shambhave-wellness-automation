"""Google Search Console (free, read-only). Skipped cleanly if GSC_SERVICE_ACCOUNT_JSON is not set.

Setup: create a Google Cloud service account, download its JSON key, add the account's email in
Search Console > Settings > Users and permissions with "Restricted" permission, and store the whole
JSON as the GSC_SERVICE_ACCOUNT_JSON secret.
"""
import json
import os
from datetime import date, timedelta
from urllib.parse import quote

import requests

SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
API = "https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"


def _token():
    raw = os.environ.get("GSC_SERVICE_ACCOUNT_JSON")
    if not raw:
        return None
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    creds = service_account.Credentials.from_service_account_info(json.loads(raw), scopes=[SCOPE])
    creds.refresh(Request())
    return creds.token


def _query(token, prop, start, end, dims, limit=1000):
    r = requests.post(API.format(site=quote(prop, safe="")), timeout=60,
                      headers={"Authorization": f"Bearer {token}"},
                      json={"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": dims,
                            "rowLimit": limit, "dataState": "final"})
    r.raise_for_status()
    return r.json().get("rows", [])


def _totals(rows):
    clicks = sum(r["clicks"] for r in rows)
    imp = sum(r["impressions"] for r in rows)
    pos = sum(r["position"] * r["impressions"] for r in rows) / imp if imp else None
    return {"clicks": clicks, "impressions": imp, "ctr_pct": round(100 * clicks / imp, 2) if imp else 0,
            "avg_position": round(pos, 1) if pos else None}


def expected_ctr(position):
    """Rough organic CTR by position, used only to spot snippets that under-perform."""
    table = {1: 0.27, 2: 0.15, 3: 0.10, 4: 0.07, 5: 0.05, 6: 0.04, 7: 0.03, 8: 0.025, 9: 0.02, 10: 0.018}
    return table.get(round(position), 0.01)


def run_gsc(cfg):
    try:
        token = _token()
    except Exception as e:
        return {"error": f"Search Console auth failed: {type(e).__name__}"}
    if not token:
        return {"skipped": "GSC_SERVICE_ACCOUNT_JSON not set"}
    end = date.today() - timedelta(days=3)          # final data lags ~3 days
    start, p_end = end - timedelta(days=27), end - timedelta(days=28)
    p_start = p_end - timedelta(days=27)
    out = {"period": f"{start} to {end}", "sites": {}}
    for s in cfg["sites"]:
        prop = s.get("gsc_property")
        if not prop:
            continue
        try:
            pages = _query(token, prop, start, end, ["page"])
            prev = _query(token, prop, p_start, p_end, ["page"])
            qp = _query(token, prop, start, end, ["query", "page"], 2500)
        except Exception as e:
            out["sites"][s["key"]] = {"error": f"{type(e).__name__}: {str(e)[:150]}"}
            continue
        striking = sorted(
            [{"query": r["keys"][0], "page": r["keys"][1], "position": round(r["position"], 1),
              "impressions": r["impressions"], "clicks": r["clicks"]}
             for r in qp if 4.5 <= r["position"] <= 20 and r["impressions"] >= 15],
            key=lambda x: -x["impressions"])[:25]
        low_ctr = sorted(
            [{"page": r["keys"][0], "position": round(r["position"], 1), "impressions": r["impressions"],
              "ctr_pct": round(100 * r["ctr"], 2), "expected_pct": round(100 * expected_ctr(r["position"]), 1)}
             for r in pages if r["position"] <= 10 and r["impressions"] >= 50
             and r["ctr"] < 0.5 * expected_ctr(r["position"])],
            key=lambda x: -x["impressions"])[:15]
        qs = {}
        for r in qp:
            q = r["keys"][0]
            qs.setdefault(q, {"query": q, "clicks": 0, "impressions": 0})
            qs[q]["clicks"] += r["clicks"]
            qs[q]["impressions"] += r["impressions"]
        top_queries = sorted(qs.values(), key=lambda x: (-x["clicks"], -x["impressions"]))[:15]
        out["sites"][s["key"]] = {"now": _totals(pages), "before": _totals(prev), "striking_distance": striking,
                                  "low_ctr_pages": low_ctr, "top_queries": top_queries}
    return out


def gsc_issues(gsc):
    """Turn Search Console findings into issues the daily fixer can act on."""
    from .crawl import issue
    out = []
    for key, d in (gsc or {}).get("sites", {}).items():
        for p in d.get("low_ctr_pages", []):
            out.append(issue(key, "low_ctr", "high", p["page"],
                             f"Position {p['position']} with {p['impressions']} impressions but CTR {p['ctr_pct']}% "
                             f"(expected about {p['expected_pct']}%). Rewrite title and description."))
        by_page = {}
        for s in d.get("striking_distance", []):
            by_page.setdefault(s["page"], []).append(f"'{s['query']}' (pos {s['position']}, {s['impressions']} impr.)")
        for page, qs in by_page.items():
            out.append(issue(key, "striking_distance", "high", page,
                             "Near page one for: " + "; ".join(qs[:5]) + ". Work these phrases into the title, H2s and FAQ."))
    return out
