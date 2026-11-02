import re
import requests

try:
    from models import PartDetails, PriceBreak
except ImportError:
    from distributor_pricing.models import PartDetails, PriceBreak


class MouserClient:
    SEARCH_URL = "https://api.mouser.com/api/v2/search/partnumber"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()

    def lookup(self, part_number: str) -> PartDetails:
        """Look up a part on Mouser. Returns a PartDetails object."""
        url = f"{self.SEARCH_URL}?apiKey={self.api_key}"
        payload = {
           "SearchByPartRequest": {
        "mouserPartNumber": part_number,
        "partSearchOptions": ""
    }
}

        try:
            resp = self.session.post(url, json=payload, timeout=30)

            if resp.status_code == 429:
                return PartDetails(
                    part_number=part_number,
                    distributor="Mouser",
                    error="Rate limit exceeded",
                )

            resp.raise_for_status()
            data = resp.json()

            errors = data.get("Errors", [])
            if errors:
                error_msg = "; ".join(
                    e.get("Message", str(e)) for e in errors
                )
                return PartDetails(
                    part_number=part_number,
                    distributor="Mouser",
                    error=error_msg,
                )

            parts = data.get("SearchResults", {}).get("Parts", [])
            if not parts:
                return PartDetails(
                    part_number=part_number,
                    distributor="Mouser",
                    error="Part not found",
                )

            # Use the first matching part
            return self._parse_part(part_number, parts[0])

        except requests.RequestException as e:
            return PartDetails(
                part_number=part_number,
                distributor="Mouser",
                error=str(e),
            )

    def _parse_part(self, part_number: str, part: dict) -> PartDetails:
        # Parse price breaks
        price_breaks = []
        for pb in part.get("PriceBreaks", []):
            price_str = pb.get("Price", "0")
            price_val = float(re.sub(r"[^\d.]", "", price_str) or "0")
            currency = pb.get("Currency", "USD")
            price_breaks.append(PriceBreak(
                quantity=pb.get("Quantity", 0),
                unit_price=price_val,
                currency=currency,
            ))

        unit_price = None
        currency = "USD"
        if price_breaks:
            unit_price = price_breaks[0].unit_price
            currency = price_breaks[0].currency

        # Parse stock from Availability string (e.g. "In Stock" or "3500 In Stock")
        stock = self._parse_stock(part.get("Availability", ""))

        return PartDetails(
            part_number=part_number,
            manufacturer=part.get("Manufacturer", ""),
            description=part.get("Description", ""),
            distributor="Mouser",
            distributor_pn=part.get("MouserPartNumber", ""),
            unit_price=unit_price,
            currency=currency,
            moq=self._safe_int(part.get("Min")),
            spq=self._safe_int(part.get("Mult")),
            stock_quantity=stock,
            lead_time=part.get("LeadTime", ""),
            lifecycle_status=part.get("LifecycleStatus", ""),
            datasheet_url=part.get("DataSheetUrl", ""),
            product_url=part.get("ProductDetailUrl", ""),
            price_breaks=price_breaks,
        )

    @staticmethod
    def _parse_stock(availability: str) -> int | None:
        if not availability:
            return None
        match = re.search(r"([\d,]+)\s*In Stock", availability, re.IGNORECASE)
        if match:
            return int(match.group(1).replace(",", ""))
        if "in stock" in availability.lower():
            return 0
        return None

    @staticmethod
    def _safe_int(value) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
