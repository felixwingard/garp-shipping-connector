"""Bring Booking API-klient.

Använder Bring Booking API för Norge:
- Pickup Parcel Bulk (0342 / PICKUP_PARCEL_BULK)
- Business Parcel Bulk (0332 / BUSINESS_PARCEL_BULK)

Ref: https://developer.bring.com/api/booking/
Auth: X-Mybring-API-Uid + X-Mybring-API-Key
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .base import CarrierClient
from ..parsers.models import Shipment

logger = logging.getLogger(__name__)

# Bring service code -> API product id
# Ref: https://developer.bring.com/api/services/
BRING_SERVICES = {
    # Bulk (kräver bulk-avtal)
    "0342": "PICKUP_PARCEL_BULK",
    "0332": "BUSINESS_PARCEL_BULK",
    "PICKUP_PARCEL_BULK": "PICKUP_PARCEL_BULK",
    "BUSINESS_PARCEL_BULK": "BUSINESS_PARCEL_BULK",
    # Icke-bulk (list agreement)
    "0340": "PICKUP_PARCEL",
    "0330": "BUSINESS_PARCEL",
    "PICKUP_PARCEL": "PICKUP_PARCEL",
    "BUSINESS_PARCEL": "BUSINESS_PARCEL",
}

BOOKING_URL = "https://api.bring.com/booking/api/create"


class BringClient(CarrierClient):
    """Klient för Bring Booking API."""

    def __init__(self, config: dict, sender_config: dict):
        self._bring_config = config
        self.api_uid = config["api_uid"]
        self.api_key = config["api_key"]
        self.customer_number = config.get("customer_number") or sender_config.get(
            "customer_number_bring", ""
        )
        self._consolidated_shipment_id = config.get("consolidated_shipment_id", "")
        self.sender = sender_config
        self.test_mode = config.get("test_mode", True)
        self.timeout = config.get("timeout_seconds", 30)
        self.session = self._create_session(config)

    def _create_session(self, config: dict) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Mybring-API-Uid": self.api_uid,
                "X-Mybring-API-Key": self.api_key,
                "X-Bring-Test-Indicator": str(self.test_mode).lower(),
                "X-Bring-Client-URL": config.get(
                    "client_url", "https://ernstp.se"
                ),
            }
        )
        retries = Retry(
            total=config.get("retry_attempts", 3),
            backoff_factor=config.get("retry_delay_seconds", 5),
            status_forcelist=[429, 502, 503, 504],
            allowed_methods=["POST", "GET"],
        )
        session.mount("https://", HTTPAdapter(max_retries=retries))
        return session

    def create_shipment(self, shipment: Shipment) -> dict:
        """Skapar sändning via Bring Booking API.

        Returnerar label direkt i samma anrop.
        """
        product_id = BRING_SERVICES.get(
            shipment.service.product_code.upper(),
            shipment.service.product_code,
        )
        payload = self._build_booking_payload(shipment, product_id)

        logger.info(
            f"Bring: Skapar sändning för order {shipment.order_no}, "
            f"produkt {product_id}"
        )

        response = self.session.post(
            BOOKING_URL,
            json=payload,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            try:
                err_body = response.json()
                logger.error(f"Bring API fel {response.status_code}: {err_body}")
                raise RuntimeError(
                    f"Bring API {response.status_code}: {err_body}"
                )
            except (ValueError, TypeError):
                pass
            response.raise_for_status()
        data = response.json()

        # Extrahera tracking och etikett från första consignment
        consignments = data.get("consignments", [])
        if not consignments:
            raise RuntimeError("Bring: Inga consignments i svar")

        cons = consignments[0]
        confirmation = cons.get("confirmation") or {}
        consignment_number = confirmation.get("consignmentNumber", "")
        # packages kan vara i confirmation eller på cons-nivå
        packages = confirmation.get("packages") or cons.get("packages", [])
        tracking = packages[0].get("packageNumber", "") if packages else consignment_number

        # Etikett: cons.labels.*, cons.links.*, eller confirmation.links.labels
        label_data = self._fetch_label(cons, confirmation)

        logger.info(
            f"Bring: Sändning skapad — consignment={consignment_number}, "
            f"tracking={tracking}"
        )

        return {
            "shipment_id": consignment_number,
            "tracking_number": tracking,
            "label_data": label_data,
            "label_format": "pdf",
        }

    def get_label(self, shipment_id: str, label_format: str = "pdf") -> bytes:
        """Bring returnerar etikett i create_shipment — denna för fallback."""
        raise NotImplementedError(
            "Bring: Etikett hämtas i create_shipment. "
            "Använd get_all_documents via create_shipment."
        )

    def get_all_documents(self, shipment_id: str) -> dict:
        """Bring har ett anrop — label finns redan från create_shipment."""
        raise NotImplementedError(
            "Bring: Anropa create_shipment först — den returnerar label."
        )

    def get_price_quote(self, shipment: Shipment) -> dict:
        """Hämtar prisuppskattning via Shipping Guide API (exkl. moms).

        Returns:
            Dict med amountWithoutVAT, currency, eller tom dict vid fel.
        """
        from datetime import datetime, timezone

        product_id = BRING_SERVICES.get(
            (shipment.service.product_code or "").upper(),
            shipment.service.product_code,
        )
        if not product_id or not shipment.receiver:
            return {}

        recv = shipment.receiver
        container = shipment.containers[0] if shipment.containers else None
        weight_g = int((container.weight if container else 1.0) * 1000)
        weight_g = max(1000, min(weight_g, 31500))
        length = int(container.length) if container and container.length > 0 else 40
        width = int(container.width) if container and container.width > 0 else 30
        height = int(container.height) if container and container.height > 0 else 20
        length, width, height = max(1, length), max(1, width), max(1, height)

        from_postal = (self.sender.get("zipcode", "") or "43133").replace(" ", "")
        to_postal = _clean_postal(recv.zipcode or "").replace(" ", "")
        from_country = self.sender.get("country", "SE")
        to_country = recv.country or "NO"

        now = datetime.now(timezone.utc)
        payload = {
            "language": "no",
            "withPrice": True,
            "withExpectedDelivery": False,
            "withGuiInformation": False,
            "edi": True,
            "postingAtPostOffice": False,
            "consignments": [
                {
                    "id": 1,
                    "products": [
                        {"id": product_id, "customerNumber": self.customer_number}
                        if self.customer_number
                        else {"id": product_id},
                    ],
                    "fromCountryCode": from_country,
                    "toCountryCode": to_country,
                    "fromPostalCode": from_postal,
                    "toPostalCode": to_postal,
                    "addressLine": recv.address1 or "",
                    "shippingDate": {
                        "day": str(now.day),
                        "hour": str(now.hour),
                        "minute": str(now.minute),
                        "month": str(now.month),
                        "year": str(now.year),
                    },
                    "packages": [
                        {
                            "id": "1",
                            "length": length,
                            "width": width,
                            "height": height,
                            "grossWeight": weight_g,
                        }
                    ],
                }
            ],
        }

        url = "https://api.bring.com/shippingguide/api/v2/products"
        headers = {"Content-Type": "application/json", "X-Bring-Client-URL": "https://ernstp.se"}
        if self.test_mode:
            headers["X-Bring-Test-Indicator"] = "true"

        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout, headers=headers)
            resp.raise_for_status()
        except Exception as e:
            logger.debug(f"Bring Shipping Guide: {e}")
            return {}

        data = resp.json()
        for cons in data.get("consignments", []):
            for prod in cons.get("products", []):
                if prod.get("id") != product_id:
                    continue
                price_info = prod.get("price", {})
                source = price_info.get("netPrice") or price_info.get("listPrice", {})
                pwa = source.get("priceWithAdditionalServices") or source.get(
                    "priceWithoutAdditionalServices", {}
                )
                amt = pwa.get("amountWithoutVAT") or pwa.get("amountWithVAT")
                curr = source.get("currencyCode", "SEK")
                if amt:
                    return {"amountWithoutVAT": str(amt), "currency": curr}
        return {}

    def _fetch_label(self, cons: dict, confirmation: dict = None) -> bytes:
        """Hämtar etikett från consignment-svar (base64 eller URL)."""
        conf = confirmation or {}
        labels = cons.get("labels") or {}
        if isinstance(labels, str):
            return base64.b64decode(labels)
        label_b64 = labels.get("base64") or labels.get("labels", "")
        if label_b64:
            return base64.b64decode(label_b64)
        # URL: cons.labels.link, cons.links.labels, eller confirmation.links.labels
        url = (
            labels.get("link")
            or (cons.get("links") or {}).get("labels")
            or (conf.get("links") or {}).get("labels")
        )
        if url:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return resp.content
        raise ValueError("Bring: Inga etiketter i API-svar (labels/link saknas)")

    def _build_booking_payload(self, shipment: Shipment, product_id: str) -> dict:
        """Bygger Booking API payload."""
        recv = shipment.receiver
        if not recv:
            raise ValueError(
                f"Order {shipment.order_no} saknar mottagarinfo. "
                "Bring kräver recipient."
            )
        container = shipment.containers[0] if shipment.containers else None
        weight = container.weight if container else 1.0
        if weight <= 0:
            weight = 1.0

        # Dimensioner i cm — min 1 för Bring
        length = int(container.length) if container and container.length > 0 else 20
        width = int(container.width) if container and container.width > 0 else 15
        height = int(container.height) if container and container.height > 0 else 5
        length = max(1, length)
        width = max(1, width)
        height = max(1, height)

        svc_ids = list(_parse_additional_services(shipment, {"bring": self._bring_config}))
        additional_services = [{"id": sid} for sid in svc_ids]
        consignment: dict = {
            "shippingDateTime": _bring_datetime_now(),
            "product": {
                        "id": product_id,
                        "customerNumber": self.customer_number,
                        "additionalServices": additional_services,
                    },
                    "parties": {
                        "sender": {
                            "name": self.sender.get("name", ""),
                            "addressLine": self.sender.get("address1", ""),
                            "addressLine2": self.sender.get("address2", ""),
                            "postalCode": self.sender.get("zipcode", ""),
                            "city": self.sender.get("city", ""),
                            "countryCode": self.sender.get("country", "SE"),
                            "contact": {
                                "name": self.sender.get("name", ""),
                                "email": self.sender.get("email", ""),
                                "phoneNumber": self.sender.get("phone", ""),
                            },
                            "reference": shipment.reference or shipment.order_no,
                        },
                        "recipient": {
                            "name": recv.name,
                            "addressLine": recv.address1,
                            "addressLine2": recv.address2 or "",
                            "postalCode": _clean_postal(recv.zipcode),
                            "city": recv.city,
                            "countryCode": recv.country or "NO",
                            "contact": {
                                "name": recv.contact or recv.name,
                                "email": recv.email or "",
                                "phoneNumber": recv.phone or "",
                            },
                            "reference": shipment.reference or "",
                        },
                    },
                    "packages": [
                        {
                            "weightInKg": weight,
                            "dimensions": {
                                "lengthInCm": length,
                                "widthInCm": width,
                                "heightInCm": height,
                            },
                            "goodsDescription": (
                                container.contents[:35] if container and container.contents else ""
                            ),
                        }
                    ],
        }
        # Bulk-produkter (0342/0332) kräver consolidatedShipmentId från Mybring.
        # Skapa pall i Mybring → kopiera bulk-ID → sätt i config eller srvid: BRING:0342:CS059102945NO
        addon_raw = (shipment.service.addon or "").strip()
        consolidated_id = (
            _extract_bulk_id_from_addon(addon_raw)
            or (self._consolidated_shipment_id or "").strip()
            or ""
        )
        if product_id in ("PICKUP_PARCEL_BULK", "BUSINESS_PARCEL_BULK"):
            if not consolidated_id:
                raise ValueError(
                    f"BRING:{product_id} kräver bulk-ID (consolidatedShipmentId). "
                    "Skapa pall i Mybring, kopiera ID och ange i config "
                    "(bring.consolidated_shipment_id) eller i srvid: BRING:0342:CS059102945NO"
                )
            consignment["references"] = {"consolidatedShipmentId": str(consolidated_id)[:20]}

        return {"schemaVersion": 1, "consignments": [consignment]}


def _parse_additional_services(shipment: Shipment, config: Optional[dict] = None) -> list[str]:
    """Extraherar additionalServices från shipment och config.

    Mappning via srvid addon:
      BRING:0332:LQ      → begränsad mängd (0003)
      BRING:0342:SOCIAL  → social kontroll (1082) — för Pickup Parcel (0340/0342)
    Config: bring.social_control: true → lägger till 1082 på Pickup Parcel (0340/0342).
    OBS: 1082 stöds för Pickup Parcel, INTE för 0332 Business Parcel Bulk.

    GARP workaround: volume > 0 = LQ — endast för BRING:0332/0342 (Bring Norge).
    Gäller inte 0330/0340 eller andra transportörer. Config: bring.use_volume_for_lq (default True).
    """
    services = []
    addon = (shipment.service.addon or "").strip()
    prod = (shipment.service.product_code or "").upper()
    for part in addon.replace(",", ":").split(":"):
        part = part.strip().upper()
        if part in ("LQ", "0003") and "0003" not in services:
            services.append("0003")
        elif part in ("SOCIAL", "1082") and "1082" not in services:
            if prod not in ("0332", "BUSINESS_PARCEL_BULK"):
                services.append("1082")
    bring_cfg = (config or {}).get("bring", {}) if config else {}
    # GARP workaround: volume > 0 = LQ — ENDAST Bring Norge 0332/0342 (de enda vi skickar LQ med till Norge)
    use_volume_for_lq = bring_cfg.get("use_volume_for_lq", True)
    if use_volume_for_lq and prod in ("0332", "0342", "BUSINESS_PARCEL_BULK", "PICKUP_PARCEL_BULK"):
        for c in shipment.containers or []:
            if c and float(getattr(c, "volume", 0) or 0) > 0:
                if "0003" not in services:
                    services.append("0003")
                break
    if bring_cfg.get("social_control", False) and "1082" not in services:
        # Endast för Pickup Parcel (0340, 0342)
        if prod in ("0340", "0342", "PICKUP_PARCEL", "PICKUP_PARCEL_BULK"):
            services.append("1082")
    return services


def _looks_like_bulk_id(s: str) -> bool:
    """Kontrollerar om sträng ser ut som Bring bulk-ID (CS/CL + siffror + NO)."""
    s = (s or "").strip()
    return len(s) >= 10 and (s.startswith("CS") or s.startswith("CL")) and s.upper().endswith("NO")


def _extract_bulk_id_from_addon(addon: str) -> str:
    """Hämtar bulk-ID från addon om det finns (t.ex. CS059102945NO, CL311690551NO).

    Addon kan vara "CS123NO", "CS123:LQ" — vi letar efter segment som ser ut som bulk-ID.
    """
    if not addon:
        return ""
    for part in addon.replace(",", ":").split(":"):
        part = part.strip()
        if _looks_like_bulk_id(part):
            return part
    return ""


def _clean_postal(zipcode: str) -> str:
    """Rensar postnummer för Bring. Norge kräver 4 siffror.

    - N-0582, NO-0582 → 0582
    - 0582 O (GARP radbrytning/kolumnfel) → 0582
    """
    cleaned = zipcode.strip().replace(" ", "")
    cleaned = re.sub(r"^[A-Z]{1,2}-", "", cleaned, flags=re.IGNORECASE)
    # GARP: "0582O" eller "0582 O" — ta bara första 4 siffror för norsk postnr
    if len(cleaned) > 4 and cleaned[:4].isdigit():
        cleaned = cleaned[:4]
    return cleaned


def _bring_datetime_now() -> str:
    """ISO 8601 datetime för Bring."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
