"""
Scraper for Inigo (inigo.com) — UK historic homes.
"""
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from config import HEADERS, REQUEST_TIMEOUT, REQUEST_DELAY, EXCHANGE_RATES
from models import PropertyListing

logger = logging.getLogger(__name__)

BASE_URL = "https://www.inigo.com"
LISTING_URL = f"{BASE_URL}/sales-list"


def scrape_listings() -> list[PropertyListing]:
    """Scrape all current listings from Inigo."""
    listings = []

    # Step 1: Get listing URLs from /sales-list
    logger.info("Fetching Inigo listing page...")
    try:
        resp = requests.get(LISTING_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch Inigo listings page: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Also try the home page which has featured listings
    property_links = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "/sales-list/" in href and href != "/sales-list/":
            full_url = href if href.startswith("http") else BASE_URL + href
            # Skip past-sales
            property_links.add(full_url.rstrip("/"))

    # Also fetch the main page for featured listings not on sales-list
    try:
        resp2 = requests.get(BASE_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp2.raise_for_status()
        soup2 = BeautifulSoup(resp2.text, "html.parser")
        for a_tag in soup2.find_all("a", href=True):
            href = a_tag["href"]
            if "/sales-list/" in href and href != "/sales-list/":
                full_url = href if href.startswith("http") else BASE_URL + href
                property_links.add(full_url.rstrip("/"))
    except requests.RequestException:
        pass

    # Filter out sold listings (they have "Sold" in nearby text)
    # We'll check this during detail page scraping instead

    logger.info(f"Found {len(property_links)} property links on Inigo")

    # Step 2: Scrape each detail page
    for url in sorted(property_links):
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
    """Scrape a single Inigo property detail page."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    text = resp.text

    # --- Check if sold ---
    if "Sold" in soup.get_text() and "For Sale" not in soup.get_text():
        # Look more carefully — "Sold" might just be in "Past Sales" section
        page_text = soup.get_text()
        # If "Sold" appears prominently (like in the price area), skip it
        sold_indicators = soup.find_all(string=re.compile(r'^\s*Sold\s*$'))
        if sold_indicators:
            logger.info(f"  Skipping sold listing: {url}")
            return None

    # --- Title ---
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.text.strip()

    if not title:
        return None

    # --- Location ---
    # Inigo shows location like "Gloucester, Gloucestershire" under the title
    city = ""
    # Look for text pattern near the price that contains location
    # The page structure: Title \n Location \n Price
    location_text = ""
    # Find text containing county/city pattern
    for elem in soup.find_all(["p", "span", "div"]):
        t = elem.get_text(strip=True)
        if re.match(r'^[A-Z][\w\s]+,\s+[A-Z][\w\s]+$', t) and "£" not in t:
            location_text = t
            break
    if location_text:
        city = location_text
    else:
        # Try from title tag: "Brunswick Square" doesn't have location
        # Check page text for patterns like "City, County" near price
        loc_match = re.search(r'(?:' + re.escape(title) + r')\s*([\w\s]+,\s+[\w\s]+?)(?:£|\d)', text)
        if loc_match:
            city = loc_match.group(1).strip().rstrip(",")

    if not city:
        city = "UK"

    # --- Price ---
    price_raw = ""
    price_amount = None
    price_match = re.search(r'£([\d,]+)', text)
    if price_match:
        price_raw = f"£{price_match.group(1)}"
        price_amount = float(price_match.group(1).replace(",", ""))

    price_cny = price_amount * EXCHANGE_RATES["GBP"] if price_amount else None

    # --- Tenure ---
    tenure = None
    if "freehold" in text.lower():
        tenure = "Freehold"
    elif "leasehold" in text.lower():
        tenure = "Leasehold"
    elif "share of freehold" in text.lower():
        tenure = "Share of Freehold"

    # --- Area ---
    area_sqm = None
    area_sqft = None
    area_match = re.search(r'([\d,]+)\s*sq\s*ft', text, re.I)
    if area_match:
        area_sqft = float(area_match.group(1).replace(",", ""))
        area_sqm = area_sqft * 0.0929

    # --- Bedrooms ---
    bedrooms = None
    bed_patterns = [
        r'(\w+)[\-/\s](?:six[\-\s])?bedroom',
        r'(\d+/\d+)[\-\s]bedroom',
        r'(\d+)\s*bed\b',
    ]
    for pattern in bed_patterns:
        m = re.search(pattern, text, re.I)
        if m:
            bedrooms = _word_to_num(m.group(1))
            break

    # --- Bathrooms ---
    bathrooms = None
    bath_match = re.search(r'(\w+)\s*(?:further\s*)?bathroom', text, re.I)
    if bath_match:
        bathrooms = _word_to_num(bath_match.group(1))
    # Count "bathroom" occurrences as alternative
    if not bathrooms:
        bath_count = len(re.findall(r'bathroom', text, re.I))
        if bath_count > 0:
            bathrooms = str(bath_count)

    # --- Property type ---
    property_type = None
    type_keywords = ["farmhouse", "townhouse", "cottage", "manor", "vicarage",
                     "apartment", "flat", "house", "villa", "barn"]
    text_lower = text.lower()
    for kw in type_keywords:
        if kw in text_lower:
            property_type = kw.capitalize()
            break

    # --- Year built ---
    year_built = None
    period_patterns = [
        r'(\d{4})',  # Specific year
        r'(\d{1,2}(?:st|nd|rd|th)[\-\s]*[Cc]entury)',
        r'(Grade\s+(?:I|II\*?|III)[\-\s]*listed)',
        r'(Georgian|Victorian|Edwardian|Regency|Tudor|Medieval|Stuart|Jacobean|Queen Anne)',
    ]
    # Look specifically in architectural context
    for pattern in period_patterns:
        # Search near keywords like "built", "dating", "century"
        m = re.search(pattern, text)
        if m:
            candidate = m.group(1)
            # Validate year is reasonable (not a phone number etc)
            if re.match(r'^\d{4}$', candidate):
                year_int = int(candidate)
                if 1200 <= year_int <= 2026:
                    year_built = candidate
                    break
            else:
                year_built = candidate
                break

    # --- Grade listing ---
    grade_match = re.search(r'Grade\s+(I{1,3}\*?|II\*?)[\-\s]*listed', text, re.I)
    grade = None
    if grade_match:
        grade = f"Grade {grade_match.group(1)}-listed"
        if year_built and "Grade" not in year_built:
            year_built = f"{year_built}, {grade}"
        elif not year_built:
            year_built = grade

    # --- Images ---
    images = []
    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "")
        if ("s3.amazonaws.com/propertybase" in src or "openasset.com" in src):
            if "_webres" in src or "_highres" in src:
                if src not in images:
                    images.append(src)

    # --- Floorplan ---
    floorplan_url = None
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "floorplan" in a_tag.get_text(strip=True).lower() or "Floorplan" in a_tag.get_text():
            if href.endswith((".jpg", ".png", ".pdf")) or "highres" in href:
                floorplan_url = href
                break

    # --- Description ---
    description = None
    # Inigo has rich editorial descriptions
    for p in soup.find_all("p"):
        txt = p.get_text(strip=True)
        if len(txt) > 150 and "cookie" not in txt.lower():
            description = txt
            break

    # --- Council Tax Band ---
    council_tax = None
    ct_match = re.search(r'Council Tax Band:\s*([A-H])', text, re.I)
    if ct_match:
        council_tax = ct_match.group(1)

    return PropertyListing(
        source="Inigo",
        url=url,
        title=title,
        city=city,
        country="英国",
        price_raw=price_raw,
        price_amount=price_amount,
        price_currency="GBP",
        price_cny=price_cny,
        area_sqm=area_sqm,
        area_sqft=area_sqft,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        property_type=property_type,
        year_built=year_built,
        tenure=tenure,
        images=images[:20],
        floorplan_url=floorplan_url,
        description=description,
    )


WORD_NUMS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}

def _word_to_num(s: str) -> str:
    """Convert word numbers to digits."""
    s = s.strip().lower()
    return WORD_NUMS.get(s, s)
