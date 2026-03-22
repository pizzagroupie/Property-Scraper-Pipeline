"""
Scraper for Fantastic Frank (fantasticfrank.com) — Global design-led properties.
Covers Stockholm, Berlin, Lisbon, Copenhagen, Barcelona, and more.

Uses a Session with full browser headers and cookie persistence to bypass blocking.
"""
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from config import REQUEST_TIMEOUT, REQUEST_DELAY, EXCHANGE_RATES
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


def _create_session() -> requests.Session:
    """Create a requests Session that mimics a real browser."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    })
    return session


def scrape_listings() -> list[PropertyListing]:
    """Scrape listings from Fantastic Frank across multiple cities."""
    all_listings = []
    session = _create_session()

    # First visit the homepage to get cookies
    try:
        logger.info("Visiting Fantastic Frank homepage for cookies...")
        resp = session.get(f"{BASE_URL}/en/", timeout=REQUEST_TIMEOUT, allow_redirects=True)
        logger.info(f"  Homepage status: {resp.status_code}, cookies: {len(session.cookies)}")
        time.sleep(REQUEST_DELAY)
    except requests.RequestException as e:
        logger.warning(f"  Homepage fetch failed: {e}, continuing anyway...")

    for city_info in CITIES:
        time.sleep(REQUEST_DELAY)
        try:
            city_listings = _scrape_city(session, city_info)
            all_listings.extend(city_listings)
            if city_listings:
                logger.info(f"  ✓ Fantastic Frank {city_info['city']}: {len(city_listings)} listings")
            else:
                logger.warning(f"  ⚠ Fantastic Frank {city_info['city']}: 0 listings")
        except Exception as e:
            logger.error(f"  ✗ Fantastic Frank {city_info['city']}: {e}")

    logger.info(f"Total Fantastic Frank listings: {len(all_listings)}")
    return all_listings


def _scrape_city(session: requests.Session, city_info: dict) -> list[PropertyListing]:
    """Scrape listings for a single Fantastic Frank city."""
    listings = []

    # Try the for-sale page
    url = f"{BASE_URL}/en/{city_info['slug']}/for-sale/"
    # Set referer as if navigating from the city page
    session.headers["Referer"] = f"{BASE_URL}/en/{city_info['slug']}/"
    session.headers["Sec-Fetch-Site"] = "same-origin"

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        logger.info(f"  {city_info['city']} for-sale page: status {resp.status_code}, length {len(resp.text)}")
        if resp.status_code != 200:
            return []
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Find property links — format: /en/{city}/property/{slug}/
    property_links = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if f"/en/{city_info['slug']}/property/" in href:
            full_url = href if href.startswith("http") else BASE_URL + href
            property_links.add(full_url.rstrip("/") + "/")

    logger.info(f"  {city_info['city']}: found {len(property_links)} property links")

    if not property_links:
        # Log some HTML for debugging
        text_preview = soup.get_text(" ", strip=True)[:300]
        logger.info(f"  Page text preview: {text_preview}")
        return []

    # Parse cards from the listing page
    for link in sorted(property_links):
        listing = _parse_from_page(link, soup, city_info)
        if listing:
            listings.append(listing)

    # If card parsing didn't work, try detail pages
    if not listings and property_links:
        for link in sorted(property_links)[:10]:
            time.sleep(REQUEST_DELAY)
            listing = _scrape_detail(session, link, city_info)
            if listing:
                listings.append(listing)

    return listings


def _parse_from_page(property_url: str, soup: BeautifulSoup, city_info: dict) -> PropertyListing | None:
    """Try to parse listing data from the for-sale page card for a given property URL."""
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_href = href if href.startswith("http") else BASE_URL + href
        if full_href.rstrip("/") == property_url.rstrip("/"):
            card_text = a_tag.get_text(" ", strip=True)
            if len(card_text) < 5:
                continue
            return _parse_card_text(property_url, card_text, city_info)
    return None


def _parse_card_text(url: str, card_text: str, city_info: dict) -> PropertyListing | None:
    """Parse a Fantastic Frank card text into a PropertyListing."""
    currency = city_info["currency"]

    # Extract address
    address = ""
    segments = [s.strip() for s in re.split(r'[·\n]', card_text) if s.strip()]
    if segments:
        address = segments[0]

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
    area_match = re.search(r'([\d.,]+)\s*m²', card_text, re.I)
    if not area_match:
        area_match = re.search(r'[Ii]nterior\s*([\d.,]+)\s*m', card_text)
    if area_match:
        try:
            area_sqm = float(area_match.group(1).replace(",", "."))
        except ValueError:
            pass

    # Extract price
    price_amount = None
    price_raw = ""
    if currency in ("SEK", "DKK"):
        price_match = re.search(r'([\d\s.]+)\s*kr', card_text, re.I)
        if price_match:
            price_str = price_match.group(1).replace(" ", "").replace(".", "")
            try:
                price_amount = float(price_str)
                price_raw = f"{int(price_amount):,} {currency}".replace(",", " ")
            except ValueError:
                pass
    elif currency == "EUR":
        price_match = re.search(r'€\s*([\d\s,.]+)|(\d[\d\s,.]+)\s*€', card_text)
        if price_match:
            price_str = (price_match.group(1) or price_match.group(2))
            price_str = price_str.replace(" ", "").replace(".", "").replace(",", "")
            try:
                price_amount = float(price_str)
                price_raw = f"€{int(price_amount):,}"
            except ValueError:
                pass

    price_cny = price_amount * EXCHANGE_RATES.get(currency, 1) if price_amount else None

    # Title
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


def _scrape_detail(session: requests.Session, url: str, city_info: dict) -> PropertyListing | None:
    """Scrape a single Fantastic Frank detail page."""
    session.headers["Referer"] = f"{BASE_URL}/en/{city_info['slug']}/for-sale/"

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code != 200:
            logger.warning(f"  Detail page {url}: status {resp.status_code}")
            return None
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    currency = city_info["currency"]

    # Title
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        slug = url.rstrip("/").split("/")[-1]
        title = slug.replace("-", " ").title()

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
    area_match = re.search(r'([\d.,]+)\s*m²', text)
    if area_match:
        try:
            area_sqm = float(area_match.group(1).replace(",", "."))
        except ValueError:
            pass

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
        if src and any(d in src for d in ["fantasticfrank", "cloudinary", "imgix"]):
            if any(ext in src.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                if src not in images:
                    images.append(src)

    # Description
    description = None
    skip_words = ["cookie", "showroom", "welcome to", "whether you", "our approach"]
    for p in soup.find_all("p"):
        txt = p.get_text(strip=True)
        if len(txt) > 100 and not any(skip in txt.lower() for skip in skip_words):
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
