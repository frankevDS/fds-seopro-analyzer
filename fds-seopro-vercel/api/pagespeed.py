"""
Vercel Serverless Function: /api/pagespeed
Proxies Google PageSpeed Insights API (bypasses browser CORS).

Google's PUBLIC, keyless PageSpeed quota is shared across everyone in the
world hitting it with no API key — that shared pool is what causes
"rate limited" errors, and it is a real limit Google enforces, not a bug
in this code. Adding your own free Google API key (from Google Cloud
Console) gives this specific app its OWN private quota of 25,000
requests/day, which makes rate-limit errors extremely rare.

To add one: console.cloud.google.com -> create a project -> enable
"PageSpeed Insights API" -> Credentials -> Create API Key -> paste it
into Vercel's environment variables as PAGESPEED_API_KEY.
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
import json
import os
import time
import urllib.request
import urllib.error


def fetch_with_retry(ps_url, retries=2, backoff=2.0):
    last_error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                ps_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; FDS-SeoPro/1.0; +https://vercel.app)"
                },
            )
            with urllib.request.urlopen(req, timeout=25) as resp:
                return json.loads(resp.read().decode()), None
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code == 429 and attempt < retries:
                time.sleep(backoff * (attempt + 1))
                continue
            return None, e
        except Exception as e:
            last_error = e
            return None, e
    return None, last_error


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        url = params.get("url", [""])[0]
        strategy = params.get("strategy", ["mobile"])[0]

        if not url:
            self._send_json(400, {"error": "No URL provided"})
            return

        api_key = os.environ.get("PAGESPEED_API_KEY", "")

        ps_url = (
            "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
            f"?url={quote(url, safe='')}&strategy={strategy}"
            "&category=performance&category=seo&category=accessibility&category=best-practices"
        )
        if api_key:
            ps_url += f"&key={quote(api_key)}"

        data, error = fetch_with_retry(ps_url)

        if data is not None:
            self._send_json(200, data)
            return

        if isinstance(error, urllib.error.HTTPError) and error.code == 429:
            msg = (
                "Google's free PageSpeed quota is temporarily exhausted. "
                if not api_key else
                "Your PageSpeed API key's quota was hit — this is rare with a "
                "personal key. Try again shortly."
            )
            self._send_json(429, {
                "error": "rate_limited",
                "message": msg,
                "hasOwnKey": bool(api_key),
            })
            return

        code = error.code if isinstance(error, urllib.error.HTTPError) else 500
        self._send_json(code, {"error": f"PageSpeed error: {str(error)}"})

    def _send_json(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
