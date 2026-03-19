"""
Swing Trader Automated Alert System
=====================================
Uses Claude (with web search) to scan markets on a schedule,
score setups using the swing trader scoring model, and send
alerts when high-conviction trades are found (score >= 70).
DELIVERY OPTIONS: Telegram (default) | Email | Slack | Discord
See config section below to switch.
REQUIREMENTS:
    pip install anthropic schedule requests python-dotenv
SETUP:
    1. Copy .env.example → .env and fill in your keys
    2. Edit WATCHLIST to set your markets
    3. Edit SCHEDULE_TIMES to set when scans run
    4. Run: python swing_trader_alert.py
"""
import os
import re
import time
import logging
import requests
import schedule
from datetime import datetime
from dotenv import load_dotenv
import anthropic

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# CONFIG — edit these to customise
# ─────────────────────────────────────────

# Markets to scan (be specific so Claude can search accurately)
WATCHLIST = [
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "AAPL",
    "NVDA",
    "EUR/USD",
    "Gold (XAUUSD)",
]

# Minimum score to trigger an alert (70 = A grade)
MIN_ALERT_SCORE = 70

# Times to run each day (24h format, UTC)
SCHEDULE_TIMES = ["07:00", "19:00"]

# Delivery method: "telegram" | "email" | "slack" | "discord"
DELIVERY_METHOD = "telegram"

# ─────────────────────────────────────────
# SYSTEM PROMPT (from swing-trader skill)
# ─────────────────────────────────────────

SYSTEM_PROMPT = """
You are an elite swing trader operating across global markets (crypto, equities, forex, commodities), specializing in multi-day to multi-week trades. You use a structured, data-driven scoring system to evaluate every trade.

Your goal is not to find many trades — it is to find the best trades.

CORE IDENTITY:
- You think like a hedge fund swing quant.
- You rely on structured scoring, not intuition.
- You only act when there is clear statistical edge.

TIMEFRAME FOCUS:
- Primary: 4H, Daily, Weekly
- Secondary: 1H for refined entries

TRADE SCORING MODEL (0–100):
Score every trade on these weighted factors:
1. Trend Alignment (0–20): 20=strong HTF alignment, 10=mixed, 0=counter-trend
2. Key Level Quality (0–20): Strength of S/R or supply/demand zone
3. Confluence (0–20): Trend + level + momentum + volume aligning
4. Risk/Reward Profile (0–15): 15=3R+, 10=2R, 5=<2R
5. Momentum & Volume (0–10): Strong expansion = high score
6. Market Structure Clarity (0–10): Clean HH/HL or LH/LL = high
7. Sentiment & Positioning (0–5): Contrarian edge = higher score

SCORE THRESHOLDS:
- 85–100 → A+ (High conviction, prioritize)
- 70–84  → A  (Tradable)
- 60–69  → B  (Optional / smaller size)
- <60    → No Trade

POSITION SIZING:
- 85+   → 1.5–2% risk
- 70–84 → 1% risk
- 60–69 → 0.5% risk
- <60   → 0% (no trade)

OUTPUT FORMAT — use this exact structure for EVERY setup:
- Market: [Asset + timeframe]
- Bias: [Bullish / Bearish / Neutral]
- Setup Type: [Pullback / Breakout / Range Reversal]
- Entry Zone: [Price range]
- Stop Loss: [Level]
- Take Profit: [TP1, TP2, TP3]
- Risk/Reward: [Ratio]
- Time Horizon: [Days / Weeks]

📊 Trade Score: [X/100]
Grade: [A+ / A / B / No Trade]

📊 Score Breakdown:
- Trend Alignment: X/20
- Key Level: X/20
- Confluence: X/20
- Risk/Reward: X/15
- Momentum/Volume: X/10
- Structure: X/10
- Sentiment: X/5

💰 Suggested Risk: [X% of capital]

- Confluence Factors:
  • [Factor 1]
  • [Factor 2]
  • [Factor 3]

- Invalidation: [Clear condition that breaks the setup]
- Reasoning: [Concise, professional explanation]

NO-TRADE RULE: If no setups score above 60, respond with:
"No swing setups with sufficient edge. Stay in cash."

BEHAVIOR RULES:
- Be highly selective. Never inflate scores.
- Prioritize asymmetric opportunities.
- Avoid emotional or narrative-driven decisions.
- If the score is not there, the trade does not exist.
"""

# ─────────────────────────────────────────
# CLAUDE API CALL
# ─────────────────────────────────────────


def run_market_scan(markets: list[str]) -> str:
    """Call Claude with web search to scan markets and score setups."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    market_list = ", ".join(markets)
    user_prompt = f"""
Today is {datetime.utcnow().strftime('%A %d %B %Y, %H:%M UTC')}.

Use web search to gather current price action, technical levels, volume, and market sentiment for the following markets:

{market_list}

For each market:
1. Search for the current price, recent trend, key support/resistance levels, and any notable volume or momentum signals.
2. Score the setup using the full scoring model (0–100).
3. Output the result in the required format.
4. Only include setups scoring 60 or above.

If no market has a setup scoring 60+, state: "No swing setups with sufficient edge. Stay in cash."
"""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": user_prompt}],
    )

    # Extract all text blocks from the response
    full_text = "\n".join(
        block.text for block in response.content if hasattr(block, "text")
    )
    return full_text


# ─────────────────────────────────────────
# SCORE PARSING
# ─────────────────────────────────────────


def extract_scores(analysis: str) -> list[dict]:
    """Parse scores from Claude's response."""
    setups = []
    # Find all "Trade Score: XX/100" occurrences
    matches = re.finditer(r"Trade Score:\s*(\d+)/100", analysis)
    for match in matches:
        score = int(match.group(1))
        # Get surrounding context (300 chars before for market name)
        start = max(0, match.start() - 300)
        context = analysis[start : match.end()]
        market_match = re.search(r"Market:\s*(.+)", context)
        market = market_match.group(1).strip() if market_match else "Unknown"
        setups.append({"market": market, "score": score})
    return setups


# ─────────────────────────────────────────
# DELIVERY METHODS
# ─────────────────────────────────────────


def send_telegram(message: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.error(
            "Telegram credentials missing. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env"
        )
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    # Telegram has a 4096 char limit per message — split if needed
    chunks = [message[i : i + 4000] for i in range(0, len(message), 4000)]
    for chunk in chunks:
        resp = requests.post(
            url, json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"}
        )
        if not resp.ok:
            log.error(f"Telegram send failed: {resp.text}")


def send_slack(message: str):
    webhook = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook:
        log.error("SLACK_WEBHOOK_URL missing from .env")
        return
    resp = requests.post(webhook, json={"text": message})
    if not resp.ok:
        log.error(f"Slack send failed: {resp.text}")


def send_discord(message: str):
    webhook = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook:
        log.error("DISCORD_WEBHOOK_URL missing from .env")
        return
    # Discord limit is 2000 chars
    chunks = [message[i : i + 1900] for i in range(0, len(message), 1900)]
    for chunk in chunks:
        resp = requests.post(webhook, json={"content": chunk})
        if not resp.ok:
            log.error(f"Discord send failed: {resp.text}")


def send_email(message: str):
    """Basic SMTP email via Gmail. Set env vars accordingly."""
    import smtplib
    from email.mime.text import MIMEText

    sender = os.getenv("EMAIL_FROM")
    recipient = os.getenv("EMAIL_TO")
    password = os.getenv("EMAIL_PASSWORD")
    if not all([sender, recipient, password]):
        log.error(
            "Email credentials missing. Set EMAIL_FROM, EMAIL_TO, EMAIL_PASSWORD in .env"
        )
        return
    msg = MIMEText(message)
    msg["Subject"] = (
        f"📊 Swing Trade Alert — {datetime.utcnow().strftime('%d %b %Y %H:%M')} UTC"
    )
    msg["From"] = sender
    msg["To"] = recipient
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, password)
        smtp.sendmail(sender, recipient, msg.as_string())


def deliver(message: str):
    method = DELIVERY_METHOD.lower()
    dispatch = {
        "telegram": send_telegram,
        "slack": send_slack,
        "discord": send_discord,
        "email": send_email,
    }
    fn = dispatch.get(method)
    if fn:
        fn(message)
    else:
        log.error(f"Unknown delivery method: {method}")


# ─────────────────────────────────────────
# MAIN SCAN JOB
# ─────────────────────────────────────────


def run_scan_job():
    log.info("🔍 Starting market scan...")
    timestamp = datetime.utcnow().strftime("%d %b %Y %H:%M UTC")

    try:
        analysis = run_market_scan(WATCHLIST)
    except Exception as e:
        log.error(f"Claude API error: {e}")
        return

    setups = extract_scores(analysis)
    high_conviction = [s for s in setups if s["score"] >= MIN_ALERT_SCORE]

    if not high_conviction:
        log.info(f"No setups above {MIN_ALERT_SCORE}. No alert sent.")
        return

    # Build alert message
    grades = {s["market"]: s["score"] for s in high_conviction}
    summary_lines = [f"• {m}: {sc}/100" for m, sc in grades.items()]
    header = (
        f"📊 *SWING TRADE ALERT*\n"
        f"🕐 {timestamp}\n"
        f"{'─' * 30}\n"
        f"*High-conviction setups found:*\n"
        + "\n".join(summary_lines)
        + f"\n{'─' * 30}\n"
    )
    full_message = header + "\n" + analysis

    deliver(full_message)
    log.info(f"✅ Alert sent. Setups: {[s['market'] for s in high_conviction]}")


# ─────────────────────────────────────────
# SCHEDULER
# ─────────────────────────────────────────


def main():
    log.info("🚀 Swing Trader Alert Bot starting...")
    log.info(f"   Watchlist : {', '.join(WATCHLIST)}")
    log.info(f"   Schedule  : {', '.join(SCHEDULE_TIMES)} UTC")
    log.info(f"   Delivery  : {DELIVERY_METHOD}")
    log.info(f"   Min score : {MIN_ALERT_SCORE}")

    for t in SCHEDULE_TIMES:
        schedule.every().day.at(t).do(run_scan_job)
        log.info(f"   Scheduled scan at {t} UTC")

    # Run once immediately on startup
    run_scan_job()

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
