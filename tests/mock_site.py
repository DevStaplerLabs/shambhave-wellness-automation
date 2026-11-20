"""Tiny local web server that imitates the real site's known problems, for offline testing."""
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
B = f"http://127.0.0.1:{PORT}"

HOME = f"""<html lang="en"><head><title>Best Clinical Psychologist in Gurgaon | Online Therapy India</title>
<meta name="description" content="Expert clinical psychologist in Gurgaon offering online counselling, therapy, hypnotherapy, trauma recovery, and mental health services.">
<link rel="canonical" href="{B}/"><meta property="og:image" content="x.png">
<script type="application/ld+json">{{"<?php $__contextArgs = []; ?>": "https://schema.org", "@type": "MedicalClinic"}}</script>
<script type="application/ld+json">{{"@context": "https://schema.org", "@type": "WebSite"}}</script>
</head><body><img src="p.gif" alt="Shambhave Wellness, Please wait..."><h1>Dr. Amita Puri</h1>
<img src="a.png"><p>Welcome to the clinic.</p></body></html>"""

SERVICE = f"""<html lang="en"><head><title>Narcissistic Abuse Recovery Therapy</title>
<link rel="canonical" href="{B}/service/narcissistic-abuse-recovery-therapy"></head>
<body><h1>Narcissistic Abuse Recovery Therapy</h1><p>Short page about recovery support.</p></body></html>"""

PAGES = {
    "/": HOME,
    "/service/narcissistic-abuse-recovery-therapy": SERVICE,
    "/narcissistic-abuse-recovery-therapy": SERVICE,   # duplicate URL, should 301
    "/about-us": SERVICE.replace("Narcissistic Abuse Recovery Therapy", "About Us"),
}
SITEMAP = ("<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
           + "".join(f"<url><loc>{B}{p}</loc></url>" for p in ("/", "/service/narcissistic-abuse-recovery-therapy",
                                                               "/about-us", "/terms-and-conditions"))
           + "</urlset>")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="text/html"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body if isinstance(body, bytes) else body.encode())

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if "ClaudeBot" in self.headers.get("User-Agent", ""):
            return self._send(403, "Forbidden")
        p = self.path.split("?")[0]
        if p == "/sitemap.xml":
            return self._send(200, SITEMAP, "application/xml")
        if p == "/robots.txt":
            return self._send(200, "User-agent: *\nAllow: /\n\nUser-agent: GPTBot\nDisallow: /\n", "text/plain")
        if p == "/composer.lock":
            return self._send(200, "{}", "application/json")
        if p in PAGES:
            return self._send(200, PAGES[p])
        return self._send(404, "<html><title>404</title></html>")


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
