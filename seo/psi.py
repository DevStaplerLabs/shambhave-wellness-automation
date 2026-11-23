"""Google PageSpeed Insights (free). Mobile scores and Core Web Vitals for a few key pages.

Without PSI_API_KEY the API shares a small anonymous quota and often answers 429, so requests are spaced
out and retried with a back-off. A free key (PSI_API_KEY secret) removes the problem."""
import os
import time

import requests

API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
WAITS = (20, 60, 120)  # seconds before each retry on 429 / 5xx


def _fetch(params, sleep=time.sleep):
    last = None
    for wait in (0,) + WAITS:
        if wait:
            sleep(wait)
        r = requests.get(API, params=params, timeout=120)
        if r.status_code != 429 and r.status_code < 500:
            r.raise_for_status()
            return r.json()
        last = r
    last.raise_for_status()


def run_pagespeed(cfg, sleep=time.sleep):
    out = []
    key = os.environ.get("PSI_API_KEY")
    for n, url in enumerate(cfg["pagespeed"]["urls"]):
        if n:
            sleep(5 if key else 15)
        params = {"url": url, "strategy": "mobile", "category": "performance"}
        if key:
            params["key"] = key
        try:
            j = _fetch(params, sleep)
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
            msg = f"{type(e).__name__}: {str(e)[:120]}"
            if "429" in msg and not key:
                msg += " (add the free PSI_API_KEY secret to stop this)"
            out.append({"url": url, "error": msg})
    return out
