"""
Scraper for Wrede (wrede.se) — Swedish premium properties.
Covers Stockholm, Skåne, and international (France, Spain).
"""
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from config import HEADERS, REQUEST_TIMEOUT, REQUEST_DELAY, EXCHANGE_RATES
from models import PropertyListing

logger = logging.getLogger(__name__)

BASE_URL = "https://www.wrede.se"
LISTING_URL = f"{BASE_URL}/en/sverige/"


def scrape_listings() -> list[PropertyListing]:
    """Scrape all current listings from Wrede Sweden page."""
    listings = []

    logger.info("Fetching Wrede listing page...")
    try:
        resp = requests.get(LISTING_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch Wrede listings page: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Find property cards — each is a link to /en/objekt/{id}/{slug}/
    property_links = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "/en/objekt/" in href:
            full_url = href if href.startswith("http") else BASE_URL + href
            # Extract card-level data
            card_text = a_tag.get_text(" ", strip=True)
            if full_url not in [p[0] for p in property_links]:
                property_links.append((full_url.rstrip("/") + "/", card_text))

    logger.info(f"Found {len(property_links)} property links on Wrede")

    # Parse listing data from the card text directly (detail pages need JS)
    # Card format: "Title \n Area \n Address \n Size / Rooms \n Price"
    for url, card_text in property_links:
        try:
            listing = _parse_card(url, card_text)
            if listing:
                listings.append(listing)
                logger.info(f"  ✓ {listing.title} — {listing.price_raw}")
        except Exception as e:
            logger.error(f"  ✗ Failed to parse {url}: {e}")

    # Also try fetching detail pages for richer data
    for i, listing in enumerate(listings):
        if i >= 5:  # Limit detail fetches to avoid rate limiting
            break
        time.sleep(REQUEST_DELAY)
        _enrich_from_detail(listing)

    return listings


def _parse_card(url: str, card_text: str) -> PropertyListing | None:
    """Parse listing data from a Wrede card's text content."""
    if not card_text.strip():
        return None

    # Extract area (sqm)
    area_sqm = None
    area_match = re.search(r'(\d[\d\s]*)\s*(?:sq\s*m|sqm|square meters)', card_text, re.I)
    if area_match:
        area_sqm = float(area_match.group(1).replace(" ", ""))

    # Extract rooms
    rooms = None
    rooms_match = re.search(r'(\d+)\s*rooms?', card_text, re.I)
    if rooms_match:
        rooms = rooms_match.group(1)

    # Extract price (SEK)
    price_raw = ""
    price_amount = None
    price_match = re.search(r'([\d\s]+)\s*SEK', card_text, re.I)
    if not price_match:
        price_match = re.search(r'([\d\s]+)\s*kr', card_text, re.I)
    if price_match:
        price_str = price_match.group(1).replace(" ", "").strip()
        try:
            price_amount = float(price_str)
            if price_amount > 0:
                price_raw = f"{int(price_amount):,} SEK".replace(",", " ")
        except ValueError:
            pass

    # Extract title and area from URL slug
    slug = url.rstrip("/").split("/")[-1]
    title_from_slug = slug.replace("-", " ").title()

    # Extract area name — usually the first capitalized word(s) in card
    lines = [l.strip() for l in card_text.split("\n") if l.strip()]
    area_name = lines[0] if lines else ""
    address = lines[1] if len(lines) > 1 else title_from_slug

    title = address if address else title_from_slug
    city = f"{area_name}, Stockholm" if area_name else "Stockholm"

    # Skip if no meaningful data
    if not title or title == title_from_slug and not price_amount and not area_sqm:
        return None

    # Convert price
    price_cny = price_amount * EXCHANGE_RATES.get("SEK", 0.68) if price_amount else None

    # Bedrooms estimate from rooms (Swedish system: rooms - 1 ≈ bedrooms)
    bedrooms = None
    if rooms:
        try:
            rooms_int = int(rooms)
            bedrooms_num = max(1, rooms_int - 1)
            bedrooms = f"{bedrooms_num}（{rooms} rum）"
        except ValueError:
            bedrooms = rooms

    return PropertyListing(
        source="Wrede",
        url=url,
        title=title,
        city=city,
        country="瑞典",
        price_raw=price_raw if price_raw else "价格面议",
        price_amount=price_amount,
        price_currency="SEK",
        price_cny=price_cny,
        area_sqm=area_sqm,
        bedrooms=bedrooms,
        property_type=None,
        year_built=None,
        images=[],
        description=None,
    )


def _enrich_from_detail(listing: PropertyListing) -> None:
    """Try to fetch detail page for additional data (images, description)."""
    try:
        resp = requests.get(listing.url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        return

    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract images
    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "")
        if src and ("wrede.se" in src or "cloudinary" in src or "cdn" in src):
            if any(ext in src.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                if src not in listing.images and len(listing.images) < 20:
                    listing.images.append(src)

    # Extract description
    for p in soup.find_all("p"):
        txt = p.get_text(strip=True)
        if len(txt) > 100 and "cookie" not in txt.lower():
            listing.description = txt
            break
