"""
Scraper for Aucoot (aucoot.com) — UK design-led heritage properties.
"""
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from config import HEADERS, REQUEST_TIMEOUT, REQUEST_DELAY, EXCHANGE_RATES
from models import PropertyListing

logger = logging.getLogger(__name__)

BASE_URL = "https://www.aucoot.com"
LISTING_URL = f"{BASE_URL}/buy/"


def scrape_listings() -> list[PropertyListing]:
    """Scrape all current listings from Aucoot."""
    listings = []

    # Step 1: Get listing URLs from the /buy/ page
    logger.info("Fetching Aucoot listing page...")
    try:
        resp = requests.get(LISTING_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch Aucoot listings page: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Find all property links — they follow pattern /property/{slug}/
    property_links = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "/property/" in href and href != "/property/":
            full_url = href if href.startswith("http") else BASE_URL + href
            # Skip "sold" or "previous sales" links
            property_links.add(full_url.rstrip("/") + "/")

    logger.info(f"Found {len(property_links)} property links on Aucoot")

    # Step 2: Scrape each property detail page
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
    """Scrape a single Aucoot property detail page."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    text = resp.text

    # --- Title (address) ---
    title = ""
    # Look for the h1 or main heading with the property name
    # Aucoot uses the page <title> tag reliably: "Address - Aucoot"
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.text.replace(" - Aucoot", "").strip()

    if not title:
        return None

    # --- Price ---
    price_raw = ""
    price_amount = None
    # Look for price text like "£3,000,000"
    price_match = re.search(r'£[\d,]+(?:\s*to\s*£[\d,]+)?', text)
    if price_match:
        price_raw = price_match.group(0).strip()
        # Extract first number for conversion
        num_match = re.search(r'£([\d,]+)', price_raw)
        if num_match:
            price_amount = float(num_match.group(1).replace(",", ""))

    price_cny = price_amount * EXCHANGE_RATES["GBP"] if price_amount else None

    # --- City ---
    # Extract from title: "Maresfield Gardens, Hampstead, London, NW3"
    # Usually the last meaningful part before postcode
    city = _extract_city_from_title(title)

    # --- Images ---
    images = []
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if "assets.aucoot.com" in src and "wp-content/uploads" in src:
            # Get high-res version by removing size constraints
            clean_url = re.sub(r'\?.*$', '', src)  # Remove query params
            if clean_url not in images:
                images.append(clean_url)

    # --- Floorplan ---
    floorplan_url = None
    floorplan_section = soup.find(id="anchor-floorplan") or soup.find("h2", string=re.compile("Floorplan", re.I))
    if floorplan_section:
        # Look for images near the floorplan section
        parent = floorplan_section.find_parent("section") or floorplan_section.find_parent("div")
        if parent:
            for img in parent.find_all("img"):
                src = img.get("src", "")
                if "assets.aucoot.com" in src:
                    floorplan_url = re.sub(r'\?.*$', '', src)
                    break

    # --- Area ---
    area_sqm = None
    area_sqft = None
    area_match = re.search(r'(\d[\d,]*)\s*sq\s*ft\s*/\s*(\d[\d,]*)\s*sq\s*m', text)
    if area_match:
        area_sqft = float(area_match.group(1).replace(",", ""))
        area_sqm = float(area_match.group(2).replace(",", ""))
    else:
        sqft_match = re.search(r'(\d[\d,]*)\s*sq\s*ft', text)
        if sqft_match:
            area_sqft = float(sqft_match.group(1).replace(",", ""))
            area_sqm = area_sqft * 0.0929
        sqm_match = re.search(r'(\d[\d,]*)\s*sq\s*m', text)
        if sqm_match:
            area_sqm = float(sqm_match.group(1).replace(",", ""))

    # --- Bedrooms (from description text) ---
    bedrooms = None
    bed_patterns = [
        r'(\w+)[\-\s]bedroom',           # "two-bedroom", "five bedroom"
        r'(\d+)\s*bed\b',                  # "3 bed"
        r'(\d+/\d+)[\-\s]bedroom',        # "5/6-bedroom"
    ]
    for pattern in bed_patterns:
        m = re.search(pattern, text, re.I)
        if m:
            bedrooms = _word_to_num(m.group(1))
            break

    # --- Bathrooms ---
    bathrooms = None
    bath_patterns = [
        r'(\w+)\s*bathroom',
        r'(\d+)\s*bath\b',
    ]
    for pattern in bath_patterns:
        m = re.search(pattern, text, re.I)
        if m:
            bathrooms = _word_to_num(m.group(1))
            break

    # --- Property type ---
    property_type = None
    type_keywords = ["apartment", "flat", "house", "townhouse", "cottage", "villa", "maisonette", "farmhouse"]
    text_lower = text.lower()
    for kw in type_keywords:
        if kw in text_lower:
            property_type = kw.capitalize()
            break

    # --- Year built / period ---
    year_built = None
    year_patterns = [
        r'(\d{4})\s*(?:red[\-\s]brick|built|constructed|dating)',
        r'(?:built|constructed|dating|from)\s*(?:in|to|from)?\s*(\d{4})',
        r'(\d{1,2}(?:st|nd|rd|th)\s*[Cc]entury)',
        r'((?:Georgian|Victorian|Edwardian|Regency|Tudor|Medieval|Art Deco))',
    ]
    for pattern in year_patterns:
        m = re.search(pattern, text, re.I)
        if m:
            year_built = m.group(1) if m.group(1) else m.group(0)
            year_built = year_built.strip()
            break

    # --- Architect ---
    architect = None
    arch_match = re.search(r'Architect\s*[\n:]*\s*([^\n<]+)', text)
    if arch_match:
        architect = arch_match.group(1).strip()

    # --- Tenure ---
    tenure = None
    tenure_match = re.search(r'Tenure\s*[\n:]*\s*([\w\s]+?)(?:\n|<)', text)
    if tenure_match:
        tenure = tenure_match.group(1).strip()
    # Also check for explicit mentions
    if not tenure:
        if "share of freehold" in text_lower:
            tenure = "Share of Freehold"
        elif "freehold" in text_lower:
            tenure = "Freehold"
        elif "leasehold" in text_lower:
            tenure = "Leasehold"

    # --- Description ---
    description = None
    # Look for the "Full Details" or "Information" section
    info_section = soup.find("h2", string=re.compile("Information", re.I))
    if info_section:
        # Get all text in the next sibling div/section
        parent = info_section.find_parent("section") or info_section.find_parent("div")
        if parent:
            paragraphs = parent.find_all("p")
            if paragraphs:
                description = " ".join(p.get_text(strip=True) for p in paragraphs[:3])
    if not description:
        # Fallback: find first big block of text
        for p in soup.find_all("p"):
            txt = p.get_text(strip=True)
            if len(txt) > 100:
                description = txt
                break

    return PropertyListing(
        source="Aucoot",
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
        architect=architect,
        tenure=tenure,
        images=images[:20],  # Cap at 20
        floorplan_url=floorplan_url,
        description=description,
    )


def _extract_city_from_title(title: str) -> str:
    """Extract city from Aucoot property title.
    e.g. 'Maresfield Gardens, Hampstead, London, NW3' → 'London'
    """
    parts = [p.strip() for p in title.split(",")]
    if len(parts) >= 3:
        # Usually: Street, Area, City, Postcode
        # Check if last part looks like a postcode
        if re.match(r'^[A-Z]{1,2}\d', parts[-1].strip()):
            return parts[-2].strip() if len(parts) >= 3 else parts[-1].strip()
        return parts[-1].strip()
    elif len(parts) == 2:
        return parts[-1].strip()
    return title


WORD_NUMS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}

def _word_to_num(s: str) -> str:
    """Convert word numbers to digits. Pass through if already a number."""
    s = s.strip().lower()
    return WORD_NUMS.get(s, s)
