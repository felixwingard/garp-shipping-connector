"""PostNord Booking & Label API-klient.

Använder PostNord Booking API v3 för att:
- Skapa sändning + hämta etikett i ett anrop
- Hitta servicepoints/ombud
"""

import base64
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .base import CarrierClient
from ..parsers.models import Shipment

logger = logging.getLogger(__name__)


class PostNordClient(CarrierClient):
    """Klient för PostNord Booking API."""

    def __init__(self, config: dict, sender_config: dict):
        self.base_url = config["base_url"].rstrip("/")
        self.api_key = config["api_key"]
        self.customer_number = sender_config.get("customer_number_postnord", "")
        self.sender = sender_config
        self.timeout = config.get("timeout_seconds", 30)
        self.session = self._create_session(config)

    def _create_session(self, config: dict) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-API-Key": config["api_key"],
        })
        retries = Retry(
            total=config.get("retry_attempts", 3),
            backoff_factor=config.get("retry_delay_seconds", 5),
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST", "GET"],
        )
        session.mount("https://", HTTPAdapter(max_retries=retries))
        return session

    def create_shipment(self, shipment: Shipment) -> dict:
        """Skapar sändning och hämtar etikett via Booking API.

        PostNord kombinerar bokning + etikett i ett anrop.

        Returns:
            {
                "shipment_id": str,
                "tracking_number": str,
                "label_data": bytes,
                "label_format": str,
            }
        """
        label_format = "pdf"  # PostNord stödjer PDF, kan konverteras till ZPL vid behov
        payload = self._build_booking_payload(shipment, label_format)

        logger.info(
            f"PostNord: Skapar sändning för order {shipment.order_no}, "
            f"tjänst {shipment.service.product_code}"
        )

        response = self.session.post(
            f"{self.base_url}/shipment/v3/booking",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()

        # Extrahera resultat
        shipments = data.get("shipments", [{}])
        first_shipment = shipments[0] if shipments else {}
        items = first_shipment.get("items", [])

        tracking = ""
        label_data = b""
        if items:
            tracking = items[0].get("itemId", "")
            label_b64 = items[0].get("labelData", "")
            if label_b64:
                label_data = base64.b64decode(label_b64)

        shipment_id = first_shipment.get("shipmentId", "")

        logger.info(
            f"PostNord: Sändning skapad — shipment_id={shipment_id}, "
            f"tracking={tracking}"
        )

        return {
            "shipment_id": shipment_id,
            "tracking_number": tracking,
            "label_data": label_data,
            "label_format": label_format,
        }

    def get_label(self, shipment_id: str, label_format: str = "pdf") -> bytes:
        """Hämtar etikett separat (om den inte kom med i create_shipment)."""
        logger.info(f"PostNord: Hämtar etikett för {shipment_id}")

        response = self.session.get(
            f"{self.base_url}/shipment/v3/labels",
            params={
                "shipmentId": shipment_id,
                "format": label_format.upper(),
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.content

    def find_service_points(self, zipcode: str, country: str = "SE",
                            max_results: int = 5) -> list[dict]:
        """Hittar närmaste PostNord-ombud."""
        logger.info(f"PostNord: Söker ombud nära {zipcode}, {country}")

        response = self.session.get(
            f"{self.base_url}/businesslocation/v5/servicepoints/nearest",
            params={
                "apikey": self.api_key,
                "countryCode": country,
                "postalCode": zipcode,
                "numberOfServicePoints": max_results,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        points = (
            response.json()
            .get("servicePointInformationResponse", {})
            .get("servicePoints", [])
        )

        logger.info(f"PostNord: Hittade {len(points)} ombud")
        return points

    def _build_booking_payload(self, shipment: Shipment,
                               label_format: str) -> dict:
        """Bygger JSON-payload för PostNord Booking API v3."""
        recv = shipment.receiver
        container = shipment.containers[0] if shipment.containers else None

        return {
            "shipment": {
                "service": {
                    "basicServiceCode": shipment.service.product_code,
                    "additionalServiceCode": (
                        [shipment.service.addon] if shipment.service.addon else []
                    ),
                },
                "parties": {
                    "sender": {
                        "name1": self.sender.get("name", ""),
                        "addressLine1": self.sender.get("address1", ""),
                        "postalCode": self.sender.get("zipcode", ""),
                        "city": self.sender.get("city", ""),
                        "countryCode": self.sender.get("country", "SE"),
                        "contact": {
                            "emailAddress": self.sender.get("email", ""),
                            "phoneNo": self.sender.get("phone", ""),
                        },
                    },
                    "receiver": {
                        "name1": recv.name,
                        "addressLine1": recv.address1,
                        "addressLine2": recv.address2,
                        "postalCode": recv.zipcode,
                        "city": recv.city,
                        "countryCode": recv.country,
                        "contact": {
                            "emailAddress": recv.email,
                            "phoneNo": recv.phone,
                            "name": recv.contact,
                        },
                    },
                },
                "parcels": [{
                    "weight": {
                        "value": container.weight if container else 1.0,
                        "unit": "kg",
                    },
                    "volume": {
                        "value": container.volume if container else 0.0,
                        "unit": "m3",
                    },
                    "contents": container.contents if container else "",
                    "numberOfPackages": container.copies if container else 1,
                }],
                "orderReference": shipment.reference,
                "customerNumber": self.customer_number,
            },
            "printConfig": {
                "target": {
                    "media": label_format.upper(),
                },
            },
        }
