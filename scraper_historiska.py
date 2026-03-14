"""
Scraper for Historiska Hem (historiskahem.se) — Swedish heritage apartments.
"""
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from config import HEADERS, REQUEST_TIMEOUT, REQUEST_DELAY, EXCHANGE_RATES
from models import PropertyListing

logger = logging.getLogger(__name__)

BASE_URL = "https://historiskahem.se"
LISTING_URL = f"{BASE_URL}/till-salu/"


def scrape_listings() -> list[PropertyListing]:
    """Scrape all current listings from Historiska Hem."""
    listings = []

    # Step 1: Get listing URLs from /till-salu/
    logger.info("Fetching Historiska Hem listing page...")
    try:
        resp = requests.get(LISTING_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch Historiska Hem listings page: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Parse listing cards from the list page
    # Each card is a link with: area, address, rooms, sqm, price
    property_data = []  # (url, quick_data)

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "/object/tillsalu-" in href:
            full_url = href if href.startswith("http") else BASE_URL + href
            # Extract quick data from the card
            card_text = a_tag.get_text(" ", strip=True)
            property_data.append((full_url.rstrip("/") + "/", card_text))

    # Deduplicate by URL
    seen_urls = set()
    unique_data = []
    for url, card in property_data:
        if url not in seen_urls:
            seen_urls.add(url)
            unique_data.append((url, card))

    logger.info(f"Found {len(unique_data)} property links on Historiska Hem")

    # Step 2: Scrape each detail page
    for url, card_text in unique_data:
        time.sleep(REQUEST_DELAY)
        try:
            listing = _scrape_detail_page(url, card_text)
            if listing:
                listings.append(listing)
                logger.info(f"  ✓ {listing.title} — {listing.price_raw}")
        except Exception as e:
            logger.error(f"  ✗ Failed to scrape {url}: {e}")

    return listings


def _scrape_detail_page(url: str, card_text: str) -> PropertyListing | None:
    """Scrape a single Historiska Hem property detail page."""
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
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        return None

    # --- Area / Neighborhood ---
    # Extract from the "OMRÅDE" field in Fakta section, or from the card text
    city = ""
    area_field = _extract_fakta_field(soup, "OMRÅDE") or _extract_fakta_field(soup, "område")
    if area_field:
        city = area_field
    else:
        # Try to extract from card text (usually starts with the area name in caps)
        area_match = re.search(r'^([A-ZÅÄÖ][a-zåäö\s\-–]+)', card_text)
        if area_match:
            city = area_match.group(1).strip()
    if not city:
        city = "Stockholm"
    city = f"{city}, Stockholm"

    # --- Price ---
    price_raw = ""
    price_amount = None
    # Look for price in card text first (e.g. "5 995 000 kr")
    price_match = re.search(r'([\d\s]+)\s*kr', card_text)
    if not price_match:
        price_match = re.search(r'([\d\s]+)\s*kr', text)
    if price_match:
        price_str = price_match.group(1).replace(" ", "").strip()
        try:
            price_amount = float(price_str)
            price_raw = f"{int(price_amount):,} SEK".replace(",", " ")
        except ValueError:
            pass

    price_cny = price_amount * EXCHANGE_RATES["SEK"] if price_amount else None

    # --- Rooms (ROK = rum och kök) ---
    bedrooms = None
    rooms_field = _extract_fakta_field(soup, "RUM")
    if rooms_field:
        # e.g. "2 rum" — ROK system: subtract 1 for kitchen
        num_match = re.search(r'([\d,]+)', rooms_field)
        if num_match:
            rok_str = num_match.group(1).replace(",", ".")
            try:
                rok = float(rok_str)
                # In Swedish ROK: 2 ROK = 1 bedroom + 1 kitchen (+ living room often combined)
                # For Chinese audience: ROK - 1 ≈ bedrooms
                bedrooms_num = max(1, int(rok) - 1)
                bedrooms = f"{bedrooms_num}（{rok_str} ROK）"
            except ValueError:
                bedrooms = rooms_field
    if not bedrooms:
        rok_match = re.search(r'([\d,]+)\s*ROK', card_text, re.I)
        if rok_match:
            rok_str = rok_match.group(1).replace(",", ".")
            try:
                rok = float(rok_str)
                bedrooms_num = max(1, int(rok) - 1)
                bedrooms = f"{bedrooms_num}（{rok_str} ROK）"
            except ValueError:
                pass

    # --- Area (sqm) ---
    area_sqm = None
    area_field = _extract_fakta_field(soup, "AREA")
    if area_field:
        sqm_match = re.search(r'(\d[\d,\.]*)\s*kvm', area_field, re.I)
        if sqm_match:
            area_sqm = float(sqm_match.group(1).replace(",", "."))
    if not area_sqm:
        sqm_match = re.search(r'(\d[\d,\.]*)\s*(?:KVM|kvm|m²)', card_text)
        if sqm_match:
            area_sqm = float(sqm_match.group(1).replace(",", "."))

    # --- Property type ---
    property_type = _extract_fakta_field(soup, "BOSTADSTYP")
    if property_type:
        # Translate common types
        type_map = {
            "lägenhet": "公寓",
            "hus": "别墅/独栋",
            "villa": "别墅",
            "radhus": "联排别墅",
        }
        property_type_lower = property_type.lower().strip()
        property_type = type_map.get(property_type_lower, property_type)

    # --- Year built (from Arkitektur section) ---
    year_built = None
    architect = None
    arch_section = soup.find("h2", string=re.compile("Arkitektur", re.I))
    if arch_section:
        parent = arch_section.find_parent("section") or arch_section.find_parent("div")
        if parent:
            arch_text = parent.get_text(" ", strip=True)
            # Look for: "ARKITEKT: 1897, Arvid Vallin"
            year_match = re.search(r'(\d{4})', arch_text)
            if year_match:
                year_built = year_match.group(1)
            arch_match = re.search(r'ARKITEKT[:\s]*(?:\d{4}[,\s]*)?([\w\s\.]+?)(?:\n|$)', arch_text, re.I)
            if arch_match:
                architect = arch_match.group(1).strip()
    # Fallback: search whole page for year pattern in architectural context
    if not year_built:
        year_match = re.search(r'uppför\w*\s+(?:under\s+)?(?:år(?:en)?\s+)?(\d{4})', text, re.I)
        if year_match:
            year_built = year_match.group(1)

    # --- Tenure ---
    tenure = _extract_fakta_field(soup, "UPPLÅTELSEFORM")
    if tenure:
        tenure_map = {
            "bostadsrätt": "Bostadsrätt（合作产权）",
            "äganderätt": "Äganderätt（完全产权）",
            "hyresrätt": "Hyresrätt（租赁权）",
        }
        tenure = tenure_map.get(tenure.lower().strip(), tenure)

    # --- Floor ---
    floor_info = _extract_fakta_field(soup, "VÅNING")

    # --- Images ---
    images = []
    for img_tag in soup.find_all("img"):
        src = img_tag.get("src", "")
        if not src:
            # Check for lazy-loaded images
            src = img_tag.get("data-src", "")
        if "historiskahem.se/wp-content/uploads/kowboy-estates" in src:
            # Get high-res version
            clean_url = re.sub(r'_w\d+_q\d+', '_w1920_q90', src)
            if clean_url not in images:
                images.append(clean_url)
    # Also check <a> tags linking to images
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "kowboy-estates" in href and href.endswith((".jpg", ".png", ".jpeg", ".JPG", ".TIF")):
            if href not in images:
                images.append(href)

    # --- Floorplan ---
    floorplan_url = None
    plan_section = soup.find("h2", string=re.compile("Planskiss", re.I))
    if plan_section:
        parent = plan_section.find_parent("section") or plan_section.find_parent("div")
        if parent:
            for img in parent.find_all("img"):
                src = img.get("src", "") or img.get("data-src", "")
                if src and "kowboy-estates" in src:
                    floorplan_url = src
                    break
            if not floorplan_url:
                for a in parent.find_all("a", href=True):
                    if "kowboy-estates" in a["href"]:
                        floorplan_url = a["href"]
                        break

    # --- Description ---
    description = None
    # The main description is usually the first big text block after h1
    desc_candidates = soup.find_all("p")
    for p in desc_candidates:
        txt = p.get_text(strip=True)
        if len(txt) > 80 and not txt.startswith("FOTO:"):
            description = txt
            break

    # --- Monthly fee (unique to Swedish bostadsrätt) ---
    monthly_fee = _extract_fakta_field(soup, "AVGIFT")

    # Build the listing
    listing = PropertyListing(
        source="Historiska Hem",
        url=url,
        title=title,
        city=city,
        country="瑞典",
        price_raw=price_raw,
        price_amount=price_amount,
        price_currency="SEK",
        price_cny=price_cny,
        area_sqm=area_sqm,
        bedrooms=bedrooms,
        property_type=property_type,
        year_built=year_built,
        architect=architect,
        tenure=tenure,
        images=images[:20],
        floorplan_url=floorplan_url,
        description=description,
    )

    return listing


def _extract_fakta_field(soup: BeautifulSoup, field_name: str) -> str | None:
    """Extract a value from the Fakta section by field label.
    Historiska Hem uses a pattern like:
    <strong>FIELD_NAME</strong> followed by value text
    """
    # Try multiple approaches
    # Approach 1: Find <strong> or <b> containing the field name
    for strong in soup.find_all(["strong", "b"]):
        if field_name.lower() in strong.get_text(strip=True).lower():
            # Get the next sibling text or next element
            next_sib = strong.next_sibling
            if next_sib and isinstance(next_sib, str):
                value = next_sib.strip().lstrip(":").strip()
                if value:
                    return value
            # Try parent's text minus the label
            parent = strong.parent
            if parent:
                full_text = parent.get_text(strip=True)
                label_text = strong.get_text(strip=True)
                value = full_text.replace(label_text, "").strip().lstrip(":").strip()
                if value:
                    return value
    return None
