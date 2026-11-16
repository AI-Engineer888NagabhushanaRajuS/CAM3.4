"""Validation of the CBOM lines before any Excel is written (Pydantic, strict mode).

Strict mode: a number given as text ("123") is refused, not converted; a missing value is refused where the rule needs it.
Cross-field rule enforced: an original-currency price must name its currency. (The extended-volume rule is not enforced: see below.) A row that breaks a rule is a violation; the export reports every violation and is not release-ready while any remain.
"""
import math

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

TOLERANCE = 1e-6


class CbomLine(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    rfq_id: str = Field(min_length=1)
    volume_no: str = Field(min_length=1)
    fg: str = Field(min_length=1)
    cpn: str = Field(min_length=1)
    part_qty: float = Field(gt=0, description="every part line needs a quantity above zero")
    volume_qty: float | None = Field(default=None, ge=0)
    ext_vol_qty: float | None = Field(default=None, ge=0)
    final_price_conv: float | None = Field(default=None, ge=0)
    final_price_original: float | None = Field(default=None, ge=0)
    final_currency_original: str | None = None

    @model_validator(mode="after")
    def _cross_field(self):
        if self.final_price_original is not None and not self.final_currency_original:
            raise ValueError("a price in the original currency needs its currency")
        # NOT enforced here: "extended volume quantity == part qty x volume qty". The real CBOM rows follow packing / MOQ rounding
        # (RFQ-000032: 3,200 against 39,000), so that rule is not the approved one. It needs the approved rule before it can block a release.
        return self


def _clean(value):
    """A pandas/numpy cell as Python: missing becomes None; numbers stay numbers (strict mode refuses text in number fields)."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return value.item()
        except (ValueError, AttributeError):
            return value
    return value


def violations(cbom_df):
    """[{row, part, message}] for every CBOM line that breaks a declared rule. An empty list means the lines may be written."""
    out = []
    if cbom_df is None or len(cbom_df) == 0:
        return [{"row": None, "part": None, "message": "no CBOM lines to write"}]
    for i, rec in enumerate(cbom_df.to_dict("records")):
        data = {k: _clean(v) for k, v in rec.items()}
        for key in ("rfq_id", "volume_no", "fg", "cpn", "final_currency_original"):
            if data.get(key) is not None and not isinstance(data[key], str):
                data[key] = str(data[key])
        try:
            CbomLine.model_validate(data)
        except ValidationError as e:
            for err in e.errors():
                field = ".".join(str(x) for x in err["loc"]) or "row"
                out.append({"row": i, "part": data.get("cpn"), "message": f"{field}: {err['msg']}"})
        except ValueError as e:
            out.append({"row": i, "part": data.get("cpn"), "message": str(e)})
    return out
