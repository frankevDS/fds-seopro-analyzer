"""
Vercel Serverless Function: /api/pagespeed
Proxies Google PageSpeed Insights API (bypasses browser CORS)
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
import json
import urllib.request
import urllib.error


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        url = params.get("url", [""])[0]
        strategy = params.get("strategy", ["mobile"])[0]

        if not url:
            self._send_json(400, {"error": "No URL provided"})
            return

        ps_url = (
            "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
            f"?url={quote(url, safe='')}&strategy={strategy}"
            "&category=performance&category=seo&category=accessibility&category=best-practices"
        )

        try:
            req = urllib.request.Request(ps_url, headers={"User-Agent": "FDS-SeoPro/1.0"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read().decode())
            self._send_json(200, data)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                self._send_json(429, {"error": "rate_limited"})
            else:
                self._send_json(e.code, {"error": f"PageSpeed error {e.code}"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _send_json(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
