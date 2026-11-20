"""Google PageSpeed Insights (free). Mobile scores and Core Web Vitals for a few key pages."""
import os

import requests

API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def run_pagespeed(cfg):
    out = []
    key = os.environ.get("PSI_API_KEY")
    for url in cfg["pagespeed"]["urls"]:
        params = {"url": url, "strategy": "mobile", "category": "performance"}
        if key:
            params["key"] = key
        try:
            r = requests.get(API, params=params, timeout=120)
            r.raise_for_status()
            j = r.json()
            lh = j["lighthouse"]["result"]
            audits = lh["audits"]
            field = j.get("loadingExperience", {}).get("metrics", {})
            out.append({
                "url": url,
                "score": round((lh["categories"]["performance"]["score"] or 0) * 100),
                "lcp_s": round(audits["largest-contentful-paint"]["numericValue"] / 1000, 1),
                "cls": round(audits["cumulative-layout-shift"]["numericValue"], 3),
                "tbt_ms": round(audits["total-blocking-time"]["numericValue"]),
                "page_mb": round(audits.get("total-byte-weight", {}).get("numericValue", 0) / 1_048_576, 1),
                "field_lcp": field.get("LARGEST_CONTENTFUL_PAINT_MS", {}).get("category"),
                "field_inp": field.get("INTERACTION_TO_NEXT_PAINT", {}).get("category"),
            })
        except Exception as e:
            out.append({"url": url, "error": f"{type(e).__name__}: {str(e)[:120]}"})
    return out
