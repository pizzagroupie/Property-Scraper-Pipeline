"""
Scraper for Uchi Japan (uchijapan.com) — Japan resort real estate.

Uchi Japan uses Algolia for search. We attempt to:
1. Fetch the properties page and extract Algolia config (appId, apiKey)
2. Query Algolia API directly for structured JSON data
3. Fallback to HTML parsing if Algolia approach fails
"""
import re
import json
import time
import logging
import requests
from bs4 import BeautifulSoup
from config import HEADERS, REQUEST_TIMEOUT, REQUEST_DELAY, EXCHANGE_RATES
from models import PropertyListing

logger = logging.getLogger(__name__)

BASE_URL = "https://uchijapan.com"
LISTING_URL = f"{BASE_URL}/properties"
HOUSES_URL = f"{LISTING_URL}?search%5BrefinementList%5D%5BpropertyType%5D%5B0%5D=Houses&search%5BsortBy%5D=date_desc"


def scrape_listings() -> list[PropertyListing]:
    """Scrape listings from Uchi Japan."""
    listings = []

    # Try the Algolia approach first
    algolia_listings = _try_algolia_approach()
    if algolia_listings:
        logger.info(f"Got {len(algolia_listings)} listings via Algolia API")
        return algolia_listings

    # Fallback: parse the HTML page
    logger.info("Algolia approach failed, falling back to HTML parsing...")
    return _scrape_html()


def _try_algolia_approach() -> list[PropertyListing]:
    """Try to find Algolia credentials in the page source and query directly."""
    try:
        resp = requests.get(LISTING_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        html = resp.text
    except requests.RequestException as e:
        logger.error(f"Failed to fetch Uchi Japan: {e}")
        return []

    # Look for Algolia config in the HTML/JS
    app_id_match = re.search(r'(?:appId|applicationId|ALGOLIA_APP_ID)["\s:=]+["\']([A-Z0-9]+)["\']', html)
    api_key_match = re.search(r'(?:apiKey|searchOnlyApiKey|ALGOLIA_SEARCH_KEY)["\s:=]+["\']([a-f0-9]+)["\']', html)

    if not app_id_match or not api_key_match:
        logger.info("Could not find Algolia credentials in page source")
        return []

    app_id = app_id_match.group(1)
    api_key = api_key_match.group(1)
    logger.info(f"Found Algolia config: appId={app_id}")

    # Find the index name
    index_match = re.search(r'(?:indexName|index)["\s:=]+["\']([^"\']+)["\']', html)
    index_name = index_match.group(1) if index_match else "properties"

    # Query Algolia
    try:
        algolia_url = f"https://{app_id}-dsn.algolia.net/1/indexes/{index_name}/query"
        algolia_headers = {
            "X-Algolia-Application-Id": app_id,
            "X-Algolia-API-Key": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "params": "hitsPerPage=50&filters=propertyType:Houses"
        }
        resp = requests.post(algolia_url, headers=algolia_headers, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        listings = []
        for hit in data.get("hits", []):
            listing = _algolia_hit_to_listing(hit)
            if listing:
                listings.append(listing)
        return listings
    except Exception as e:
        logger.error(f"Algolia query failed: {e}")
        return []


def _algolia_hit_to_listing(hit: dict) -> PropertyListing | None:
    """Convert an Algolia hit to a PropertyListing."""
    slug = hit.get("slug", "")
    title = hit.get("title", hit.get("name", slug.replace("-", " ").title()))
    if not title:
        return None

    url = f"{BASE_URL}/properties/{slug}" if slug else ""

    # Location
    location = hit.get("location", "")
    region = hit.get("region", "")
    area = hit.get("area", "")
    city = " / ".join(filter(None, [region, area, location]))
    if not city:
        city = "Japan"

    # Price
    price_amount = hit.get("price")
    price_currency = hit.get("currency", "JPY")
    price_raw = ""
    if price_amount:
        if price_currency == "JPY":
            man = price_amount / 10000
            price_raw = f"¥{int(price_amount):,}（{man:.0f}万円）"
        else:
            price_raw = f"{price_currency} {int(price_amount):,}"

    rate = EXCHANGE_RATES.get(price_currency, EXCHANGE_RATES.get("JPY", 0.048))
    price_cny = price_amount * rate if price_amount else None

    # Details
    bedrooms = str(hit.get("bedrooms", "")) if hit.get("bedrooms") else None
    bathrooms = str(hit.get("bathrooms", "")) if hit.get("bathrooms") else None
    area_sqm = hit.get("floorArea") or hit.get("buildingArea")
    land_area = hit.get("landArea")
    year_built = str(hit.get("yearBuilt", "")) if hit.get("yearBuilt") else None

    # Images
    images = hit.get("images", [])
    if isinstance(images, list):
        images = [img.get("url", img) if isinstance(img, dict) else str(img) for img in images[:20]]
    else:
        images = []

    description = hit.get("description", "")
    if isinstance(description, str) and len(description) > 500:
        description = description[:500]

    return PropertyListing(
        source="Uchi Japan",
        url=url,
        title=title,
        city=city,
        country="日本",
        price_raw=price_raw,
        price_amount=price_amount,
        price_currency=price_currency,
        price_cny=price_cny,
        area_sqm=float(area_sqm) if area_sqm else None,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        property_type="House",
        year_built=year_built,
        images=images,
        description=description if description else None,
    )


def _scrape_html() -> list[PropertyListing]:
    """Fallback: scrape Uchi Japan via HTML parsing of search results."""
    listings = []

    # The properties page uses JS rendering, so direct HTML may be limited
    # Try fetching the main page which has some listings in SSR
    try:
        resp = requests.get(BASE_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch Uchi Japan homepage: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Find property links
    property_links = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "/properties/" in href and href != "/properties/" and "/sold" not in href and "/map" not in href:
            full_url = href if href.startswith("http") else BASE_URL + href
            property_links.add(full_url)

    logger.info(f"Found {len(property_links)} property links on Uchi Japan (HTML fallback)")

    # Scrape detail pages
    for url in sorted(property_links)[:20]:  # Limit
        time.sleep(REQUEST_DELAY)
        try:
            listing = _scrape_detail_page(url)
            if listing:
                listings.append(listing)
                logger.info(f"  ✓ {listing.title} — {listing.price_raw}")
        except Exception as e:
            logger.error(f"  ✗ Failed to scrape {url}: {e}")

    return listings


def _scrape_detail_page(url: str) -> PropertyListing | None:
    """Scrape a single Uchi Japan property detail page."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    # Title
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.text.split("|")[0].strip()

    if not title:
        return None

    # Location from breadcrumb-like text
    # Pattern: "Hokkaido / Niseko Area / Kutchan Town"
    city = ""
    loc_match = re.search(r'(Hokkaido|Mainland Japan|Okinawa)\s*/\s*([\w\s]+)\s*/?\s*([\w\s]*)', text)
    if loc_match:
        parts = [loc_match.group(1), loc_match.group(2).strip()]
        if loc_match.group(3):
            parts.append(loc_match.group(3).strip())
        city = " / ".join(filter(None, parts))
    if not city:
        city = "Japan"

    # Price
    price_amount = None
    price_raw = ""
    yen_match = re.search(r'¥([\d,]+)', text)
    if yen_match:
        price_str = yen_match.group(1).replace(",", "")
        try:
            price_amount = float(price_str)
            man = price_amount / 10000
            price_raw = f"¥{int(price_amount):,}（{man:.0f}万円）"
        except ValueError:
            pass

    price_cny = price_amount * EXCHANGE_RATES.get("JPY", 0.048) if price_amount else None

    # Bedrooms
    bedrooms = None
    bed_match = re.search(r'(\d+)\s*(?:bedrooms?|beds?)', text, re.I)
    if bed_match:
        bedrooms = bed_match.group(1)
    # Also check the structured data: "3 + 1" pattern
    bed_match2 = re.search(r'House\s*·.*?(\d+(?:\s*\+\s*\d+)?)\s*·', text)
    if bed_match2 and not bedrooms:
        bedrooms = bed_match2.group(1)

    # Bathrooms
    bathrooms = None
    bath_match = re.search(r'(\d+)\s*(?:bathrooms?|baths?)', text, re.I)
    if bath_match:
        bathrooms = bath_match.group(1)

    # Area
    area_sqm = None
    area_match = re.search(r'([\d.]+)\s*sqm', text, re.I)
    if area_match:
        area_sqm = float(area_match.group(1))

    # Year built
    year_built = None
    year_match = re.search(r'(?:Built|built|Year)\s*(?:in\s*)?(\d{4})', text)
    if year_match:
        year_built = year_match.group(1)

    # Images
    images = []
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src and ("uchijapan" in src or "cloudinary" in src):
            if any(ext in src.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                if src not in images:
                    images.append(src)

    # Description
    description = None
    for p in soup.find_all("p"):
        txt = p.get_text(strip=True)
        if len(txt) > 100 and "cookie" not in txt.lower() and "notified" not in txt.lower():
            description = txt
            break

    return PropertyListing(
        source="Uchi Japan",
        url=url,
        title=title,
        city=city,
        country="日本",
        price_raw=price_raw,
        price_amount=price_amount,
        price_currency="JPY",
        price_cny=price_cny,
        area_sqm=area_sqm,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        property_type="House",
        year_built=year_built,
        images=images[:20],
        description=description,
    )
