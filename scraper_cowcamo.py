"""
Scraper for Cowcamo (cowcamo.jp) — Tokyo curated renovated apartments.
"""
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from config import HEADERS, REQUEST_TIMEOUT, REQUEST_DELAY, EXCHANGE_RATES
from models import PropertyListing

logger = logging.getLogger(__name__)

BASE_URL = "https://cowcamo.jp"
LISTING_URL = f"{BASE_URL}/update"  # New listings page


def scrape_listings() -> list[PropertyListing]:
    """Scrape latest listings from Cowcamo."""
    listings = []

    logger.info("Fetching Cowcamo listings page...")
    try:
        resp = requests.get(LISTING_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch Cowcamo listings page: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Also parse from the top page which has rich card data
    try:
        resp_top = requests.get(BASE_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp_top.raise_for_status()
        soup_top = BeautifulSoup(resp_top.text, "html.parser")
    except requests.RequestException:
        soup_top = None

    # Collect property links from both pages
    property_links = set()
    for s in [soup, soup_top]:
        if s is None:
            continue
        for a_tag in s.find_all("a", href=True):
            href = a_tag["href"]
            # Cowcamo property URLs: /東京都/世田谷区/名前 or similar Japanese paths
            # They also have /short_stories/ links
            if href.startswith("/") and "report" not in href and "user" not in href:
                # Check if it looks like a property link (has Japanese chars and no common non-property paths)
                skip_paths = ["/search", "/area", "/style", "/mixes", "/service",
                              "/seminar", "/journal", "/magazine", "/about", "/faq",
                              "/contact", "/howto", "/seller", "/urucamo", "/update",
                              "/station", "/room_layouts", "/city", "/company",
                              "/terms", "/policy", "/user", "/consultation"]
                if not any(href.startswith(p) for p in skip_paths):
                    full_url = BASE_URL + href
                    property_links.add(full_url)

    # Also parse card data directly from the homepage
    cards = _parse_homepage_cards(soup_top or soup)
    for card in cards:
        listings.append(card)

    # If we didn't get cards from homepage parsing, try detail pages
    if not listings:
        for url in sorted(property_links)[:30]:  # Limit to 30
            time.sleep(REQUEST_DELAY)
            try:
                listing = _scrape_detail_page(url)
                if listing:
                    listings.append(listing)
                    logger.info(f"  ✓ {listing.title} — {listing.price_raw}")
            except Exception as e:
                logger.error(f"  ✗ Failed to scrape {url}: {e}")

    logger.info(f"Found {len(listings)} listings on Cowcamo")
    return listings


def _parse_homepage_cards(soup: BeautifulSoup) -> list[PropertyListing]:
    """Parse property cards from Cowcamo homepage HTML."""
    listings = []
    if soup is None:
        return listings

    # Find all links that contain property data
    # Cowcamo cards typically have: name, area (sqm), layout (LDK), price (万円), station, district
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        text = a_tag.get_text(" ", strip=True)

        # Must contain price pattern (万円) and area pattern (㎡)
        if "万円" not in text and "㎡" not in text:
            continue

        # Skip non-property links
        if any(x in href for x in ["/search", "/user", "/service", "/mixes", "/urucamo", "/short_stories"]):
            continue

        full_url = href if href.startswith("http") else BASE_URL + href

        # Extract price
        price_amount = None
        price_raw = ""
        price_match = re.search(r'([\d,]+)\s*万円', text)
        if price_match:
            man_yen = float(price_match.group(1).replace(",", ""))
            price_amount = man_yen * 10000  # Convert 万 to yen
            price_raw = f"{price_match.group(1)}万円"

        # Extract area
        area_sqm = None
        area_match = re.search(r'([\d.]+)\s*㎡', text)
        if area_match:
            area_sqm = float(area_match.group(1))

        # Extract layout (1LDK, 2SLDK, etc.)
        layout = None
        layout_match = re.search(r'(\d\w*(?:LDK|DK|K|R|SLDK)(?:\+[\w+]+)?)', text)
        if layout_match:
            layout = layout_match.group(1)

        # Extract property name (the creative Japanese name)
        # Usually the last meaningful text segment
        title = ""
        # Look for Japanese text that's the property name
        lines = [l.strip() for l in text.split() if l.strip()]
        # The property name is usually a standalone Japanese phrase
        for line in lines:
            if re.match(r'^[\u3000-\u9fff\u30a0-\u30ff\u3040-\u309f\uff00-\uffef\w]+$', line):
                if "駅" not in line and "区" not in line and "万円" not in line and "㎡" not in line:
                    if len(line) >= 3:
                        title = line
                        break

        # Extract station info
        station = None
        station_match = re.search(r'(\S+駅\S*\d+分)', text)
        if station_match:
            station = station_match.group(1)

        # Extract district
        district = None
        district_match = re.search(r'([\u4e00-\u9fff]+区[\u4e00-\u9fff]*)', text)
        if district_match:
            district = district_match.group(1)

        if not title and not price_amount:
            continue

        city = district if district else "東京"
        if station:
            city = f"{city}（{station}）"

        price_cny = price_amount * EXCHANGE_RATES.get("JPY", 0.048) if price_amount else None

        # Extract images from the card
        images = []
        for img in a_tag.find_all("img"):
            src = img.get("src", "")
            if src and "cowcamo.jp" in src and "thumbnail" not in src:
                images.append(src)
            elif src and "cowcamo.jp" in src:
                # Use thumbnail as fallback
                images.append(src)

        listing = PropertyListing(
            source="Cowcamo",
            url=full_url,
            title=title if title else f"{layout} {district}" if layout and district else "東京物件",
            city=city,
            country="日本",
            price_raw=price_raw,
            price_amount=price_amount,
            price_currency="JPY",
            price_cny=price_cny,
            area_sqm=area_sqm,
            bedrooms=layout,  # Use layout string directly (1LDK etc.)
            property_type="翻新公寓",
            images=images[:10],
        )
        listings.append(listing)

    # Deduplicate by URL
    seen = set()
    unique = []
    for l in listings:
        if l.url not in seen:
            seen.add(l.url)
            unique.append(l)

    return unique


def _scrape_detail_page(url: str) -> PropertyListing | None:
    """Scrape a single Cowcamo property detail page."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    # Price
    price_amount = None
    price_raw = ""
    price_match = re.search(r'([\d,]+)\s*万円', text)
    if price_match:
        man_yen = float(price_match.group(1).replace(",", ""))
        price_amount = man_yen * 10000
        price_raw = f"{price_match.group(1)}万円"

    # Area
    area_sqm = None
    area_match = re.search(r'([\d.]+)\s*㎡', text)
    if area_match:
        area_sqm = float(area_match.group(1))

    # Layout
    layout = None
    layout_match = re.search(r'(\d\w*(?:LDK|DK|K|R|SLDK))', text)
    if layout_match:
        layout = layout_match.group(1)

    # Title
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.text.split("|")[0].strip()

    if not title and not price_amount:
        return None

    # District
    district_match = re.search(r'([\u4e00-\u9fff]+区[\u4e00-\u9fff]*)', text)
    district = district_match.group(1) if district_match else "東京"

    # Station
    station_match = re.search(r'(\S+駅(?:徒歩)?\d+分)', text)
    station = station_match.group(1) if station_match else None

    city = district
    if station:
        city = f"{district}（{station}）"

    price_cny = price_amount * EXCHANGE_RATES.get("JPY", 0.048) if price_amount else None

    # Images
    images = []
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if "cowcamo.jp/uploads" in src and "thumbnail" not in src:
            if src not in images:
                images.append(src)

    # Floorplan
    floorplan_url = None
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if "floor_plan" in src:
            floorplan_url = src
            break

    # Description
    description = None
    for p in soup.find_all("p"):
        txt = p.get_text(strip=True)
        if len(txt) > 80:
            description = txt
            break

    return PropertyListing(
        source="Cowcamo",
        url=url,
        title=title,
        city=city,
        country="日本",
        price_raw=price_raw,
        price_amount=price_amount,
        price_currency="JPY",
        price_cny=price_cny,
        area_sqm=area_sqm,
        bedrooms=layout,
        property_type="翻新公寓",
        images=images[:20],
        floorplan_url=floorplan_url,
        description=description,
    )
