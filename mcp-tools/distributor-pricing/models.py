from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PriceBreak:
    quantity: int
    unit_price: float
    currency: str = "USD"


def select_price_for_qty(price_breaks: list["PriceBreak"], qty) -> tuple[Optional[float], Optional[str]]:
    """Selects the price-break tier that actually applies to `qty`, per standard
    distributor price-break semantics: a breakpoint of quantity=100 means "100 or
    more", so the correct tier is the HIGHEST breakpoint quantity that is <= qty --
    not price_breaks[0] (the lowest/qty=1 tier), which every one of this module's
    callers previously used regardless of how many units were actually needed.

    Falls back to the lowest available breakpoint if qty is below every listed
    breakpoint (e.g. required_qty=1 against a part whose cheapest tier starts at
    10) -- still returns a real, usable price rather than None.

    Returns (unit_price, currency), or (None, None) if price_breaks is empty.
    """
    if not price_breaks:
        return None, None
    try:
        qty = float(qty)
    except (TypeError, ValueError):
        qty = 0.0
    ordered = sorted(price_breaks, key=lambda pb: pb.quantity)
    selected = ordered[0]
    for pb in ordered:
        if qty >= pb.quantity:
            selected = pb
        else:
            break
    return selected.unit_price, selected.currency


@dataclass
class PartDetails:
    part_number: str
    manufacturer: str = ""
    description: str = ""
    distributor: str = ""
    distributor_pn: str = ""
    unit_price: Optional[float] = None
    currency: str = "USD"
    moq: Optional[int] = None
    spq: Optional[int] = None
    stock_quantity: Optional[int] = None
    lead_time: str = ""
    lifecycle_status: str = ""
    datasheet_url: str = ""
    product_url: str = ""
    price_breaks: list[PriceBreak] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        price_breaks_str = "; ".join(
            f"{pb.quantity}+: {pb.currency} {pb.unit_price}" for pb in self.price_breaks
        )
        return {
            "Part Number": self.part_number,
            "Manufacturer": self.manufacturer,
            "Description": self.description,
            "Distributor": self.distributor,
            "Distributor PN": self.distributor_pn,
            "Unit Price": self.unit_price,
            "Currency": self.currency,
            "MOQ": self.moq,
            "SPQ": self.spq,
            "Stock": self.stock_quantity,
            "Lead Time": self.lead_time,
            "Lifecycle Status": self.lifecycle_status,
            "Datasheet URL": self.datasheet_url,
            "Product URL": self.product_url,
            "Price Breaks": price_breaks_str,
            "Error": self.error,
        }
