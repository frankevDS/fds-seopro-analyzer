# FDS SeoPro Analyzer

Premium AI-powered SEO audit tool — powered by **Groq AI** (free, fast) and
**Google PageSpeed Insights**. Deployed on **Vercel**, installable as an app
on phone and desktop (PWA).

---

## How it works

```
Your phone/browser  →  Vercel serverless functions  →  Groq AI + Google PageSpeed
     (index.html)         (/api/analyze, /api/pagespeed)
```

The frontend never calls Groq or Google directly — it calls Vercel's own
`/api/*` routes (same domain, so **no CORS errors ever**). Those serverless
functions make the actual API calls server-side.

---

## Part 1 — Get your free Groq API key

1. Go to **https://console.groq.com/keys**
2. Sign up (free, no credit card)
3. Click **"Create API Key"**
4. Copy the key — it looks like `gsk_...`

Groq's free tier is generous and Llama 3.3 70B is very fast — perfect for this.

---

## Part 2 — Push this project to GitHub

1. Go to **https://github.com/new** and create a new repository
   (e.g. `fds-seopro-analyzer`) — keep it Public or Private, either works.
2. On your computer, inside this folder, run:

```bash
git init
git add .
git commit -m "Initial commit - FDS SeoPro Analyzer"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/fds-seopro-analyzer.git
git push -u origin main
```

(Replace `YOUR_USERNAME` with your actual GitHub username.)

**No git installed / prefer the website?**
Go to your new empty repo on GitHub → click **"uploading an existing file"**
→ drag this entire folder in → commit.

---

## Part 3 — Deploy to Vercel

1. Go to **https://vercel.com** and sign up (use "Continue with GitHub" — easiest)
2. Click **"Add New..." → "Project"**
3. Find your `fds-seopro-analyzer` repo → click **"Import"**
4. Vercel auto-detects the Python functions in `/api`. Leave all build settings as default.
5. Before clicking Deploy, expand **"Environment Variables"** and add:
   - **Name:** `GROQ_API_KEY`
   - **Value:** *(paste your `gsk_...` key here)*
6. Click **"Deploy"**

In about 60 seconds you'll get a live URL like:

```
https://fds-seopro-analyzer.vercel.app
```

That's it — open that URL on your phone or computer. No fetch errors, no CORS
issues, because everything runs through your own Vercel domain.

---

## Part 4 — Install on your phone (PWA, works like a real app)

**Android (Chrome):**
1. Open your Vercel URL in Chrome
2. Tap the **⋮ menu → "Add to Home screen"** (or look for the install banner)
3. It installs with its own icon, opens full-screen, no browser bar

**iPhone (Safari):**
1. Open your Vercel URL in Safari
2. Tap the **Share button** (square with arrow)
3. Scroll down → **"Add to Home Screen"** → **Add**

**Desktop (Chrome/Edge):**
1. Open your Vercel URL
2. Click the **install icon** in the address bar, or the **download icon** in the app's header
3. Opens as a standalone app window

---

## Part 5 — Optional: real Android APK

Once your Vercel URL is live:

1. Go to **https://www.pwabuilder.com**
2. Paste your Vercel URL
3. Click **"Start"** → it scores your PWA → click **"Package for Stores"**
4. Choose **Android** → download the signed APK
5. Install directly on any Android phone (enable "install from unknown sources" if prompted)

---

## Updating the app later

Any time you push new changes to GitHub (`git push`), Vercel automatically
redeploys within ~60 seconds. No manual redeploy needed.

```bash
git add .
git commit -m "Update: improved keyword analysis"
git push
```

---

## File structure

```
fds-seopro-vercel/
├── index.html          ← Frontend app (mobile-optimized, installable)
├── manifest.json        ← PWA install config
├── sw.js                ← Service worker (offline support)
├── vercel.json          ← Vercel function config
├── icons/                ← App icons (8 sizes)
└── api/
    ├── analyze.py        ← Calls Groq AI for the full SEO audit
    └── pagespeed.py      ← Proxies Google PageSpeed (bypasses CORS)
```

---

## Troubleshooting

**"No Groq API key provided" error**
→ Either paste your key in the app's Settings (gear icon), or make sure
`GROQ_API_KEY` is set correctly in Vercel → Project Settings → Environment
Variables, then redeploy.

**PageSpeed shows "AI Mode" banner**
→ Google's free PageSpeed API has rate limits. This isn't an error — the
app automatically falls back to Groq AI estimating the technical scores.
Wait a few minutes and try again for real Core Web Vitals data.

**Changes not showing after `git push`**
→ Check the "Deployments" tab in your Vercel dashboard — it usually takes
30-90 seconds to rebuild.
