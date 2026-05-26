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

# ── TRUSTED INDONESIAN NEWS SOURCES ─────────────────────────────────
TRUSTED_SOURCES = [
    # General news
    "kompas.com", "tempo.co", "detik.com", "cnbcindonesia.com",
    "bisnis.com", "kontan.co.id", "republika.co.id", "liputan6.com",
    "antara.id", "antaranews.com", "mediaindonesia.com",
    # Business & economy
    "katadata.co.id", "industri.kontan.co.id", "ekonomi.bisnis.com",
    # Government
    "bpom.go.id", "kemendag.go.id", "kemenko.go.id", "kemenperin.go.id",
    # FMCG / trade
    "foodreview.co.id", "swa.co.id", "marketing.co.id",
]

SOURCES_LIST = ", ".join(TRUSTED_SOURCES)

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

def extract_text(response):
    """Safely extract text from Gemini response."""
    text = ""
    if response and response.candidates:
        for candidate in response.candidates:
            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if hasattr(part, "text") and part.text:
                        text += part.text
    return text.strip()

# ── STEP 1: SEARCH — trusted Indonesian sources only ─────────────────
client = genai.Client(api_key=GEMINI_API_KEY)

search_prompt = f"""
Today is {TODAY}, time is {HOUR}.

Search for news published in the last 3-4 hours about topics relevant to 
Indonesian grocery e-commerce (Food & Beverage, Homecare, Personal Care).

IMPORTANT: Only use news from these trusted Indonesian sources:
{SOURCES_LIST}

Do NOT include news from blogs, unknown sites, social media posts, or 
unverified sources. Only report news if you can confirm it comes from 
one of the trusted sources listed above.

Search for:
1. Indonesian economy, inflation, consumer spending, food prices
2. BPOM or Kemendag regulations on food, beverage, homecare, or cosmetics
3. Trending/viral food, beverage, or homecare products in Indonesia
4. Supply chain, import regulations, or commodity prices affecting grocery

For each news item found, provide:
- Headline (as written on the source)
- Full URL from the trusted source
- Which source it came from (e.g. Kompas, Tempo)
- 2-3 sentence summary

If no relevant news from trusted sources in last 3-4 hours, say: NO_NEWS
"""

search_response = client.models.generate_content(
    model="gemini-2.5-flash-lite",
    contents=search_prompt,
    config=types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=0.2,
    ),
)

search_text = extract_text(search_response)

if not search_text or "NO_NEWS" in search_text:
    print(f"No relevant news from trusted sources at {HOUR} — skipping")
    exit(0)

# ── STEP 2: ANALYZE — structured impact assessment ───────────────────
analysis_prompt = f"""
You are a market intelligence analyst for a Shopee Indonesia Category Manager.
Categories managed: Food & Beverage, Homecare, Personal Care (grocery).

Here are today's news items from trusted Indonesian media:
{search_text}

For each news item, produce a structured impact assessment across 5 levers:
- Assortment: does this affect what products to carry or remove?
- Price: does this affect pricing strategy or consumer price sensitivity?
- Seller Investment: does this affect how much sellers invest on the platform?
- Content Commerce: does this affect live selling, affiliates, or content trends?
- Seller Sentiment: does this make sellers more optimistic or pessimistic?

Label each lever GOOD or BAD. Give a short specific reason for each.
Also assess impact on Food & Beverage and Homecare sub-categories specifically.

CRITICAL: Include the exact article URL from the news summary above in "link".
If a URL was provided, use it exactly. Do not make up URLs.

Return ONLY a valid JSON array. No markdown fences. No text before or after:
[
  {{
    "news_title": "headline as reported",
    "source": "e.g. Kompas.com",
    "link": "exact URL from the article",
    "assortment_verdict": "GOOD or BAD",
    "assortment_reason": "specific reason max 15 words",
    "price_verdict": "GOOD or BAD",
    "price_reason": "specific reason max 15 words",
    "seller_investment_verdict": "GOOD or BAD",
    "seller_investment_reason": "specific reason max 15 words",
    "content_commerce_verdict": "GOOD or BAD",
    "content_commerce_reason": "specific reason max 15 words",
    "seller_sentiment_verdict": "GOOD or BAD",
    "seller_sentiment_reason": "specific reason max 15 words",
    "category_food_beverage": "1-2 sentence specific impact on F&B",
    "category_homecare": "1-2 sentence specific impact on Homecare"
  }}
]
"""

analysis_response = client.models.generate_content(
    model="gemini-2.5-flash-lite",
    contents=analysis_prompt,
    config=types.GenerateContentConfig(temperature=0.2),
)

raw = extract_text(analysis_response)

if not raw:
    print(f"No analysis output at {HOUR} — skipping")
    exit(0)

# ── STEP 3: PARSE JSON ────────────────────────────────────────────────
if "```" in raw:
    for block in raw.split("```"):
        if block.startswith("json"):
            raw = block[4:].strip()
            break
        elif "[" in block:
            raw = block.strip()
            break

start = raw.find("[")
end   = raw.rfind("]") + 1
if start == -1 or end == 0:
    print(f"Could not parse JSON at {HOUR} — skipping")
    exit(0)

all_items = json.loads(raw[start:end])

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
    source = item.get("source", "")
    source_line = f"📰 <b>Source:</b> {source}\n" if source else ""
    send_telegram(
        f"<b>NEWS {i}: {item['news_title']}</b>\n\n"
        f"{source_line}"
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
    f"Sources: Kompas · Tempo · Detik · CNBC ID · Bisnis · Kontan · Antara + more\n"
    "Auto-runs every 3 hours · 07:00 WIB"
)

print(f"✅ Sent {len(new_items)} item(s) to Telegram at {HOUR}")
