# Trading Alert Bot

A production-ready Python trading alert system that monitors **all available instruments** on Binance and Markets.com, runs technical analysis + sentiment scoring, and sends real-time alerts via Telegram and/or WhatsApp.

**ALERT-ONLY** — this bot never places, modifies, or cancels any trade or order.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Get a Telegram Bot Token](#get-a-telegram-bot-token)
4. [Get Your Telegram Chat ID](#get-your-telegram-chat-id)
5. [Set Up Twilio WhatsApp Sandbox](#set-up-twilio-whatsapp-sandbox)
6. [Get a Binance API Key](#get-a-binance-api-key)
7. [Get a Markets.com API Key](#get-a-marketscom-api-key)
8. [Get News API Keys](#get-news-api-keys)
9. [Configure config.yaml](#configure-configyaml)
10. [Running the Bot](#running-the-bot)
11. [Dry-Run Mode](#dry-run-mode)
12. [Run as a Background Service](#run-as-a-background-service)
13. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- **Python 3.11+** (3.12 recommended)
- **pip** (comes with Python)
- A Linux, macOS, or Windows machine with internet access
- API keys for at least one exchange and one notification channel

---

## Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd trading-alert-bot

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env with your API keys
nano .env  # or use any text editor
```

> **Note:** `torch` is a large package (~2 GB). If you don't need FinBERT sentiment analysis, the bot will automatically fall back to VADER (much lighter). You can skip torch by removing it from requirements.txt.

---

## Get a Telegram Bot Token

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Follow the prompts to choose a name and username
4. BotFather will give you a token like: `110201543:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw`
5. Copy this token to `TELEGRAM_BOT_TOKEN` in your `.env` file

---

## Get Your Telegram Chat ID

1. Start a chat with your new bot (search its username and press "Start")
2. Send any message to the bot
3. Open this URL in your browser (replace `YOUR_TOKEN`):
   ```
   https://api.telegram.org/botYOUR_TOKEN/getUpdates
   ```
4. Look for `"chat":{"id":123456789}` in the response
5. Copy this number to `TELEGRAM_CHAT_ID` in your `.env` file

For group chats, the ID will be negative (e.g., `-1001234567890`).

---

## Set Up Twilio WhatsApp Sandbox

1. Sign up at [twilio.com](https://www.twilio.com/)
2. Go to **Messaging > Try it out > Send a WhatsApp message**
3. Follow the instructions to join the sandbox (send a specific message to the Twilio WhatsApp number)
4. Note the sandbox number (e.g., `whatsapp:+14155238886`)
5. Copy to your `.env`:
   - `TWILIO_ACCOUNT_SID` — from Twilio Console dashboard
   - `TWILIO_AUTH_TOKEN` — from Twilio Console dashboard
   - `TWILIO_WHATSAPP_FROM` — the sandbox number (e.g., `whatsapp:+14155238886`)
   - `TWILIO_WHATSAPP_TO` — your WhatsApp number (e.g., `whatsapp:+1234567890`)

---

## Get a Binance API Key

1. Log in to [binance.com](https://www.binance.com/)
2. Go to **Account > API Management**
3. Create a new API key
4. **Important:** Enable only **Read** permissions. Do NOT enable trading or withdrawals.
5. Copy to `.env`:
   - `BINANCE_API_KEY`
   - `BINANCE_API_SECRET`

> A read-only key is sufficient. This bot never places trades.

---

## Get a Markets.com API Key

1. Log in to [markets.com](https://www.markets.com/)
2. Markets.com uses the **cTrader Open API**
3. Check their API documentation at: https://help.markets.com/en/articles/api
4. Generate API credentials from your account settings
5. Copy to `.env`:
   - `MARKETS_COM_API_KEY`
   - `MARKETS_COM_API_SECRET`
   - `MARKETS_COM_ACCOUNT_ID`

> If the Markets.com API is unavailable, the bot automatically falls back to yfinance for price data on those instruments.

---

## Get News API Keys

All of these have free tiers:

### NewsAPI
1. Sign up at [newsapi.org](https://newsapi.org/)
2. Get your API key from the dashboard
3. Copy to `NEWSAPI_KEY` in `.env`

### Finnhub
1. Sign up at [finnhub.io](https://finnhub.io/)
2. Get your free API key
3. Copy to `FINNHUB_API_KEY` in `.env`

### Alpha Vantage
1. Sign up at [alphavantage.co](https://www.alphavantage.co/support/#api-key)
2. Request a free API key
3. Copy to `ALPHA_VANTAGE_KEY` in `.env`

### CryptoPanic
1. Sign up at [cryptopanic.com](https://cryptopanic.com/developers/api/)
2. Get your API auth token
3. Copy to `CRYPTOPANIC_API_KEY` in `.env`

---

## Configure config.yaml

The `config.yaml` file controls all bot behavior. Key sections:

### `exchanges`
- `binance.enabled` — Enable/disable Binance monitoring
- `binance.quote_currencies` — Which quote currencies to include (USDT, BTC, ETH, BNB)
- `binance.min_24h_volume_usd` — Minimum 24h volume filter (default: $5M)
- `markets_com.enabled` — Enable/disable Markets.com
- `markets_com.poll_interval_sec` — How often to poll (default: 10s)

### `signals`
- `spike` — Price spike detection thresholds
- `rsi` — RSI period and overbought/oversold levels
- `macd` — MACD fast/slow/signal periods
- `bollinger` — Bollinger Band period and standard deviation
- `ema_crossover` — EMA fast/slow periods
- `support_resistance` — S/R lookback periods
- `sentiment` — News polling interval, score thresholds, sources

### `confidence`
- `min_confidence` — Minimum composite score to trigger alert (0-100)
- `confidence_weights` — Weight of each sub-score

### `sl_tp`
- `atr_period` — ATR calculation period
- `atr_multiplier_sl` — ATR multiplier for stop loss
- `rr_tp1/tp2/tp3` — Risk-reward ratios for take profit levels

### `notifications`
- `telegram.enabled` — Enable/disable Telegram alerts
- `whatsapp.enabled` — Enable/disable WhatsApp alerts

### `rate_limiting`
- `dedupe_window_min` — Suppress duplicate alerts within this window
- `max_alerts_per_hour` — Global alert cap
- `max_alerts_per_asset_per_hour` — Per-asset alert cap

### `asset_class_overrides`
- Override signal thresholds per asset class (crypto, forex, commodity, index, stock)

---

## Running the Bot

```bash
# Activate virtual environment
source venv/bin/activate

# Run the bot
python main.py
```

---

## Dry-Run Mode

Test without sending any messages:

```bash
python main.py --dry-run
```

Additional flags:

```bash
# Debug logging
python main.py --dry-run --verbose

# Monitor a single asset
python main.py --dry-run --asset BTCUSDT

# Custom config path
python main.py --config /path/to/config.yaml
```

---

## Run as a Background Service

### Using systemd (Linux)

Create `/etc/systemd/system/trading-alert-bot.service`:

```ini
[Unit]
Description=Trading Alert Bot
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/trading-alert-bot
ExecStart=/path/to/trading-alert-bot/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-alert-bot
sudo systemctl start trading-alert-bot

# Check status
sudo systemctl status trading-alert-bot

# View logs
journalctl -u trading-alert-bot -f
```

### Using launchd (macOS)

Create `~/Library/LaunchAgents/com.trading-alert-bot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.trading-alert-bot</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/venv/bin/python</string>
        <string>/path/to/trading-alert-bot/main.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>/path/to/trading-alert-bot</string>
</dict>
</plist>
```

Then:

```bash
launchctl load ~/Library/LaunchAgents/com.trading-alert-bot.plist
```

---

## Troubleshooting

### "No symbols discovered"
- Check that at least one exchange is enabled in `config.yaml`
- Verify your Binance API key has read permissions
- For Markets.com, check if the API key is valid or if the fallback to yfinance is working

### "Telegram send failed"
- Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`
- Make sure you've started a conversation with your bot first
- Check that the bot hasn't been blocked

### "FinBERT unavailable, falling back to VADER"
- This is normal if `torch` and `transformers` aren't installed
- VADER is lighter and faster but less accurate for financial text
- To use FinBERT: `pip install torch transformers`

### "Markets.com auth failed"
- The Markets.com API uses cTrader Open API protocol
- Double-check your API key and secret
- The bot will automatically fall back to yfinance for price data

### High memory usage
- FinBERT + torch can use 2-4 GB RAM
- Set `use_finbert: false` in `config.yaml` to use VADER instead
- Reduce the number of monitored instruments by increasing `min_24h_volume_usd`

### Rate limiting
- If you're getting "rate limit hit" messages, increase `max_alerts_per_hour` in `config.yaml`
- Or increase `min_confidence` to reduce the number of triggered alerts
- Adjust `dedupe_window_min` to control how often the same signal can re-trigger

### WebSocket disconnections
- The bot automatically reconnects with exponential backoff
- Check your internet connection if disconnects are frequent
- Some firewalls/proxies may block WebSocket connections
