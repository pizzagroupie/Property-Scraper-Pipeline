"""
Main orchestrator for the property scraper pipeline.
Runs all scrapers, deduplicates against seen listings, and sends new ones to Telegram.
"""
import json
import logging
import sys
import time
from pathlib import Path

from config import SEEN_LISTINGS_FILE, REQUEST_DELAY
import scraper_aucoot
import scraper_historiska
import scraper_inigo
import scraper_wrede
import scraper_cowcamo
import scraper_fantasticfrank
import scraper_uchijapan
import telegram_sender

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def load_seen_listings() -> set[str]:
    """Load previously seen listing IDs from JSON file."""
    path = Path(SEEN_LISTINGS_FILE)
    if path.exists():
        try:
            with open(path, "r") as f:
                data = json.load(f)
                return set(data.get("seen", []))
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Could not parse {SEEN_LISTINGS_FILE}: {e}")
    return set()


def save_seen_listings(seen: set[str]) -> None:
    """Save seen listing IDs to JSON file."""
    with open(SEEN_LISTINGS_FILE, "w") as f:
        json.dump({"seen": sorted(seen)}, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved {len(seen)} seen listings to {SEEN_LISTINGS_FILE}")


def main():
    logger.info("=" * 60)
    logger.info("🏠 Property Scraper Pipeline — Starting")
    logger.info("=" * 60)

    # Load previously seen listings
    seen = load_seen_listings()
    logger.info(f"Loaded {len(seen)} previously seen listings")

    # Run all scrapers
    all_listings = []
    source_counts = {}

    scrapers = [
        ("Aucoot", scraper_aucoot.scrape_listings),
        ("Historiska Hem", scraper_historiska.scrape_listings),
        ("Inigo", scraper_inigo.scrape_listings),
        ("Wrede", scraper_wrede.scrape_listings),
        ("Cowcamo", scraper_cowcamo.scrape_listings),
        ("Fantastic Frank", scraper_fantasticfrank.scrape_listings),
        ("Uchi Japan", scraper_uchijapan.scrape_listings),
    ]

    for name, scrape_fn in scrapers:
        logger.info(f"\n{'─' * 40}")
        logger.info(f"Scraping {name}...")
        try:
            listings = scrape_fn()
            all_listings.extend(listings)
            source_counts[name] = len(listings)
            logger.info(f"✓ {name}: {len(listings)} listings found")
        except Exception as e:
            logger.error(f"✗ {name} scraper crashed: {e}")
            source_counts[name] = 0

    logger.info(f"\n{'─' * 40}")
    logger.info(f"Total listings scraped: {len(all_listings)}")

    # Filter out already-seen listings
    new_listings = []
    for listing in all_listings:
        uid = listing.unique_id()
        if uid not in seen:
            new_listings.append(listing)
            seen.add(uid)

    logger.info(f"New listings: {len(new_listings)}")

    # Send new listings to Telegram
    sent_count = 0
    for listing in new_listings:
        success = telegram_sender.send_listing(listing)
        if success:
            sent_count += 1
        time.sleep(1)  # Rate limit Telegram API

    # Send summary
    telegram_sender.send_summary(
        total=len(all_listings),
        new=len(new_listings),
        sources=source_counts,
    )

    # Save updated seen listings
    save_seen_listings(seen)

    logger.info(f"\n{'=' * 60}")
    logger.info(f"✅ Done! Sent {sent_count}/{len(new_listings)} new listings")
    logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    main()
