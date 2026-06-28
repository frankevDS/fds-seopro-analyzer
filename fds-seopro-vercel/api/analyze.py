"""
Vercel Serverless Function: /api/analyze

This version actually fetches the live page HTML and parses it for real
title, meta description, headings, and keyword frequency BEFORE calling
Groq — so the analysis reflects what's truly on the page, not a guess
based on the domain name alone. Groq is then used only for the parts
that genuinely require judgment: scoring, strategy, competitor research,
and writing recommendations.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import re
import gzip
import urllib.request
import urllib.error
from collections import Counter
from html.parser import HTMLParser


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

STOPWORDS = set(
    "the a an and or but if is are was were be been being to of in on for with "
    "as by at from this that these those it its it's you your we our they their "
    "he she his her i my me us not no yes do does did can will would should "
    "have has had get gets got go goes going up out so than then there here "
    "what when where which who whom why how all any both each few more most "
    "other some such only own same too very just also into about over under "
    "again further once".split()
)


# ── Real page fetch + parse ───────────────────────────────────────────────────

class PageParser(HTMLParser):
    """Lightweight HTML parser — no external deps, works on Vercel's stdlib-only runtime."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta_description = ""
        self.canonical = ""
        self.headings = {"h1": [], "h2": [], "h3": []}
        self.body_text_parts = []
        self.image_count = 0
        self.images_missing_alt = 0
        self.has_viewport = False
        self.has_structured_data = False
        self._cur_tag = None
        self._capture_title = False
        self._capture_heading = None
        self._in_script_or_style = False

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "title":
            self._capture_title = True
        elif tag == "meta":
            name = (attrs_d.get("name") or "").lower()
            prop = (attrs_d.get("property") or "").lower()
            if name == "description":
                self.meta_description = attrs_d.get("content", "")
            if name == "viewport":
                self.has_viewport = True
            if prop == "og:description" and not self.meta_description:
                self.meta_description = attrs_d.get("content", "")
        elif tag == "link":
            if (attrs_d.get("rel") or "").lower() == "canonical":
                self.canonical = attrs_d.get("href", "")
        elif tag in ("h1", "h2", "h3"):
            self._capture_heading = tag
        elif tag == "img":
            self.image_count += 1
            if not attrs_d.get("alt"):
                self.images_missing_alt += 1
        elif tag == "script":
            self._in_script_or_style = True
            if (attrs_d.get("type") or "").lower() == "application/ld+json":
                self.has_structured_data = True
        elif tag == "style":
            self._in_script_or_style = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._capture_title = False
        elif tag in ("h1", "h2", "h3"):
            self._capture_heading = None
        elif tag in ("script", "style"):
            self._in_script_or_style = False

    def handle_data(self, data):
        if self._in_script_or_style:
            return
        text = data.strip()
        if not text:
            return
        if self._capture_title:
            self.title += text
        if self._capture_heading:
            self.headings[self._capture_heading].append(text)
        self.body_text_parts.append(text)


def fetch_html(url, timeout=12):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "gzip",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.info().get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        charset = "utf-8"
        ctype = resp.info().get("Content-Type", "")
        m = re.search(r"charset=([\w-]+)", ctype)
        if m:
            charset = m.group(1)
        try:
            return raw.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            return raw.decode("utf-8", errors="replace")


def extract_keywords(body_text, title, meta, top_n=8):
    """Real frequency-based keyword extraction from actual page text."""
    full_text = f"{title} {title} {meta} {meta} {' '.join(body_text)}".lower()
    words = re.findall(r"[a-z][a-z0-9'-]{2,}", full_text)
    words = [w for w in words if w not in STOPWORDS and len(w) > 2]

    unigram_counts = Counter(words)

    bigrams = [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]
    bigram_counts = Counter(bigrams)

    total_words = max(len(words), 1)
    candidates = []

    for phrase, count in bigram_counts.most_common(15):
        if count >= 2:
            candidates.append((phrase, count, count / total_words * 100))

    for word, count in unigram_counts.most_common(20):
        if count >= 3 and not any(word in c[0] for c in candidates):
            candidates.append((word, count, count / total_words * 100))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[:top_n], total_words


def analyze_page(url):
    """Fetch the real page and extract real, verifiable SEO facts."""
    try:
        html = fetch_html(url)
    except Exception as e:
        return {"error": str(e), "fetched": False}

    parser = PageParser()
    try:
        parser.feed(html)
    except Exception:
        pass

    title = parser.title.strip()
    meta = parser.meta_description.strip()
    h1_list = parser.headings["h1"]
    h2_list = parser.headings["h2"]
    h3_list = parser.headings["h3"]
    body_text = parser.body_text_parts

    word_count = sum(len(t.split()) for t in body_text)
    keywords, total_words = extract_keywords(body_text, title, meta)

    title_lower = title.lower()
    meta_lower = meta.lower()
    h1_text_lower = " ".join(h1_list).lower()

    keyword_rows = []
    for phrase, count, density in keywords:
        keyword_rows.append({
            "kw": phrase,
            "count": count,
            "density": round(density, 2),
            "inTitle": phrase in title_lower,
            "inMeta": phrase in meta_lower,
            "inH1": phrase in h1_text_lower,
        })

    return {
        "fetched": True,
        "title": title,
        "title_length": len(title),
        "meta": meta,
        "meta_length": len(meta),
        "canonical": parser.canonical,
        "h1_count": len(h1_list),
        "h1_list": h1_list[:3],
        "h2_count": len(h2_list),
        "h2_list": h2_list[:6],
        "h3_count": len(h3_list),
        "word_count": word_count,
        "image_count": parser.image_count,
        "images_missing_alt": parser.images_missing_alt,
        "has_viewport": parser.has_viewport,
        "has_structured_data": parser.has_structured_data,
        "https": url.startswith("https"),
        "keyword_rows": keyword_rows,
    }


# ── Prompt construction using REAL extracted data ─────────────────────────────

def build_prompt(url, page_data, ps_desktop, ps_mobile):
    has_ps = ps_desktop is not None
    has_page = page_data.get("fetched", False)

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

    ps_ctx = ""
    if has_ps:
        ps_ctx = f"""
GOOGLE PAGESPEED (real, live measurement):
Desktop: Performance={sc(ps_desktop,'performance')}/100 SEO={sc(ps_desktop,'seo')}/100 Accessibility={sc(ps_desktop,'accessibility')}/100 BestPractices={sc(ps_desktop,'best-practices')}/100
Mobile: Performance={sc(ps_mobile,'performance')}/100 SEO={sc(ps_mobile,'seo')}/100
LCP={gav(ps_desktop,'largest-contentful-paint')} CLS={gav(ps_desktop,'cumulative-layout-shift')} TBT={gav(ps_desktop,'total-blocking-time')} FCP={gav(ps_desktop,'first-contentful-paint')} TTFB={gav(ps_desktop,'server-response-time')} SpeedIndex={gav(ps_desktop,'speed-index')}"""
    else:
        ps_ctx = "\nGOOGLE PAGESPEED: unavailable for this run (rate limited) — do not invent specific millisecond/score figures for Core Web Vitals; describe performance qualitatively instead, or note it as not measured."

    if has_page:
        kw_lines = "\n".join(
            f'  - "{k["kw"]}" — appears {k["count"]}x, density {k["density"]}%, '
            f'in title: {k["inTitle"]}, in meta: {k["inMeta"]}, in H1: {k["inH1"]}'
            for k in page_data["keyword_rows"]
        ) or "  (no repeated phrases detected — page may be very short or JS-rendered)"

        page_ctx = f"""
REAL PAGE CONTENT (actually fetched and parsed from {url} — this is ground truth, not a guess):
Title tag (exact): "{page_data['title']}" ({page_data['title_length']} characters)
Meta description (exact): "{page_data['meta']}" ({page_data['meta_length']} characters)
Canonical tag: {page_data['canonical'] or 'not set'}
H1 count: {page_data['h1_count']} — text: {page_data['h1_list']}
H2 count: {page_data['h2_count']} — examples: {page_data['h2_list']}
H3 count: {page_data['h3_count']}
Visible body word count: {page_data['word_count']}
Images: {page_data['image_count']} total, {page_data['images_missing_alt']} missing alt text
Has viewport meta tag: {page_data['has_viewport']}
Has structured data (JSON-LD): {page_data['has_structured_data']}
HTTPS: {page_data['https']}

REAL KEYWORD FREQUENCY ANALYSIS (extracted by counting actual words on the page — use THESE as the keyword list, do not invent different ones):
{kw_lines}

IMPORTANT: The title, meta, headings, and keywords above are extracted directly from the live page. Base your title/meta/heading scores and comments on these EXACT values. For the keywords array in your JSON response, use the real keywords listed above as your primary candidates — you may suggest 2-3 ADDITIONAL keyword opportunities the page should target but currently doesn't, clearly distinguishing them as "currently targets" vs "should add", but do not replace the real detected keywords with unrelated guesses."""
    else:
        page_ctx = f"""
NOTE: Could not fetch the live page content directly (error: {page_data.get('error', 'unknown')}). This may be because the site blocks automated requests, requires JavaScript rendering, or is temporarily unreachable. Be explicit in your summary that title/meta/keyword data below are ESTIMATES based on the URL and domain only, not confirmed page content. Do not state specific keyword densities or exact title/meta text as fact."""

    schema = (
        '{"summary":"3-4 sentence expert verdict, explicitly state whether this is based on real fetched content or estimates","scores":{"onPage":0,"technical":0,'
        '"content":0,"ux":0,"mobile":0,"security":0},"title":{"score":0,"value":"the exact real title if fetched, else best estimate",'
        '"length":"~N chars","kwInTitle":true,"rating":"Good/Needs Work/Poor/Critical",'
        '"comment":"expert analysis","improved":"exact improved title"},"meta":{"score":0,'
        '"value":"the exact real meta if fetched, else best estimate","length":"~N chars","kwInMeta":true,'
        '"rating":"Good/Needs Work/Poor/Critical","comment":"expert analysis",'
        '"improved":"exact improved meta"},"headings":{"score":0,"h1Count":"N","h1Value":"the real H1 text if fetched",'
        '"structure":"description","issues":["i1","i2"],"fixes":["f1","f2"]},'
        '"content":{"score":0,"words":0,"readability":0,"eeat":0,"depth":0,"comment":"analysis",'
        '"gaps":["g1","g2","g3"]},"keywords":[{"kw":"phrase from real data above","volume":"High/Medium/Low",'
        '"difficulty":"High/Medium/Low","relevance":0,"inTitle":true,"inMeta":true,"inH1":true,'
        '"density":"1.2%","verdict":"Keep/Improve/Replace","status":"current","reason":"why"}],'
        '"suggestedKeywords":[{"kw":"new keyword opportunity not currently targeted","volume":"High/Medium/Low","difficulty":"High/Medium/Low","reason":"why this would help the site rank higher"}],'
        '"technical":[{"issue":"problem","severity":"High/Medium/Low","impact":"ranking effect",'
        '"fix":"step-by-step"}],"cwv":{"lcp":"value or Not measured","cls":"value or Not measured","fcp":"value or Not measured","ttfb":"value or Not measured",'
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

    return f"""You are a world-class SEO expert with 20 years of experience auditing websites. Analyse this site with precision and brutal honesty, grounded strictly in the real data provided below — never invent facts that contradict it.

SITE: {url}
{page_ctx}
{ps_ctx}

Respond ONLY with a single valid JSON object matching this exact schema (no markdown formatting, no backticks, no explanation text before or after):
{schema}"""


def call_groq(api_key, prompt):
    groq_body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4000,
        "response_format": {"type": "json_object"},
    }).encode()

    req = urllib.request.Request(
        GROQ_URL,
        data=groq_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": BROWSER_UA,
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

        # Step 1: actually fetch and parse the real page
        page_data = analyze_page(url)

        # Step 2: build prompt using REAL extracted facts + PageSpeed if available
        prompt = build_prompt(url, page_data, ps_desktop, ps_mobile)

        try:
            result = None
            last_err = None
            for attempt in (1, 2):
                try:
                    result = call_groq(api_key, prompt)
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
                "pageFetched": page_data.get("fetched", False),
            })
        except urllib.error.HTTPError as e:
            err_body = e.read().decode() if e.fp else str(e)
            hint = ""
            if e.code == 403:
                hint = " — check that your Groq API key is valid at console.groq.com/keys"
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
