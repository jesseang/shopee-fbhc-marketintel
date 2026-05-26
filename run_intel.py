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

# ── PROMPT ──────────────────────────────────────────────────────────
PROMPT = f"""
Today is {TODAY}, current time is {HOUR}.

You are a market intelligence analyst for a Category Manager at Shopee Indonesia.
Categories: Food & Beverage, Homecare, Personal Care (grocery).

Search the web for news from the last 3-4 hours relevant to:
- Indonesian economy, consumer spending, inflation (Kompas, Detik, CNBC Indonesia)
- Government regulations: BPOM, Kemendag, Kemenko Perekonomian
- Viral/trending products on Indonesian TikTok or Instagram
- Global FMCG/CPG trends reaching Indonesia

IMPORTANT: Only include news published in the last 3-4 hours.
If there is NO relevant new news, return exactly this: []

For EACH news item found, assess impact on these 5 levers:
1. Assortment - affect what products to carry or remove?
2. Price - affect pricing strategy or consumer price sensitivity?
3. Seller Investment - affect how much sellers invest on the platform?
4. Content Commerce - affect live selling, affiliates, or content trends?
5. Seller Sentiment - make sellers more optimistic or pessimistic?

Label each lever GOOD or BAD with a short specific reason.
Then give category-specific impact for Food & Beverage and Homecare.

Return ONLY a valid JSON array. No markdown. No explanation. Just the JSON:
[
  {{
    "news_title": "concise headline",
    "link": "actual article URL",
    "assortment_verdict": "GOOD or BAD",
    "assortment_reason": "short reason",
    "price_verdict": "GOOD or BAD",
    "price_reason": "short reason",
    "seller_investment_verdict": "GOOD or BAD",
    "seller_investment_reason": "short reason",
    "content_commerce_verdict": "GOOD or BAD",
    "content_commerce_reason": "short reason",
    "seller_sentiment_verdict": "GOOD or BAD",
    "seller_sentiment_reason": "short reason",
    "category_food_beverage": "1-2 sentence impact",
    "category_homecare": "1-2 sentence impact"
  }}
]
"""

# ── CALL GEMINI 2.5 FLASH-LITE (current free tier model) ─────────────
client = genai.Client(api_key=GEMINI_API_KEY)

response = client.models.generate_content(
    model="gemini-2.5-flash-lite",
    contents=PROMPT,
    config=types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=0.3,
    ),
)

# ── PARSE JSON ───────────────────────────────────────────────────────
raw = response.text.strip()
# Strip markdown fences if Gemini adds them
if "```" in raw:
    raw = raw.split("```")[1]
    if raw.startswith("json"):
        raw = raw[4:]
raw = raw.strip()

all_items = json.loads(raw)

# ── FILTER ALREADY-SEEN NEWS ─────────────────────────────────────────
seen = load_seen()
new_items = []
for item in all_items:
    h = make_hash(item["news_title"])
    if h not in seen["hashes"]:
        new_items.append(item)
        seen["hashes"].append(h)
save_seen(seen)

# ── NOTHING NEW → EXIT SILENTLY ──────────────────────────────────────
if not new_items:
    print(f"No new news at {HOUR} — nothing sent to Telegram")
    exit(0)

# ── SEND TO TELEGRAM ─────────────────────────────────────────────────
def emoji(verdict):
    return "✅" if verdict.strip().upper() == "GOOD" else "❌"

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })
    r.raise_for_status()

# Header
send_telegram(
    f"📡 <b>SHOPEE GROCERY — MARKET INTEL</b>\n"
    f"📅 {TODAY} · {HOUR}\n"
    f"🔍 {len(new_items)} new signal(s) found\n"
    f"{'─' * 28}"
)

# Each news item
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
