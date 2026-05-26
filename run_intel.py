from google import genai
from google.genai import types
import requests, os, json, hashlib
from datetime import datetime
from pathlib import Path

# ── CONFIG ──────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]

NOW   = datetime.utcnow()
TODAY = NOW.strftime("%A, %d %B %Y")
HOUR  = NOW.strftime("%H:%M UTC")

# ── SEEN NEWS TRACKER ────────────────────────────────────────────────
SEEN_FILE = Path("seen_news.json")

def load_seen():
    try:
        data = json.loads(SEEN_FILE.read_text())
        if data.get("date") != NOW.strftime("%Y-%m-%d"):
            return {"date": NOW.strftime("%Y-%m-%d"), "hashes": []}
        return data
    except:
        return {"date": NOW.strftime("%Y-%m-%d"), "hashes": []}

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

# ── STEP 1: SEARCH with Gemini ───────────────────────────────────────
# First call: use Google Search to gather raw news
client = genai.Client(api_key=GEMINI_API_KEY)

search_prompt = f"""
Today is {TODAY}, time is {HOUR}.

Search for news from the last 3-4 hours about:
1. Indonesian economy, inflation, consumer spending (Kompas, Detik, CNBC Indonesia)
2. BPOM or Kemendag regulations affecting food, beverage, or homecare products
3. Viral food/beverage/homecare products on Indonesian TikTok or Instagram
4. Global FMCG trends relevant to Indonesia

Find 3-5 relevant news items and summarize each one with its URL.
"""

search_response = client.models.generate_content(
    model="gemini-2.5-flash-lite",
    contents=search_prompt,
    config=types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=0.3,
    ),
)

# Extract text from search response — handle None safely
search_text = ""
if search_response and search_response.candidates:
    for candidate in search_response.candidates:
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if hasattr(part, 'text') and part.text:
                    search_text += part.text

if not search_text.strip():
    print(f"No search results at {HOUR} — skipping")
    exit(0)

# ── STEP 2: ANALYZE with Gemini (no search tool, just text) ──────────
analysis_prompt = f"""
You are a market intelligence analyst for a Shopee Indonesia Category Manager.
Categories: Food & Beverage, Homecare, Personal Care.

Here are today's news summaries gathered from web search:
{search_text}

For each news item, assess impact on these 5 levers:
- Assortment: affect what products to carry or remove?
- Price: affect pricing or consumer price sensitivity?
- Seller Investment: affect how much sellers invest on platform?
- Content Commerce: affect live selling or content trends?
- Seller Sentiment: make sellers optimistic or pessimistic?

Label each GOOD or BAD with a short reason.

Return ONLY a JSON array. No markdown. No explanation. Just JSON:
[
  {{
    "news_title": "concise headline",
    "link": "URL if available, else N/A",
    "assortment_verdict": "GOOD",
    "assortment_reason": "short reason",
    "price_verdict": "BAD",
    "price_reason": "short reason",
    "seller_investment_verdict": "GOOD",
    "seller_investment_reason": "short reason",
    "content_commerce_verdict": "GOOD",
    "content_commerce_reason": "short reason",
    "seller_sentiment_verdict": "BAD",
    "seller_sentiment_reason": "short reason",
    "category_food_beverage": "1-2 sentence impact on F&B",
    "category_homecare": "1-2 sentence impact on Homecare"
  }}
]
"""

analysis_response = client.models.generate_content(
    model="gemini-2.5-flash-lite",
    contents=analysis_prompt,
    config=types.GenerateContentConfig(temperature=0.2),
)

# Extract text safely
raw = ""
if analysis_response and analysis_response.candidates:
    for candidate in analysis_response.candidates:
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if hasattr(part, 'text') and part.text:
                    raw += part.text

if not raw.strip():
    print(f"No analysis output at {HOUR} — skipping")
    exit(0)

# ── STEP 3: PARSE JSON ────────────────────────────────────────────────
raw = raw.strip()
if "```" in raw:
    parts = raw.split("```")
    for p in parts:
        if p.startswith("json"):
            raw = p[4:].strip()
            break
        elif "[" in p:
            raw = p.strip()
            break

# Find the JSON array
start = raw.find("[")
end = raw.rfind("]") + 1
if start == -1 or end == 0:
    print(f"Could not find JSON in response — skipping")
    exit(0)

raw = raw[start:end]
all_items = json.loads(raw)

# ── STEP 4: FILTER SEEN NEWS ─────────────────────────────────────────
seen = load_seen()
new_items = []
for item in all_items:
    h = make_hash(item["news_title"])
    if h not in seen["hashes"]:
        new_items.append(item)
        seen["hashes"].append(h)
save_seen(seen)

if not new_items:
    print(f"No new news at {HOUR} — nothing sent")
    exit(0)

# ── STEP 5: SEND TO TELEGRAM ─────────────────────────────────────────
send_telegram(
    f"📡 <b>SHOPEE GROCERY — MARKET INTEL</b>\n"
    f"📅 {TODAY} · {HOUR}\n"
    f"🔍 {len(new_items)} new signal(s) found\n"
    f"{'─' * 28}"
)

for i, item in enumerate(new_items, 1):
    send_telegram(
        f"<b>NEWS {i}: {item['news_title']}</b>\n\n"
        f"🔗 <b>Link:</b> {item.get('link', 'N/A')}\n\n"
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
    "✅ <b>End of scan.</b>\n"
    "Powered by Gemini 2.5 Flash-Lite + Google Search\n"
    "Auto-runs every 3 hours · 07:00 WIB onwards"
)

print(f"✅ Sent {len(new_items)} item(s) to Telegram at {HOUR}")
