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

# ── TARGETED SEARCH QUERIES ──────────────────────────────────────────
SEARCH_QUERIES = [
    "Kemendag Permendag marketplace Indonesia 2026",
    "regulasi e-commerce Shopee Tokopedia TikTok Shop Indonesia 2026",
    "keluhan penjual marketplace Kemendag 2026",
    "harga minyak goreng beras gula Indonesia 2026",
    "BPOM recall penarikan produk makanan minuman 2026",
    "inflasi harga pangan Indonesia 2026",
    "Shopee Indonesia kebijakan seller 2026",
    "TikTok Shop Indonesia live commerce 2026",
    "produk FMCG viral Indonesia 2026",
    "Korean food K-beauty trend Indonesia 2026",
]

TRUSTED_DOMAINS = [
    "kompas.com", "tempo.co", "detik.com", "cnbcindonesia.com",
    "bisnis.com", "kontan.co.id", "katadata.co.id", "antaranews.com",
    "liputan6.com", "mediaindonesia.com", "republika.co.id",
    "kemendag.go.id", "bpom.go.id", "thejakartapost.com",
    "swa.co.id", "marketing.co.id", "foodreview.co.id",
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
        "disable_web_page_preview": True,
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

def extract_real_urls(response):
    """Extract real URLs from Gemini grounding metadata — these are verified source URLs."""
    urls = []
    try:
        if not response or not response.candidates:
            return urls
        for candidate in response.candidates:
            if not hasattr(candidate, "grounding_metadata"):
                continue
            gm = candidate.grounding_metadata
            if not gm:
                continue
            # grounding_chunks contains the actual URLs Gemini retrieved
            if hasattr(gm, "grounding_chunks") and gm.grounding_chunks:
                for chunk in gm.grounding_chunks:
                    if hasattr(chunk, "web") and chunk.web:
                        uri = chunk.web.uri
                        title = getattr(chunk.web, "title", "")
                        if uri and uri.startswith("http"):
                            urls.append({"url": uri, "title": title})
    except Exception as e:
        print(f"URL extraction error: {e}")
    return urls

def is_trusted_url(url):
    if not url: return False
    if not url.startswith("http"): return False
    if "example.com" in url: return False
    return any(domain in url for domain in TRUSTED_DOMAINS)

def find_best_url(title, grounding_urls):
    """Match article title to the best grounding URL."""
    title_words = set(title.lower().split())
    best_url = None
    best_score = 0
    for item in grounding_urls:
        url = item["url"]
        if not is_trusted_url(url): continue
        # Score by how many title words appear in the URL or its title
        combined = (url + " " + item.get("title", "")).lower()
        score = sum(1 for w in title_words if len(w) > 4 and w in combined)
        if score > best_score:
            best_score = score
            best_url = url
    return best_url

# ── LOAD SEEN DATA ───────────────────────────────────────────────────
seen = load_seen()
seen["scans"] = seen.get("scans", 0) + 1

# ── MORNING HEARTBEAT ────────────────────────────────────────────────
if IS_MORNING:
    send_telegram(
        f"🟢 <b>BOT STATUS: RUNNING</b>\n"
        f"📅 {TODAY}\n"
        f"⏰ Good morning! Daily scan started.\n\n"
        f"<b>Yesterday's summary:</b>\n"
        f"• Scans run: {seen.get('scans', 1)}\n"
        f"• News items sent: {seen.get('found', 0)}\n\n"
        f"📡 Scanning every 3 hours · trusted Indonesian sources only\n"
        f"<i>If you see this, the bot is alive ✅</i>"
    )
    seen["scans"] = 0
    seen["found"] = 0
    save_seen(seen)

# ── STEP 1: TARGETED SEARCHES + COLLECT REAL URLs ────────────────────
client = genai.Client(api_key=GEMINI_API_KEY)

all_search_text = ""
all_grounding_urls = []  # real URLs from Gemini's actual search

for query in SEARCH_QUERIES:
    search_prompt = f"""
Search for Indonesian news about: "{query}"
Find articles from last 24 hours from: kompas.com, tempo.co, detik.com,
cnbcindonesia.com, bisnis.com, kontan.co.id, katadata.co.id, antaranews.com,
liputan6.com, kemendag.go.id, bpom.go.id

For each article found:
TITLE: [exact headline]
SOURCE: [domain]
SUMMARY: [2 sentences]
---
Output NONE if nothing found.
"""
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=search_prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.1,
            ),
        )
        result = extract_text(resp)
        if result and "NONE" not in result:
            all_search_text += f"\n\n=== {query} ===\n{result}"

        # Extract real URLs from grounding metadata
        urls = extract_real_urls(resp)
        all_grounding_urls.extend(urls)

    except Exception as e:
        print(f"Search error for '{query}': {e}")
        continue

if not all_search_text.strip():
    save_seen(seen)
    print(f"No results at {HOUR_UTC}")
    exit(0)

# ── STEP 2: ANALYZE ───────────────────────────────────────────────────
analysis_prompt = f"""
You are a market intelligence analyst for a Shopee Indonesia Category Manager.
Categories: Food & Beverage, Homecare, Personal Care.

News search results from Indonesian trusted media:
{all_search_text}

Extract ONLY news that is:
- Directly relevant to Indonesian FMCG, grocery, or e-commerce marketplace
- NOT job listings, NOT company profiles, NOT sports, NOT entertainment
- NOT global news with no Indonesia market impact

For each relevant item assess 5 levers:
- Assortment: affect what products to carry?
- Price: affect pricing or consumer price sensitivity?
- Seller Investment: affect seller spending on platform?
- Content Commerce: affect live selling or content trends?
- Seller Sentiment: make sellers optimistic or pessimistic?

Return ONLY valid JSON array, no markdown, no text outside JSON:
[
  {{
    "news_title": "exact headline",
    "source": "domain e.g. Kompas.com",
    "assortment_verdict": "GOOD or BAD",
    "assortment_reason": "max 12 words",
    "price_verdict": "GOOD or BAD",
    "price_reason": "max 12 words",
    "seller_investment_verdict": "GOOD or BAD",
    "seller_investment_reason": "max 12 words",
    "content_commerce_verdict": "GOOD or BAD",
    "content_commerce_reason": "max 12 words",
    "seller_sentiment_verdict": "GOOD or BAD",
    "seller_sentiment_reason": "max 12 words",
    "category_food_beverage": "1-2 sentence impact",
    "category_homecare": "1-2 sentence impact"
  }}
]

If nothing qualifies: []
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

# ── STEP 3: MATCH REAL URLs FROM GROUNDING ───────────────────────────
# This is the key fix — use actual URLs Gemini retrieved, not hallucinated ones
for item in all_items:
    real_url = find_best_url(item["news_title"], all_grounding_urls)
    item["link"] = real_url or "NOT_FOUND"

# ── STEP 4: FILTER ───────────────────────────────────────────────────
new_items = []
for item in all_items:
    h = make_hash(item["news_title"])
    if h in seen["hashes"]: continue
    if not is_trusted_url(item.get("link", "")):
        print(f"Skipped no valid URL: {item['news_title']}")
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
    send_telegram(
        f"<b>NEWS {i}: {item['news_title']}</b>\n\n"
        f"📰 <b>Source:</b> {item.get('source','')}\n"
        f"🔗 <b>Link:</b> {item['link']}\n\n"
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
    f"✅ <b>Scan complete.</b> {len(new_items)} verified item(s).\n"
    f"Next scan in ~3 hours ✅"
)
print(f"✅ Sent {len(new_items)} item(s) at {HOUR_UTC}")
