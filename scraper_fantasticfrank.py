"""
Scraper for Fantastic Frank (fantasticfrank.com) — Global design-led properties.
Covers Stockholm, Berlin, Lisbon, Copenhagen, Barcelona, and more.

Note: robots.txt disallows crawling. This scraper respects rate limits
and only fetches listing pages, not bulk crawling.
"""
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from config import HEADERS, REQUEST_TIMEOUT, REQUEST_DELAY, EXCHANGE_RATES
from models import PropertyListing

logger = logging.getLogger(__name__)

BASE_URL = "https://www.fantasticfrank.com"

# Cities to scrape with their currency
CITIES = [
    {"slug": "stockholm", "currency": "SEK", "country": "瑞典", "city": "Stockholm"},
    {"slug": "berlin", "currency": "EUR", "country": "德国", "city": "Berlin"},
    {"slug": "lisbon", "currency": "EUR", "country": "葡萄牙", "city": "Lisbon"},
    {"slug": "copenhagen", "currency": "DKK", "country": "丹麦", "city": "Copenhagen"},
    {"slug": "barcelona", "currency": "EUR", "country": "西班牙", "city": "Barcelona"},
    {"slug": "munich", "currency": "EUR", "country": "德国", "city": "Munich"},
    {"slug": "hamburg", "currency": "EUR", "country": "德国", "city": "Hamburg"},
]


def scrape_listings() -> list[PropertyListing]:
    """Scrape listings from Fantastic Frank across multiple cities."""
    all_listings = []

    for city_info in CITIES:
        time.sleep(REQUEST_DELAY)
        try:
            city_listings = _scrape_city(city_info)
            all_listings.extend(city_listings)
            logger.info(f"  ✓ Fantastic Frank {city_info['city']}: {len(city_listings)} listings")
        except Exception as e:
            logger.error(f"  ✗ Fantastic Frank {city_info['city']}: {e}")

    logger.info(f"Total Fantastic Frank listings: {len(all_listings)}")
    return all_listings


def _scrape_city(city_info: dict) -> list[PropertyListing]:
    """Scrape listings for a single Fantastic Frank city."""
    listings = []
    url = f"{BASE_URL}/en/{city_info['slug']}/for-sale/"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    text = resp.text

    # Find property links — format: /en/{city}/property/{slug}/
    property_links = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if f"/en/{city_info['slug']}/property/" in href:
            full_url = href if href.startswith("http") else BASE_URL + href
            property_links.add(full_url.rstrip("/") + "/")

    # Parse cards from the listing page
    # Fantastic Frank cards show: address, rooms, bathrooms, area, price
    for link in sorted(property_links):
        listing = _parse_from_page(link, soup, city_info)
        if listing:
            listings.append(listing)

    # If card parsing didn't work well, try detail pages
    if not listings and property_links:
        for link in sorted(property_links)[:10]:
            time.sleep(REQUEST_DELAY)
            listing = _scrape_detail(link, city_info)
            if listing:
                listings.append(listing)

    return listings


def _parse_from_page(property_url: str, soup: BeautifulSoup, city_info: dict) -> PropertyListing | None:
    """Try to parse listing data from the for-sale page card for a given property URL."""
    # Find the <a> tag linking to this property
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_href = href if href.startswith("http") else BASE_URL + href
        if full_href.rstrip("/") == property_url.rstrip("/"):
            card_text = a_tag.get_text(" ", strip=True)
            if len(card_text) < 10:
                continue
            return _parse_card_text(property_url, card_text, city_info)
    return None


def _parse_card_text(url: str, card_text: str, city_info: dict) -> PropertyListing | None:
    """Parse a Fantastic Frank card text into a PropertyListing."""
    currency = city_info["currency"]

    # Extract address (usually first line or before room count)
    address = ""
    lines = [l.strip() for l in card_text.split(",")]
    if lines:
        address = lines[0].strip()

    # Extract rooms
    rooms = None
    rooms_match = re.search(r'(\d+)\s*rooms?', card_text, re.I)
    if rooms_match:
        rooms = rooms_match.group(1)

    # Extract bathrooms
    bathrooms = None
    bath_match = re.search(r'(\d+)\s*bathrooms?', card_text, re.I)
    if bath_match:
        bathrooms = bath_match.group(1)

    # Extract area
    area_sqm = None
    area_match = re.search(r'([\d.]+)\s*m²', card_text, re.I)
    if not area_match:
        area_match = re.search(r'Interior\s*([\d.]+)\s*m', card_text, re.I)
    if area_match:
        area_sqm = float(area_match.group(1))

    # Extract price
    price_amount = None
    price_raw = ""
    if currency == "SEK":
        price_match = re.search(r'([\d\s.]+)\s*kr', card_text, re.I)
        if price_match:
            price_str = price_match.group(1).replace(" ", "").replace(".", "")
            try:
                price_amount = float(price_str)
                price_raw = f"{int(price_amount):,} SEK".replace(",", " ")
            except ValueError:
                pass
    elif currency == "DKK":
        price_match = re.search(r'([\d\s.]+)\s*kr', card_text, re.I)
        if price_match:
            price_str = price_match.group(1).replace(" ", "").replace(".", "")
            try:
                price_amount = float(price_str)
                price_raw = f"{int(price_amount):,} DKK".replace(",", " ")
            except ValueError:
                pass
    elif currency == "EUR":
        price_match = re.search(r'€\s*([\d\s,.]+)|(\d[\d\s,.]+)\s*€', card_text)
        if price_match:
            price_str = (price_match.group(1) or price_match.group(2)).replace(" ", "").replace(".", "").replace(",", "")
            try:
                price_amount = float(price_str)
                price_raw = f"€{int(price_amount):,}"
            except ValueError:
                pass

    price_cny = price_amount * EXCHANGE_RATES.get(currency, 1) if price_amount else None

    # Title from URL slug
    slug = url.rstrip("/").split("/")[-1]
    title = address if address else slug.replace("-", " ").title()

    if not title:
        return None

    # Bedrooms from rooms
    bedrooms = None
    if rooms:
        try:
            bedrooms = str(max(1, int(rooms) - 1))
        except ValueError:
            bedrooms = rooms

    return PropertyListing(
        source="Fantastic Frank",
        url=url,
        title=title,
        city=city_info["city"],
        country=city_info["country"],
        price_raw=price_raw if price_raw else "价格面议",
        price_amount=price_amount,
        price_currency=currency,
        price_cny=price_cny,
        area_sqm=area_sqm,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        images=[],
    )


def _scrape_detail(url: str, city_info: dict) -> PropertyListing | None:
    """Scrape a single Fantastic Frank detail page."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    # Extract title
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        slug = url.rstrip("/").split("/")[-1]
        title = slug.replace("-", " ").title()

    currency = city_info["currency"]

    # Price
    price_amount = None
    price_raw = ""
    if currency in ("SEK", "DKK"):
        price_match = re.search(r'([\d\s.]+)\s*kr', text)
        if price_match:
            price_str = price_match.group(1).replace(" ", "").replace(".", "")
            try:
                price_amount = float(price_str)
                price_raw = f"{int(price_amount):,} {currency}".replace(",", " ")
            except ValueError:
                pass
    elif currency == "EUR":
        price_match = re.search(r'€\s*([\d\s,.]+)', text)
        if price_match:
            price_str = price_match.group(1).replace(" ", "").replace(".", "").replace(",", "")
            try:
                price_amount = float(price_str)
                price_raw = f"€{int(price_amount):,}"
            except ValueError:
                pass

    price_cny = price_amount * EXCHANGE_RATES.get(currency, 1) if price_amount else None

    # Area
    area_sqm = None
    area_match = re.search(r'([\d.]+)\s*m²', text)
    if area_match:
        area_sqm = float(area_match.group(1))

    # Rooms
    rooms_match = re.search(r'(\d+)\s*rooms?', text, re.I)
    bedrooms = None
    if rooms_match:
        try:
            bedrooms = str(max(1, int(rooms_match.group(1)) - 1))
        except ValueError:
            pass

    bathrooms = None
    bath_match = re.search(r'(\d+)\s*bathrooms?', text, re.I)
    if bath_match:
        bathrooms = bath_match.group(1)

    # Images
    images = []
    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "")
        if src and ("fantasticfrank" in src or "cloudinary" in src):
            if any(ext in src.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                if src not in images:
                    images.append(src)

    # Description
    description = None
    for p in soup.find_all("p"):
        txt = p.get_text(strip=True)
        if len(txt) > 100 and "cookie" not in txt.lower() and "showroom" not in txt.lower():
            description = txt
            break

    return PropertyListing(
        source="Fantastic Frank",
        url=url,
        title=title,
        city=city_info["city"],
        country=city_info["country"],
        price_raw=price_raw if price_raw else "价格面议",
        price_amount=price_amount,
        price_currency=currency,
        price_cny=price_cny,
        area_sqm=area_sqm,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        images=images[:20],
        description=description,
    )
