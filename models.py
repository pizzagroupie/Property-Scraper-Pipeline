"""
Unified data model for property listings across all sources.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PropertyListing:
    """A single property listing from any source."""
    # Required fields
    source: str              # e.g. "aucoot", "historiska", "inigo"
    url: str                 # Original listing URL
    title: str               # Property name / address
    city: str                # City or area
    country: str             # e.g. "UK", "Sweden"

    # Price
    price_raw: str           # Original price string e.g. "£3,000,000"
    price_amount: Optional[float] = None  # Numeric amount
    price_currency: str = "GBP"
    price_cny: Optional[float] = None     # Converted to CNY

    # Property details
    area_sqm: Optional[float] = None
    area_sqft: Optional[float] = None
    bedrooms: Optional[str] = None        # String because could be "5/6"
    bathrooms: Optional[str] = None
    property_type: Optional[str] = None   # e.g. "Apartment", "Townhouse"
    year_built: Optional[str] = None      # e.g. "1897", "19th Century"
    architect: Optional[str] = None
    tenure: Optional[str] = None          # e.g. "Freehold", "Bostadsrätt"

    # Media
    images: list[str] = field(default_factory=list)       # High-res image URLs
    floorplan_url: Optional[str] = None

    # Description
    description: Optional[str] = None     # Full text description (truncated for Telegram)

    def unique_id(self) -> str:
        """Generate a unique ID for dedup. Based on source + URL."""
        return f"{self.source}:{self.url}"

    def format_price_cny(self) -> str:
        """Format price with CNY conversion."""
        if self.price_cny:
            if self.price_cny >= 10000:
                wan = self.price_cny / 10000
                return f"{self.price_raw}（≈{wan:.0f}万人民币）"
            else:
                return f"{self.price_raw}（≈{self.price_cny:.0f}元人民币）"
        return self.price_raw

    def format_area(self) -> str:
        """Format area with both sqm and sqft if available."""
        parts = []
        if self.area_sqm:
            parts.append(f"{self.area_sqm:.0f}㎡")
        if self.area_sqft:
            parts.append(f"{self.area_sqft:.0f}sq ft")
        return " / ".join(parts) if parts else "未标注"

    def to_telegram_message(self) -> str:
        """Format as a Telegram message."""
        lines = []

        # Header
        lines.append(f"🏠 *{_escape_md(self.title)}*")
        lines.append(f"📍 {_escape_md(self.city)}, {_escape_md(self.country)}")
        lines.append("")

        # Price
        lines.append(f"💰 {_escape_md(self.format_price_cny())}")

        # Area
        lines.append(f"📐 面积: {_escape_md(self.format_area())}")

        # Rooms
        room_parts = []
        if self.bedrooms:
            room_parts.append(f"🛏 {_escape_md(self.bedrooms)}卧")
        if self.bathrooms:
            room_parts.append(f"🚿 {_escape_md(self.bathrooms)}卫")
        if room_parts:
            lines.append(" / ".join(room_parts))

        # Property type
        if self.property_type:
            lines.append(f"🏡 类型: {_escape_md(self.property_type)}")

        # Year / architect
        if self.year_built:
            lines.append(f"🏛 建筑年代: {_escape_md(self.year_built)}")
        if self.architect:
            lines.append(f"✏️ 建筑师: {_escape_md(self.architect)}")

        # Tenure
        if self.tenure:
            lines.append(f"📜 产权: {_escape_md(self.tenure)}")

        lines.append("")

        # Description snippet (first 200 chars)
        if self.description:
            snippet = self.description[:200].strip()
            if len(self.description) > 200:
                snippet += "..."
            lines.append(f"📝 _{_escape_md(snippet)}_")
            lines.append("")

        # Floorplan
        if self.floorplan_url:
            lines.append(f"📋 [户型图]({self.floorplan_url})")

        # Images
        if self.images:
            lines.append(f"📸 共{len(self.images)}张图片")
            for i, img in enumerate(self.images[:5]):
                lines.append(f"  [{i+1}]({img})")

        lines.append("")
        lines.append(f"🔗 [查看原文]({self.url})")
        lines.append(f"📌 来源: {_escape_md(self.source)}")

        return "\n".join(lines)


def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    if not text:
        return ""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    result = str(text)
    for char in special_chars:
        result = result.replace(char, f'\\{char}')
    return result
