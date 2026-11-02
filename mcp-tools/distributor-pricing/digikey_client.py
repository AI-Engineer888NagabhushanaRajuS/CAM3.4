import time
import requests

try:
    from models import PartDetails, PriceBreak
except ImportError:
    from distributor_pricing.models import PartDetails, PriceBreak


class DigikeyClient:
    TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
    PRODUCT_DETAILS_URL = "https://api.digikey.com/products/v4/search/{part_number}/productdetails"
    KEYWORD_SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None
        self._token_expiry = 0
        self.session = requests.Session()

    def _authenticate(self):
        resp = self.session.post(
            self.TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
        )

        resp.raise_for_status()

        data = resp.json()

        self._token = data["access_token"]
        self._token_expiry = (
            time.time()
            + data.get("expires_in", 3600)
            - 60
        )

    def _get_token(self):

        if (
            self._token is None
            or time.time() >= self._token_expiry
        ):
            self._authenticate()

        return self._token

    def _headers(self):

        return {
            "Authorization": f"Bearer {self._get_token()}",
            "X-DIGIKEY-Client-Id": self.client_id,
            "Accept": "application/json",
        }

    def _make_request(
        self,
        method,
        url,
        **kwargs
    ):

        resp = self.session.request(
            method,
            url,
            headers=self._headers(),
            timeout=30,
            **kwargs
        )

        if resp.status_code == 401:

            self._token = None

            resp = self.session.request(
                method,
                url,
                headers=self._headers(),
                timeout=30,
                **kwargs
            )

        return resp

    def lookup(
        self,
        part_number
    ):

        result = self._lookup_product_details(
            part_number
        )

        if not result.error:
            return result

        return self._lookup_keyword_search(
            part_number
        )

    def _lookup_product_details(
        self,
        part_number
    ):

        url = self.PRODUCT_DETAILS_URL.format(
            part_number=requests.utils.quote(
                part_number
            )
        )

        try:

            resp = self._make_request(
                "GET",
                url
            )

            if resp.status_code in (
                404,
                400
            ):
                return PartDetails(
                    part_number=part_number,
                    distributor="Digikey",
                    error="Part not found"
                )

            if resp.status_code == 429:
                return PartDetails(
                    part_number=part_number,
                    distributor="Digikey",
                    error="Rate limit exceeded"
                )

            resp.raise_for_status()

            return self._parse_response(
                part_number,
                resp.json()
            )

        except requests.RequestException as e:

            return PartDetails(
                part_number=part_number,
                distributor="Digikey",
                error=str(e)
            )

    def _lookup_keyword_search(
        self,
        part_number
    ):

        payload = {
            "Keywords": part_number,
            "RecordCount": 10,
            "RecordStartPosition": 0,
            "ExcludeMarketPlaceProducts": True,
        }

        try:

            resp = self._make_request(
                "POST",
                self.KEYWORD_SEARCH_URL,
                json=payload
            )

            if resp.status_code == 429:
                return PartDetails(
                    part_number=part_number,
                    distributor="Digikey",
                    error="Rate limit exceeded"
                )

            resp.raise_for_status()

            data = resp.json()

            products = data.get(
                "Products",
                []
            )

            if not products:
                return PartDetails(
                    part_number=part_number,
                    distributor="Digikey",
                    error="Part not found"
                )

            best = products[0]

            for p in products:

                if (
                    p.get(
                        "ManufacturerPartNumber",
                        ""
                    ).upper()
                    ==
                    part_number.upper()
                ):

                    best = p
                    break

            return self._parse_response(
                part_number,
                best
            )

        except requests.RequestException as e:

            return PartDetails(
                part_number=part_number,
                distributor="Digikey",
                error=str(e)
            )

    def search_alternatives(
        self,
        keyword,
        limit=20
    ):

        payload = {
            "Keywords": keyword,
            "RecordCount": limit,
            "RecordStartPosition": 0,
            "ExcludeMarketPlaceProducts": True,
        }

        try:

            resp = self._make_request(
                "POST",
                self.KEYWORD_SEARCH_URL,
                json=payload
            )

            resp.raise_for_status()

            data = resp.json()

            return data.get(
                "Products",
                []
            )

        except Exception as e:

            print(
                f"Alternative search failed: {e}"
            )

            return []

    def _parse_response(
        self,
        part_number,
        data
    ):

        product = data.get(
            "Product",
            data
        )

        variations = product.get(
            "ProductVariations",
            []
        )

        variation = None

        for v in variations:

            pkg = (
                v.get(
                    "PackageType",
                    {}
                )
                .get(
                    "Name",
                    ""
                )
            )

            if "Cut Tape" in pkg:

                variation = v
                break

        if variation is None and variations:
            variation = variations[0]

        price_breaks = []

        if variation:

            for pb in variation.get(
                "StandardPricing",
                []
            ):

                price_breaks.append(
                    PriceBreak(
                        quantity=pb.get(
                            "BreakQuantity",
                            0
                        ),
                        unit_price=pb.get(
                            "UnitPrice",
                            0.0
                        ),
                    )
                )

        unit_price = product.get(
            "UnitPrice"
        )

        if (
            unit_price is None
            and price_breaks
        ):
            unit_price = (
                price_breaks[0]
                .unit_price
            )

        desc = product.get(
            "Description",
            {}
        )

        if isinstance(
            desc,
            dict
        ):

            description = (
                desc.get(
                    "ProductDescription",
                    ""
                )
                or
                desc.get(
                    "DetailedDescription",
                    ""
                )
            )

        else:

            description = (
                str(desc)
                if desc
                else ""
            )

        status = product.get(
            "ProductStatus",
            ""
        )

        if isinstance(
            status,
            dict
        ):

            status = status.get(
                "Status",
                ""
            )

        distributor_pn = ""

        if variation:

            distributor_pn = variation.get(
                "DigiKeyProductNumber",
                ""
            )

        moq = None
        spq = None

        if variation:

            moq = variation.get(
                "MinimumOrderQuantity"
            )

            spq = variation.get(
                "StandardPackage"
            )

        lead_time = product.get(
            "ManufacturerLeadWeeks",
            ""
        )

        if lead_time:
            lead_time = (
                f"{lead_time} weeks"
            )

        return PartDetails(
            part_number=part_number,
            manufacturer=product.get(
                "Manufacturer",
                {}
            ).get(
                "Name",
                ""
            ),
            description=description,
            distributor="Digikey",
            distributor_pn=distributor_pn,
            unit_price=unit_price,
            currency="USD",
            moq=moq,
            spq=spq,
            stock_quantity=product.get(
                "QuantityAvailable"
            ),
            lead_time=lead_time,
            lifecycle_status=status,
            datasheet_url=product.get(
                "DatasheetUrl",
                ""
            ) or product.get(
                "PrimaryDatasheet",
                ""
            ),
            product_url=product.get(
                "ProductUrl",
                ""
            ),
            price_breaks=price_breaks,
        )

