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
IS_MORNING = HOUR_WIB in [7, 8]  # catch delayed runs between 7-8AM WIB

# ── TRUSTED INDONESIAN NEWS SOURCES ─────────────────────────────────
TRUSTED_SOURCES = [
    "kompas.com", "tempo.co", "detik.com", "cnbcindonesia.com",
    "bisnis.com", "kontan.co.id", "republika.co.id", "liputan6.com",
    "antara.id", "antaranews.com", "mediaindonesia.com",
    "katadata.co.id", "swa.co.id", "marketing.co.id",
    "bpom.go.id", "kemendag.go.id", "kemenperin.go.id",
    "foodreview.co.id", "techinasia.com", "dailysocial.id",
    "idntimes.com", "kumparan.com", "thejakartapost.com",
]
SOURCES_LIST = ", ".join(TRUSTED_SOURCES)

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

# ── LOAD SEEN DATA ───────────────────────────────────────────────────
seen = load_seen()
seen["scans"] = seen.get("scans", 0) + 1

# DEBUG — remove after fixing
send_telegram(f"🔧 DEBUG: Script started at {HOUR_UTC} WIB:{HOUR_WIB}")



# ── MORNING HEARTBEAT ────────────────────────────────────────────────
if IS_MORNING:
    send_telegram(
        f"🟢 <b>BOT STATUS: RUNNING</b>\n"
        f"📅 {TODAY}\n"
        f"⏰ Good morning! Daily scan started.\n\n"
        f"<b>Yesterday's summary:</b>\n"
        f"• Scans run: {seen.get('scans', 1)}\n"
        f"• News items sent: {seen.get('found', 0)}\n\n"
        f"📡 Scanning every 3 hours from trusted Indonesian sources\n\n"
        f"<i>If you see this, the bot is alive and working ✅</i>"
    )
    seen["scans"] = 0
    seen["found"] = 0
    save_seen(seen)

# ── STEP 1: SEARCH ───────────────────────────────────────────────────
client = genai.Client(api_key=GEMINI_API_KEY)

search_prompt = f"""
Today is {TODAY}, time is {HOUR_UTC}.

Search for news from the last 7 days from these trusted Indonesian sources:
{SOURCES_LIST}

Find news about ANY of these topics relevant to Indonesian grocery e-commerce:

FMCG & GROCERY: Indomie, Aqua, Unilever Indonesia, Wings, Indofood, Mayora, Garudafood,
Rinso, Sunlight, Wardah, Emina, Pepsodent, Indomaret, Alfamart, BPOM recall, penarikan produk,
sertifikasi halal, harga minyak goreng, harga beras, harga gula, inflasi pangan, produk baru FMCG

E-COMMERCE & MARKETPLACE: Shopee Indonesia, Tokopedia, TikTok Shop Indonesia, Lazada, Blibli,
Permendag, regulasi marketplace, keluhan penjual marketplace, Kemendag e-commerce,
aturan seller, biaya platform, live commerce Indonesia, affiliate marketing, logistik J&T JNE SiCepat,
kebijakan platform digital, UMKM online, perlindungan penjual

ECONOMY: inflasi Indonesia, daya beli masyarakat, harga barang pokok, subsidi pangan,
HET harga eceran tertinggi, impor pangan, bea masuk, kurs rupiah

TRENDS: produk viral TikTok Indonesia, makanan viral, Korean food Indonesia, K-beauty Indonesia,
frozen food, makanan sehat, belanja online trend

RULES:
- Indonesia market impact ONLY — skip global news with no Indonesia angle
- Must be from the trusted sources list above
- Include the EXACT URL as it appeared in search results
- If no real URL found for an item, skip that item entirely
- Do NOT invent or guess URLs

For each item: headline | real URL | source name | 2-3 sentence summary
If nothing found: NO_NEWS
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

# DEBUG
send_telegram(f"🔧 DEBUG: Search done. Got text: {bool(search_text)} | NO_NEWS: {'NO_NEWS' in search_text if search_text else 'N/A'} | Length: {len(search_text) if search_text else 0}")

if not search_text or "NO_NEWS" in search_text:
    save_seen(seen)
    print(f"No relevant news at {HOUR_UTC}")
    exit(0)

# ── STEP 2: ANALYZE ──────────────────────────────────────────────────
analysis_prompt = f"""
You are a market intelligence analyst for a Shopee Indonesia Category Manager.
Categories: Food & Beverage, Homecare, Personal Care (grocery).

Here are today's news items from trusted Indonesian media:
{search_text}

IMPORTANT: Before analyzing, check each news item:
- Is it directly relevant to INDONESIAN market, sellers, or consumers? 
- If NO → skip it entirely, do not include in output
- If YES → analyze it

For relevant items, assess impact across 5 levers:
- Assortment: affect what products to carry or remove?
- Price: affect pricing or consumer price sensitivity?
- Seller Investment: affect how much sellers invest on platform?
- Content Commerce: affect live selling or content trends?
- Seller Sentiment: make sellers optimistic or pessimistic?

Label each GOOD or BAD with a short specific reason.
For the "link" field: use the exact URL from the search results above.
If no real URL was found, write "NOT_FOUND" — never invent a URL.

Return ONLY a valid JSON array. No markdown. No text before or after:
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

raw = extract_text(analysis_response)

if not raw:
    save_seen(seen)
    print(f"No analysis output at {HOUR_UTC}")
    exit(0)

# ── STEP 3: PARSE JSON ────────────────────────────────────────────────
if "```" in raw:
    for block in raw.split("```"):
        if block.startswith("json"):
            raw = block[4:].strip(); break
        elif "[" in block:
            raw = block.strip(); break

start = raw.find("[")
end   = raw.rfind("]") + 1
if start == -1 or end == 0:
    save_seen(seen)
    print(f"Could not parse JSON at {HOUR_UTC}")
    exit(0)

all_items = json.loads(raw[start:end])

# DEBUG
send_telegram(f"🔧 DEBUG: Parsed {len(all_items)} items from JSON")

# ── STEP 4: FILTER SEEN NEWS ─────────────────────────────────────────
new_items = []
for item in all_items:
    h = make_hash(item["news_title"])
    if h not in seen["hashes"]:
        new_items.append(item)
        seen["hashes"].append(h)

seen["found"] = seen.get("found", 0) + len(new_items)
save_seen(seen)

if not new_items:
    print(f"No new news at {HOUR_UTC} — already seen")
    send_telegram(f"🔧 DEBUG: No new items after dedup filter. Total seen hashes: {len(seen['hashes'])}")
    exit(0)

# DEBUG — show how many pass URL filter
send_telegram(f"🔧 DEBUG: {len(new_items)} new items after dedup. Now checking URLs...")

# ── STEP 5: SEND TO TELEGRAM ─────────────────────────────────────────
send_telegram(
    f"📡 <b>SHOPEE GROCERY — MARKET INTEL</b>\n"
    f"📅 {TODAY} · {HOUR_UTC}\n"
    f"🔍 {len(new_items)} new signal(s) found\n"
    f"{'─' * 28}"
)

for i, item in enumerate(new_items, 1):
    source = item.get("source", "")
    raw_link = item.get("link", "NOT_FOUND")

    # Drop item entirely if no real URL — likely hallucination
    is_real_url = (
        raw_link and
        raw_link != "NOT_FOUND" and
        raw_link.startswith("http") and
        "example.com" not in raw_link and
        len(raw_link) > 20
    )
    if not is_real_url:
        print(f"Skipped item with no real URL: {item['news_title']}")
        continue

    send_telegram(
        f"<b>NEWS {i}: {item['news_title']}</b>\n\n"
        f"{'📰 <b>Source:</b> ' + source + chr(10) if source else ''}"
        f"🔗 <b>Link:</b> {raw_link}\n\n"
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
    f"Next scan in ~3 hours. Bot running normally ✅"
)

print(f"✅ Sent {len(new_items)} item(s) to Telegram at {HOUR_UTC}")
