from google import genai
from google.genai import types
import requests, os, json, hashlib
from datetime import datetime
from pathlib import Path

# ── CONFIG ──────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]

NOW        = datetime.utcnow()
TODAY      = NOW.strftime("%A, %d %B %Y")
HOUR_UTC   = NOW.strftime("%H:%M UTC")
HOUR_WIB   = NOW.hour + 7
if HOUR_WIB >= 24: HOUR_WIB -= 24
IS_MORNING = HOUR_WIB in [7, 8]

TRUSTED_DOMAINS = [
    "kompas.com", "tempo.co", "detik.com", "cnbcindonesia.com",
    "bisnis.com", "kontan.co.id", "katadata.co.id", "antaranews.com",
    "liputan6.com", "mediaindonesia.com", "republika.co.id",
    "kemendag.go.id", "bpom.go.id", "thejakartapost.com",
]

# ── SEEN NEWS TRACKER ────────────────────────────────────────────────
SEEN_FILE = Path("seen_news.json")

def load_seen():
    try:
        data = json.loads(SEEN_FILE.read_text())
        if data.get("date") != NOW.strftime("%Y-%m-%d"):
            return {"date": NOW.strftime("%Y-%m-%d"), "hashes": [], "scans": 0, "found": 0}
        return data
    except:
        return {"date": NOW.strftime("%Y-%m-%d"), "hashes": [], "scans": 0, "found": 0}

def save_seen(data):
    SEEN_FILE.write_text(json.dumps(data))

def make_hash(title):
    return hashlib.md5(title.lower().strip().encode()).hexdigest()

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,  # show link preview so you can verify
    })
    r.raise_for_status()

def emoji(verdict):
    return "✅" if verdict.strip().upper() == "GOOD" else "❌"

def extract_text(response):
    text = ""
    if response and response.candidates:
        for candidate in response.candidates:
            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if hasattr(part, "text") and part.text:
                        text += part.text
    return text.strip()

def extract_grounding_urls(response):
    """Get real URLs + titles directly from Gemini grounding metadata."""
    items = []
    try:
        if not response or not response.candidates:
            return items
        for candidate in response.candidates:
            gm = getattr(candidate, "grounding_metadata", None)
            if not gm: continue
            chunks = getattr(gm, "grounding_chunks", None)
            if not chunks: continue
            for chunk in chunks:
                web = getattr(chunk, "web", None)
                if not web: continue
                uri = getattr(web, "uri", "")
                title = getattr(web, "title", "")
                if uri and uri.startswith("http"):
                    items.append({"url": uri, "title": title})
    except Exception as e:
        print(f"Grounding extract error: {e}")
    return items

def is_trusted_url(url):
    if not url or not url.startswith("http"): return False
    if "example.com" in url or "google.com" in url: return False
    return any(d in url for d in TRUSTED_DOMAINS)

def match_url_to_title(title, grounding_items):
    """Find best matching URL from grounding results for a given title."""
    title_words = [w for w in title.lower().split() if len(w) > 4]
    best_url, best_score = None, 0
    for item in grounding_items:
        url = item["url"]
        if not is_trusted_url(url): continue
        # homepage URLs are too short/generic — skip them
        if url.rstrip("/") in [
            "https://kompas.com", "https://www.kompas.com",
            "https://detik.com", "https://www.detik.com",
            "https://tempo.co", "https://www.tempo.co",
            "https://bisnis.com", "https://www.bisnis.com",
            "https://cnbcindonesia.com", "https://www.cnbcindonesia.com",
            "https://katadata.co.id", "https://www.katadata.co.id",
            "https://liputan6.com", "https://www.liputan6.com",
            "https://kontan.co.id", "https://www.kontan.co.id",
        ]: continue
        combined = (url + " " + item.get("title", "")).lower()
        score = sum(1 for w in title_words if w in combined)
        if score > best_score:
            best_score = score
            best_url = url
    return best_url if best_score >= 1 else None

# ── LOAD SEEN DATA ───────────────────────────────────────────────────
seen = load_seen()
seen["scans"] = seen.get("scans", 0) + 1

# ── MORNING HEARTBEAT ────────────────────────────────────────────────
if IS_MORNING:
    send_telegram(
        f"🟢 <b>BOT STATUS: RUNNING</b>\n"
        f"📅 {TODAY}\n"
        f"⏰ Good morning! Daily scan started.\n\n"
        f"<b>Yesterday:</b> {seen.get('found', 0)} news sent across {seen.get('scans', 0)} scans\n\n"
        f"📡 Scanning every 3 hours · trusted Indonesian sources only\n"
        f"<i>If you see this, the bot is alive ✅</i>"
    )
    seen["scans"] = 0
    seen["found"] = 0
    save_seen(seen)

# ── STEP 1: ONE FOCUSED SEARCH (better than 10 scattered ones) ───────
client = genai.Client(api_key=GEMINI_API_KEY)

# Single well-crafted search — more focused = better relevance
search_prompt = f"""
Today is {TODAY}.

Search Google News for Indonesian news published in the LAST 24 HOURS only.

Search these specific topics and find real articles:
1. site:kompas.com OR site:detik.com OR site:tempo.co OR site:cnbcindonesia.com OR site:bisnis.com OR site:kontan.co.id OR site:katadata.co.id OR site:antaranews.com (Kemendag OR Permendag OR marketplace OR e-commerce OR Shopee OR Tokopedia)
2. site:kompas.com OR site:detik.com OR site:cnbcindonesia.com (BPOM OR "harga pangan" OR "minyak goreng" OR "harga beras" OR inflasi OR FMCG)
3. site:kompas.com OR site:detik.com OR site:cnbcindonesia.com ("TikTok Shop" OR "Shopee" OR "live commerce" OR "belanja online" OR "penjual online")

For EACH real article found, output:
TITLE: [exact article headline]
DATE: [publication date, e.g. 3 Juni 2026]
SOURCE: [domain name]
SUMMARY: [2 sentence summary of what happened]
---

STRICT RULES:
- Only include articles published in the LAST 24 HOURS
- If you cannot confirm the date, skip the article
- Do NOT include job listings, press releases, or company profiles
- Do NOT make up articles — only report what you actually found
- If nothing found: output NONE
"""

resp = client.models.generate_content(
    model="gemini-2.5-flash-lite",
    contents=search_prompt,
    config=types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=0.1,
    ),
)

search_text = extract_text(resp)
grounding_urls = extract_grounding_urls(resp)

if not search_text or "NONE" in search_text or len(search_text.strip()) < 20:
    save_seen(seen)
    print(f"No relevant news found at {HOUR_UTC}")
    exit(0)

# ── STEP 2: ANALYZE + STRUCTURE ──────────────────────────────────────
analysis_prompt = f"""
You are a market intelligence analyst for a Shopee Indonesia Category Manager.
Categories: Food & Beverage, Homecare, Personal Care (grocery).

Here are today's news from Indonesian trusted media:
{search_text}

From this list, select ONLY articles that are relevant to:
- Indonesian FMCG / grocery products (food, beverage, homecare, personal care)
- E-commerce marketplace regulation or policy in Indonesia
- Commodity prices affecting grocery (rice, cooking oil, sugar)
- Consumer spending / inflation in Indonesia
- Viral trending products in Indonesia

SKIP anything that is: job listing, sports, entertainment, politics unrelated to economy,
international news with no Indonesia market impact.

For each relevant article, assess impact on 5 levers:
- Assortment: affect what products to carry?
- Price: affect pricing or consumer price sensitivity?
- Seller Investment: affect seller spending on platform?
- Content Commerce: affect live selling or content trends?
- Seller Sentiment: make sellers optimistic or pessimistic?

Return ONLY a valid JSON array. No markdown. No text before or after the JSON:
[
  {{
    "news_title": "exact headline",
    "source": "e.g. Kompas.com",
    "publish_date": "e.g. 3 Juni 2026",
    "assortment_verdict": "GOOD or BAD",
    "assortment_reason": "specific reason max 12 words",
    "price_verdict": "GOOD or BAD",
    "price_reason": "specific reason max 12 words",
    "seller_investment_verdict": "GOOD or BAD",
    "seller_investment_reason": "specific reason max 12 words",
    "content_commerce_verdict": "GOOD or BAD",
    "content_commerce_reason": "specific reason max 12 words",
    "seller_sentiment_verdict": "GOOD or BAD",
    "seller_sentiment_reason": "specific reason max 12 words",
    "category_food_beverage": "1-2 sentence specific impact on F&B",
    "category_homecare": "1-2 sentence specific impact on Homecare"
  }}
]

If nothing qualifies return: []
"""

analysis_resp = client.models.generate_content(
    model="gemini-2.5-flash-lite",
    contents=analysis_prompt,
    config=types.GenerateContentConfig(temperature=0.1),
)

raw = extract_text(analysis_resp)
if not raw:
    save_seen(seen); exit(0)

# Parse JSON
if "```" in raw:
    for block in raw.split("```"):
        if block.startswith("json"): raw = block[4:].strip(); break
        elif "[" in block: raw = block.strip(); break

start = raw.find("["); end = raw.rfind("]") + 1
if start == -1 or end == 0:
    save_seen(seen); exit(0)

all_items = json.loads(raw[start:end])

# ── STEP 3: MATCH REAL URLs FROM GROUNDING METADATA ─────────────────
for item in all_items:
    real_url = match_url_to_title(item["news_title"], grounding_urls)
    item["link"] = real_url  # None if not found

# ── STEP 4: FILTER ───────────────────────────────────────────────────
new_items = []
for item in all_items:
    h = make_hash(item["news_title"])
    if h in seen["hashes"]:
        continue
    # Must have a real verified URL — no URL = likely hallucination, skip
    if not item.get("link"):
        print(f"Skipped (no verified URL): {item['news_title']}")
        continue
    new_items.append(item)
    seen["hashes"].append(h)

seen["found"] = seen.get("found", 0) + len(new_items)
save_seen(seen)

if not new_items:
    print(f"No new verified news at {HOUR_UTC}")
    exit(0)

# ── STEP 5: SEND TO TELEGRAM ─────────────────────────────────────────
send_telegram(
    f"📡 <b>SHOPEE GROCERY — MARKET INTEL</b>\n"
    f"📅 {TODAY} · {HOUR_UTC}\n"
    f"🔍 {len(new_items)} verified signal(s)\n"
    f"{'─' * 28}"
)

for i, item in enumerate(new_items, 1):
    pub_date = item.get("publish_date", "")
    date_line = f"📅 <b>Published:</b> {pub_date}\n" if pub_date else ""
    send_telegram(
        f"<b>NEWS {i}: {item['news_title']}</b>\n\n"
        f"📰 <b>Source:</b> {item.get('source', '')}\n"
        f"{date_line}"
        f"🔗 {item['link']}\n\n"
        f"<b>Impact to Shopee:</b>\n"
        f"{emoji(item['assortment_verdict'])} <b>Assortment:</b> {item['assortment_verdict']} — {item['assortment_reason']}\n"
        f"{emoji(item['price_verdict'])} <b>Price:</b> {item['price_verdict']} — {item['price_reason']}\n"
        f"{emoji(item['seller_investment_verdict'])} <b>Seller Investment:</b> {item['seller_investment_verdict']} — {item['seller_investment_reason']}\n"
        f"{emoji(item['content_commerce_verdict'])} <b>Content Commerce:</b> {item['content_commerce_verdict']} — {item['content_commerce_reason']}\n"
        f"{emoji(item['seller_sentiment_verdict'])} <b>Seller Sentiment:</b> {item['seller_sentiment_verdict']} — {item['seller_sentiment_reason']}\n\n"
        f"<b>Category Impact:</b>\n"
        f"🍜 <b>Food &amp; Beverage:</b> {item['category_food_beverage']}\n"
        f"🧴 <b>Homecare:</b> {item['category_homecare']}"
    )

send_telegram(
    f"✅ <b>Scan complete.</b> {len(new_items)} item(s) sent.\n"
    f"Next scan in ~3 hours ✅"
)
print(f"✅ Sent {len(new_items)} item(s) at {HOUR_UTC}")
