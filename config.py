"""
Configuration for property scraper pipeline.
Update exchange rates manually as needed.
"""

# === Telegram Bot Config ===
# These should be set as GitHub Actions secrets in production.
# For local testing, you can hardcode them here temporarily.
import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1031987552")

# === Exchange Rates (manual update) ===
# Last updated: 2026-03-14
# 所有汇率均为 1 外币 = X 人民币
EXCHANGE_RATES = {
    "GBP": 9.2,    # 英镑
    "EUR": 7.7,    # 欧元 — Fantastic Frank (德/西/葡/丹麦等)
    "USD": 7.1,    # 美元 — Uchi Japan 有时标 USD
    "SEK": 0.68,   # 瑞典克朗 — Historiska Hem, Fantastic Frank Stockholm
    "DKK": 1.03,   # 丹麦克朗 — Fantastic Frank Copenhagen
    "AUD": 4.6,    # 澳元
    "JPY": 0.048,  # 日元 — Uchi Japan
}

# === Scraper Settings ===
REQUEST_TIMEOUT = 30  # seconds
REQUEST_DELAY = 2     # seconds between requests (be polite)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# === Data File ===
SEEN_LISTINGS_FILE = "seen_listings.json"

# === Max images to include per listing in Telegram message ===
MAX_IMAGES_PER_LISTING = 5
