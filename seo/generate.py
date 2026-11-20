"""Deterministic generators (no AI, no cost): llms.txt and a corrected JSON-LD schema pack per site.
Output goes to data/generated/<site>/ for review, then you copy it into the website."""
import json
from urllib.parse import urlparse

from .store import write_text

GROUPS = [("/service/", "Services"), ("/course/", "Courses and training"), ("/blog/", "Articles"),
          ("/project", "Projects"), ("/volunteer", "Volunteering")]


def _clean_title(t, brand):
    for sep in (" | ", " - "):
        if sep in t and brand.lower() in t.split(sep)[-1].lower():
            t = sep.join(t.split(sep)[:-1])
    return t.strip()


def build_llms_txt(site, pages, entity):
    ok = [p for p in pages if p.get("status") == 200 and p.get("title")]
    home = next((p for p in ok if urlparse(p["url"]).path in ("", "/")), None)
    is_foundation = site["key"] == "foundation"
    about = (entity["foundation"]["description"] if is_foundation else
             f"{entity['clinic_name']} is a clinical psychology practice in {entity['city']}, {entity['region']}, India, "
             f"founded and led by {entity['founder']['name']}, {entity['founder']['job_title']}. "
             "It offers in-person sessions in Gurugram and online therapy for clients in India and abroad, "
             "with a focus on narcissistic abuse recovery, trauma, relationships and anxiety.")
    lines = [f"# {site['name']}", "", f"> {about}", ""]
    if home and home.get("description"):
        lines += [home["description"], ""]
    lines += ["## Key facts", "",
              f"- Location: {entity['street']}, {entity['city']}, {entity['region']} {entity['postcode']}, India",
              f"- Phone: {entity['phone']}", f"- Email: {entity['email']}",
              f"- Languages: {', '.join(entity['languages'])}", ""]
    used = set()
    for prefix, label in GROUPS:
        items = [p for p in ok if prefix in urlparse(p["url"]).path]
        if not items:
            continue
        lines += [f"## {label}", ""]
        for p in items:
            used.add(p["url"])
            desc = f": {p['description']}" if p.get("description") else ""
            lines.append(f"- [{_clean_title(p['title'], 'Shambhave')}]({p['url']}){desc}")
        lines.append("")
    rest = [p for p in ok if p["url"] not in used and p is not home and not any(
        x in p["url"] for x in ("privacy", "terms", "login", "payment"))]
    if rest:
        lines += ["## Other pages", ""] + [f"- [{_clean_title(p['title'], 'Shambhave')}]({p['url']})" for p in rest] + [""]
    lines += ["## Optional", "", "- Privacy policy and terms are on the site footer.",
              "- Information on this site is general and not a substitute for an individual consultation.", ""]
    return "\n".join(lines)


def build_schema(site, entity):
    """Clean JSON-LD for the site head. One graph, stable @id values, no self-served ratings."""
    base = site["base_url"].rstrip("/")
    f = entity["founder"]
    if site["key"] == "foundation":
        ngo = entity["foundation"]
        graph = [
            {"@type": "NGO", "@id": f"{base}/#organization", "name": ngo["name"], "url": ngo["url"],
             "description": ngo["description"], "email": entity["email"], "telephone": entity["phone"],
             "parentOrganization": {"@id": "https://shambhavewellness.org/#clinic"},
             "founder": {"@id": "https://shambhavewellness.org/#founder"},
             "areaServed": {"@type": "Country", "name": "India"}},
            {"@type": "WebSite", "@id": f"{base}/#website", "url": f"{base}/", "name": ngo["name"],
             "publisher": {"@id": f"{base}/#organization"}, "inLanguage": "en-IN"},
        ]
    else:
        graph = [
            {"@type": ["MedicalClinic", "LocalBusiness"], "@id": f"{base}/#clinic", "name": entity["clinic_name"],
             "url": f"{base}/", "telephone": entity["phone"], "email": entity["email"],
             "image": f"{base}/OGImage/shambhave-wellness.png", "logo": f"{base}/assets/img/logo-color.svg",
             "address": {"@type": "PostalAddress", "streetAddress": entity["street"], "addressLocality": entity["city"],
                         "addressRegion": entity["region"], "postalCode": entity["postcode"],
                         "addressCountry": entity["country"]},
             "geo": {"@type": "GeoCoordinates", "latitude": entity["geo"]["lat"], "longitude": entity["geo"]["lng"]},
             "openingHours": entity["opening_hours"], "knowsLanguage": entity["languages"],
             "founder": {"@id": f"{base}/#founder"}, "employee": {"@id": f"{base}/#founder"},
             "areaServed": [{"@type": "City", "name": "Gurugram"}, {"@type": "Country", "name": "India"}],
             "availableService": [{"@type": "MedicalTherapy", "name": n} for n in
                                  ("Psychotherapy", "Clinical hypnotherapy", "Narcissistic abuse recovery therapy",
                                   "Marriage and relationship counselling", "Trauma therapy")],
             "sameAs": entity["same_as"]},
            {"@type": "Person", "@id": f"{base}/#founder", "name": f["name"], "honorificPrefix": f["honorific"],
             "jobTitle": f["job_title"], "url": f["profile_url"], "image": f["image"],
             "worksFor": {"@id": f"{base}/#clinic"}, "knowsAbout": f["knows_about"], "sameAs": f["same_as"]},
            {"@type": "WebSite", "@id": f"{base}/#website", "url": f"{base}/", "name": entity["clinic_name"],
             "publisher": {"@id": f"{base}/#clinic"}, "inLanguage": "en-IN"},
        ]
    return {"@context": "https://schema.org", "@graph": graph}


def faq_schema(qas):
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                           for q, a in qas]}


BLADE_NOTE = """{{-- Paste in frontMaster.blade.php <head>, replacing the old JSON-LD blocks for this domain.
     Blade leaves @php blocks untouched, so "@context" is safe inside it (the old leak came from writing it
     directly in the template). --}}
@php
$schemaJson = <<<'JSON'
{json}
JSON;
@endphp
<script type="application/ld+json">{!! $schemaJson !!}</script>
"""


def write_generated(cfg, audit):
    ent = cfg["entity"]
    written = []
    for s_cfg, s_audit in zip(cfg["sites"], audit["sites"]):
        key = s_cfg["key"]
        llms = build_llms_txt(s_cfg, s_audit["pages"], ent)
        schema = json.dumps(build_schema(s_cfg, ent), indent=2, ensure_ascii=False)
        written.append(write_text(f"generated/{key}/llms.txt", llms))
        written.append(write_text(f"generated/{key}/schema.json", schema))
        written.append(write_text(f"generated/{key}/schema.blade.php", BLADE_NOTE.replace("{json}", schema)))
    return written
