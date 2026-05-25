from google import genai
from google.genai import types
import requests, os, json
from datetime import datetime

# ── CONFIG ──────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]

TODAY = datetime.now().strftime("%A, %d %B %Y")

# ── PROMPT ──────────────────────────────────────────────────────────
PROMPT = f"""
Today is {TODAY}.

You are a market intelligence analyst for a Category Manager at Shopee Indonesia.
Categories: Food & Beverage, Homecare, Personal Care (grocery).

Search the web for the 3-5 most important news items from the last 48 hours relevant to:
- Indonesian economy, consumer spending, inflation (Kompas, Detik, CNBC Indonesia)
- Government regulations: BPOM, Kemendag, Kemenko Perekonomian
- Viral/trending products on Indonesian TikTok or Instagram
- Global FMCG/CPG trends reaching Indonesia

For EACH news item, assess impact on these 5 levers:
1. Assortment — affect what products to carry or remove?
2. Price — affect pricing strategy or consumer price sensitivity?
3. Seller Investment — affect how much sellers invest on the platform?
4. Content Commerce — affect live selling, affiliates, or content trends?
5. Seller Sentiment — make sellers more optimistic or pessimistic?

Label each lever GOOD or BAD with a short specific reason.
Then give category-specific impact for Food & Beverage and Homecare.

Return ONLY a valid JSON array, no markdown fences, no explanation:
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

# ── CALL GEMINI WITH GOOGLE SEARCH ───────────────────────────────────
client = genai.Client(api_key=GEMINI_API_KEY)

response = client.models.generate_content(
    model="gemini-2.0-flash-lite",
    contents=PROMPT,
    config=types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=0.3,
    ),
)

raw = response.text.strip()
if raw.startswith("```"):
    raw = raw.split("```")[1]
    if raw.startswith("json"):
        raw = raw[4:]
raw = raw.strip()

news_items = json.loads(raw)

# ── SEND TO TELEGRAM ─────────────────────────────────────────────────
def emoji(verdict):
    return "✅" if verdict.strip().upper() == "GOOD" else "❌"

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload)
    r.raise_for_status()

# Header
send_telegram(
    f"📡 <b>SHOPEE GROCERY — MARKET INTEL</b>\n"
    f"📅 {TODAY}\n"
    f"🔍 {len(news_items)} signals found\n"
    f"{'─' * 28}"
)

# Each news item
for i, item in enumerate(news_items, 1):
    msg = (
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
    send_telegram(msg)

# Footer
send_telegram("✅ <b>End of daily scan.</b>\nPowered by Gemini AI + Google Search\nAuto-runs 07:00 WIB daily")

print(f"✅ Sent {len(news_items)} news items to Telegram for {TODAY}")
