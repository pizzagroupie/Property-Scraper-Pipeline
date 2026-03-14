"""
Telegram Bot message sender for property listings.
Sends formatted messages with property data to specified chat.
"""
import logging
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from models import PropertyListing

logger = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_listing(listing: PropertyListing) -> bool:
    """Send a single property listing to Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        return False

    message = listing.to_telegram_message()

    # Telegram has a 4096 char limit for messages
    if len(message) > 4000:
        message = message[:4000] + "\n\\.\\.\\."

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": False,
    }

    try:
        resp = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=30)
        if resp.status_code == 200:
            logger.info(f"  📤 Sent to Telegram: {listing.title}")
            return True
        else:
            logger.error(f"  Telegram API error {resp.status_code}: {resp.text}")
            # If MarkdownV2 fails, try plain text fallback
            return _send_plain_text(listing)
    except requests.RequestException as e:
        logger.error(f"  Telegram send failed: {e}")
        return False


def _send_plain_text(listing: PropertyListing) -> bool:
    """Fallback: send as plain text if MarkdownV2 fails."""
    lines = []
    lines.append(f"🏠 {listing.title}")
    lines.append(f"📍 {listing.city}, {listing.country}")
    lines.append(f"💰 {listing.format_price_cny()}")
    lines.append(f"📐 面积: {listing.format_area()}")

    if listing.bedrooms:
        lines.append(f"🛏 {listing.bedrooms}卧")
    if listing.bathrooms:
        lines.append(f"🚿 {listing.bathrooms}卫")
    if listing.property_type:
        lines.append(f"🏡 类型: {listing.property_type}")
    if listing.year_built:
        lines.append(f"🏛 建筑年代: {listing.year_built}")
    if listing.architect:
        lines.append(f"✏️ 建筑师: {listing.architect}")
    if listing.tenure:
        lines.append(f"📜 产权: {listing.tenure}")

    if listing.description:
        snippet = listing.description[:200]
        if len(listing.description) > 200:
            snippet += "..."
        lines.append(f"\n📝 {snippet}")

    if listing.floorplan_url:
        lines.append(f"\n📋 户型图: {listing.floorplan_url}")

    if listing.images:
        lines.append(f"\n📸 共{len(listing.images)}张图片")
        for i, img in enumerate(listing.images[:5]):
            lines.append(f"  {i+1}. {img}")

    lines.append(f"\n🔗 原文: {listing.url}")
    lines.append(f"📌 来源: {listing.source}")

    message = "\n".join(lines)

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message[:4096],
        "disable_web_page_preview": False,
    }

    try:
        resp = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=30)
        if resp.status_code == 200:
            logger.info(f"  📤 Sent (plain text): {listing.title}")
            return True
        else:
            logger.error(f"  Plain text also failed {resp.status_code}: {resp.text}")
            return False
    except requests.RequestException as e:
        logger.error(f"  Plain text send failed: {e}")
        return False


def send_summary(total: int, new: int, sources: dict[str, int]) -> bool:
    """Send a summary message after scraping run."""
    if not TELEGRAM_BOT_TOKEN:
        return False

    lines = [
        "📊 *房源爬取日报*",
        "",
        f"总房源数: {total}",
        f"新增房源: {new}",
        "",
        "各来源明细:",
    ]
    for source, count in sources.items():
        lines.append(f"  • {source}: {count}条")

    if new == 0:
        lines.append("\n今日无新增房源 ☕")

    message = "\n".join(lines)

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }

    try:
        resp = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=30)
        return resp.status_code == 200
    except requests.RequestException:
        return False
