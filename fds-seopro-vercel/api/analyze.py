"""
Vercel Serverless Function: /api/analyze
Calls Groq's API (OpenAI-compatible) to run the full SEO analysis.
Groq API key comes from the request header X-API-Key, OR from the
GROQ_API_KEY environment variable set in Vercel project settings.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import re
import urllib.request
import urllib.error


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Llama 3.3 70B is Groq's strongest free-tier model for this kind of
# structured reasoning task. Swap to "llama-3.1-8b-instant" for speed
# over depth if you hit rate limits.
MODEL = "llama-3.3-70b-versatile"


def build_prompt(url, ps_desktop, ps_mobile):
    has_ps = ps_desktop is not None

    def sc(d, k):
        try:
            return round((d["lighthouseResult"]["categories"][k]["score"] or 0) * 100)
        except Exception:
            return 0

    def gav(d, k):
        try:
            return d["lighthouseResult"]["audits"][k]["displayValue"] or "N/A"
        except Exception:
            return "N/A"

    def gs(d, k):
        try:
            return round((d["lighthouseResult"]["audits"][k]["score"] or 0) * 100)
        except Exception:
            return 0

    if has_ps:
        ctx = f"""REAL GOOGLE PAGESPEED DATA:
Desktop: Performance={sc(ps_desktop,'performance')}/100 SEO={sc(ps_desktop,'seo')}/100 Accessibility={sc(ps_desktop,'accessibility')}/100 BestPractices={sc(ps_desktop,'best-practices')}/100
Mobile: Performance={sc(ps_mobile,'performance')}/100 SEO={sc(ps_mobile,'seo')}/100
LCP={gav(ps_desktop,'largest-contentful-paint')} CLS={gav(ps_desktop,'cumulative-layout-shift')} TBT={gav(ps_desktop,'total-blocking-time')} FCP={gav(ps_desktop,'first-contentful-paint')} TTFB={gav(ps_desktop,'server-response-time')} SpeedIndex={gav(ps_desktop,'speed-index')}
Title="{gav(ps_desktop,'document-title')}" Meta="{gav(ps_desktop,'meta-description')}"
Canonical={ps_desktop.get('lighthouseResult',{}).get('audits',{}).get('canonical',{}).get('displayValue','not set')}
Robots={'valid' if gs(ps_desktop,'robots-txt')==100 else 'missing'} Hreflang={'valid' if gs(ps_desktop,'hreflang')==100 else 'missing'}
ImageAlt={'all ok' if gs(ps_desktop,'image-alt')==100 else 'missing'} StructuredData={'present' if gs(ps_desktop,'structured-data')==100 else 'missing'}
Viewport={'yes' if gs(ps_mobile,'viewport')==100 else 'no'} HTTPS={'yes' if url.startswith('https') else 'no'}"""
    else:
        ctx = (
            "NOTE: PageSpeed data unavailable. Estimate all values using your "
            "general knowledge of this domain, its industry, and typical SEO "
            f"patterns for sites like it. HTTPS={'yes' if url.startswith('https') else 'no'}"
        )

    schema = (
        '{"summary":"3-4 sentence expert verdict","scores":{"onPage":0,"technical":0,'
        '"content":0,"ux":0,"mobile":0,"security":0},"title":{"score":0,"value":"likely title",'
        '"length":"~N chars","kwInTitle":true,"rating":"Good/Needs Work/Poor/Critical",'
        '"comment":"expert analysis","improved":"exact improved title"},"meta":{"score":0,'
        '"value":"likely meta","length":"~N chars","kwInMeta":true,'
        '"rating":"Good/Needs Work/Poor/Critical","comment":"expert analysis",'
        '"improved":"exact improved meta"},"headings":{"score":0,"h1Count":"N","h1Value":"likely H1",'
        '"structure":"description","issues":["i1","i2"],"fixes":["f1","f2"]},'
        '"content":{"score":0,"words":0,"readability":0,"eeat":0,"depth":0,"comment":"analysis",'
        '"gaps":["g1","g2","g3"]},"keywords":[{"kw":"phrase","volume":"High/Medium/Low",'
        '"difficulty":"High/Medium/Low","relevance":0,"inTitle":true,"inMeta":true,"inH1":true,'
        '"density":"1.2%","verdict":"Keep/Improve/Replace","reason":"why"}],'
        '"technical":[{"issue":"problem","severity":"High/Medium/Low","impact":"ranking effect",'
        '"fix":"step-by-step"}],"cwv":{"lcp":"2.5s","cls":"0.1","fcp":"1.8s","ttfb":"0.8s",'
        '"perfScore":0,"mobileScore":0},"backlinks":{"estimated":0,"da":0,"pa":0,"dofollow":"~X%",'
        '"nofollow":"~X%","toxic":"Low/Medium/High","topRefs":[{"domain":"x.com","da":0,'
        '"type":"Dofollow/Nofollow","quality":"High/Medium/Low"}],"analysis":"profile analysis",'
        '"strategy":"link building plan"},"extLinks":[{"domain":"x.com",'
        '"type":"Industry/News/Educational/Government/Directory","da":0,"reason":"why",'
        '"how":"how to get it"}],"competitor":{"rivals":["a.com","b.com","c.com"],'
        '"barriers":["b1","b2","b3"],"quickWins":["w1","w2","w3"],"strategy":"4-6 sentence strategy",'
        '"angles":["a1","a2","a3"]},"rankingIssues":[{"reason":"why not ranking",'
        '"impact":"High/Medium/Low","signal":"google signal","fix":"actionable fix"}],'
        '"fixes":[{"title":"fix name","priority":"High/Medium/Low","effort":"Easy/Medium/Hard",'
        '"time":"days/weeks/months","impact":"improvement","steps":["s1","s2","s3","s4"]}]}'
    )

    return f"""You are a world-class SEO expert with 20 years of experience auditing websites. Analyse this site with precision and brutal honesty.

SITE: {url}
{ctx}

Respond ONLY with a single valid JSON object matching this exact schema (no markdown formatting, no backticks, no explanation text before or after):
{schema}"""


def call_groq(api_key, prompt, attempt=1):
    """Call Groq with browser-like headers to avoid Cloudflare bot detection (error 1010)."""
    groq_body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 4000,
        "response_format": {"type": "json_object"},
    }).encode()

    req = urllib.request.Request(
        GROQ_URL,
        data=groq_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            # Cloudflare (which fronts Groq's API) sometimes blocks requests
            # with no User-Agent or generic urllib defaults — error code 1010.
            # A normal browser-style UA avoids that classification.
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=55) as resp:
        return json.loads(resp.read().decode())


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            payload = json.loads(body)
        except Exception:
            self._send_json(400, {"error": "Invalid request body"})
            return

        url = payload.get("url", "")
        ps_desktop = payload.get("psDesktop")
        ps_mobile = payload.get("psMobile")

        if not url:
            self._send_json(400, {"error": "No URL provided"})
            return

        api_key = self.headers.get("X-API-Key") or os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            self._send_json(401, {"error": "No Groq API key provided. Add it in Settings or set GROQ_API_KEY in Vercel."})
            return

        prompt = build_prompt(url, ps_desktop, ps_mobile)

        try:
            result = None
            last_err = None
            # Retry once on transient Cloudflare/network blocks
            for attempt in (1, 2):
                try:
                    result = call_groq(api_key, prompt, attempt)
                    break
                except urllib.error.HTTPError as e:
                    last_err = e
                    if e.code in (403, 429, 503) and attempt == 1:
                        continue
                    raise
            if result is None and last_err:
                raise last_err

            text = result["choices"][0]["message"]["content"]
            match = re.search(r"\{[\s\S]*\}", text)
            if not match:
                self._send_json(500, {"error": "No JSON in AI response", "raw": text[:400]})
                return
            ai_data = json.loads(match.group(0))
            self._send_json(200, {
                "success": True,
                "data": ai_data,
                "mode": "full" if ps_desktop is not None else "ai-only",
            })
        except urllib.error.HTTPError as e:
            err_body = e.read().decode() if e.fp else str(e)
            hint = ""
            if e.code == 403:
                hint = (
                    " — this usually means the API key is invalid/expired, or "
                    "Groq's account region/billing check rejected the request. "
                    "Double check the key at console.groq.com/keys."
                )
            self._send_json(e.code, {"error": f"Groq API error {e.code}: {err_body[:300]}{hint}"})
        except json.JSONDecodeError as e:
            self._send_json(500, {"error": f"JSON parse error: {str(e)}"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.end_headers()

    def _send_json(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
