import google.generativeai as genai
import requests
import os
import json
from datetime import datetime

# ── CONFIG ──────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]

TODAY = datetime.now().strftime("%A, %d %B %Y")

# ── PROMPT ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = f"""
You are a market intelligence analyst for a Category Manager at Shopee Indonesia.
Categories managed: Food & Beverage, Homecare, Personal Care (grocery).
Today is {TODAY}.

Search for the 3-5 most important and relevant news items from the last 24-48 hours that could impact this Shopee grocery category. Focus on:
- Indonesian news (Kompas, Detik, CNBC Indonesia, CNN Indonesia)
- Government regulations (BPOM, Kemendag, Kemenko Perekonomian)
- Social media trends in Indonesia (TikTok, Instagram viral products)
- Global FMCG/CPG trends reaching Indonesia

For EACH news item found, assess impact across these 5 levers:
1. Assortment — does this affect what products we should carry or remove?
2. Price — does this affect pricing strategy or consumer price sensitivity?
3. Seller Investment — does this affect how much sellers will invest/spend on the platform?
4. Content Commerce — does this affect live selling, affiliate, or content trends?
5. Seller Sentiment — does this make sellers more optimistic or pessimistic?

For each lever: label GOOD or BAD, then give a short specific reason why.
Then assess category impact for Food & Beverage and Homecare specifically.

Return ONLY a valid JSON array. No markdown, no explanation outside JSON:
[
  {{
    "news_title": "concise news headline",
    "link": "actual URL if found, else best source URL",
    "assortment_verdict": "GOOD or BAD",
    "assortment_reason": "short specific reason",
    "price_verdict": "GOOD or BAD",
    "price_reason": "short specific reason",
    "seller_investment_verdict": "GOOD or BAD",
    "seller_investment_reason": "short specific reason",
    "content_commerce_verdict": "GOOD or BAD",
    "content_commerce_reason": "short specific reason",
    "seller_sentiment_verdict": "GOOD or BAD",
    "seller_sentiment_reason": "short specific reason",
    "category_food_beverage": "1-2 sentence impact on F&B",
    "category_homecare": "1-2 sentence impact on Homecare"
  }}
]
"""

# ── CALL GEMINI WITH SEARCH ──────────────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    tools="google_search",  # built-in grounding search, free
)

response = model.generate_content(
    f"Today is {TODAY}. Run a full market intelligence scan for a Shopee Indonesia Category Manager handling Food & Beverage, Homecare, and Personal Care. Find the 3-5 most impactful news items from the last 48 hours. Return JSON only as instructed.\n\nSystem instructions:\n{SYSTEM_PROMPT}"
)

raw = response.text.strip()
# Strip markdown fences if present
if raw.startswith("```"):
    raw = raw.split("```")[1]
    if raw.startswith("json"):
        raw = raw[4:]
raw = raw.strip()

news_items = json.loads(raw)

# ── FORMAT TELEGRAM MESSAGES ─────────────────────────────────────────
def emoji(verdict):
    return "✅" if verdict.upper() == "GOOD" else "❌"

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

# ── SEND HEADER ──────────────────────────────────────────────────────
header = (
    f"📡 <b>SHOPEE GROCERY — MARKET INTEL</b>\n"
    f"📅 {TODAY}\n"
    f"🔍 {len(news_items)} signals found\n"
    f"{'─' * 30}"
)
send_telegram(header)

# ── SEND EACH NEWS ITEM ───────────────────────────────────────────────
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

# ── SEND FOOTER ───────────────────────────────────────────────────────
send_telegram("✅ <b>End of daily scan.</b> Powered by Gemini AI + Google Search · Auto-runs 07:00 WIB")

print(f"✅ Sent {len(news_items)} news items to Telegram for {TODAY}")
