"""Bring Bulksplit API — reservera bulk-ID, registrera pall, lista terminaler.

Ref: https://developer.bring.com/api/bulksplit/
Används för Bring Business Parcel Bulk (0332) och Pickup Parcel Bulk (0342).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

BULKSPLIT_BASE = "https://api.bring.com/bulksplit/v1"


class BringBulksplitClient:
    """Klient för Bring Bulksplit API."""

    def __init__(self, config: dict, sender_config: dict):
        self.api_uid = config["api_uid"]
        self.api_key = config["api_key"]
        self.customer_number = str(
            config.get("customer_number")
            or sender_config.get("customer_number_bring", "")
        ).strip()
        self.sender = sender_config
        self.test_mode = config.get("test_mode", True)
        self.timeout = config.get("timeout_seconds", 30)
        self._session = self._create_session()

    def _create_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Mybring-API-Uid": self.api_uid,
                "X-Mybring-API-Key": self.api_key,
                "X-Bring-Test-Indicator": str(self.test_mode).lower(),
            }
        )
        return s

    def list_terminals(self) -> list[dict]:
        """Listar tillgängliga terminaler (t.ex. NO_OSLO_4)."""
        url = f"{BULKSPLIT_BASE}/terminals"
        resp = self._session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return data.get("terminals", [])

    def reserve_bulk_id(self, terminal_id: str) -> str:
        """Reserverar bulk-nummer. Returnerar bulkShipmentId (t.ex. CS059102945NO)."""
        if not self.customer_number:
            raise ValueError("Bring customer_number krävs för att reservera bulk-ID")

        sender = self.sender
        sender_party = {
            "name": sender.get("name", ""),
            "addressLine1": sender.get("address1", ""),
            "city": sender.get("city", ""),
            "postalCode": str(sender.get("zipcode", "")).replace(" ", ""),
            "countryCode": (sender.get("country") or "SE").strip(),
        }
        if sender.get("address2"):
            sender_party["addressLine2"] = sender.get("address2", "")
        payload = {
            "customerNumber": self.customer_number,
            "senderParty": sender_party,
            "terminalId": terminal_id,
        }

        url = f"{BULKSPLIT_BASE}/bulk-shipment-ids"
        resp = self._session.post(url, json=payload, timeout=self.timeout)
        if resp.status_code >= 400:
            try:
                err = resp.json()
                msg = err.get("message", str(err))
                logger.error(f"Bring Bulksplit reserve {resp.status_code}: {msg}")
                raise RuntimeError(f"Bring Bulksplit: {msg}")
            except (ValueError, TypeError):
                pass
            resp.raise_for_status()

        data = resp.json()
        bulk_id = data.get("bulkShipmentId", "")
        if not bulk_id:
            raise RuntimeError("Bring: Inget bulkShipmentId i svar")
        logger.info(f"Bring: Reserverat bulk-ID {bulk_id}")
        return bulk_id

    def register_bulk_shipment(
        self,
        bulk_shipment_id: str,
        total_weight_kg: int,
        num_packages: Optional[int] = None,
        num_invoices: Optional[int] = None,
        service_code: str = "0332",
        pallet_type: str = "EUR_PALLETS",
        shipping_date: Optional[datetime] = None,
    ) -> dict:
        """Registrerar pall när den är packad. Returnerar waybillUrl, routingLabelsUrl."""
        if shipping_date is None:
            shipping_date = datetime.now(timezone.utc)

        pallet = {
            "palletType": pallet_type,
            "services": [service_code],
            "totalWeightKg": max(1, int(total_weight_kg)),
        }
        if num_packages is not None and num_packages > 0:
            pallet["numberOfPackages"] = int(num_packages)

        payload = {
            "pallets": [pallet],
            "waybillType": "CMR",
            "routingLabelsType": "ROUTING",
        }
        if num_invoices is not None and num_invoices > 0:
            payload["customsDocuments"] = {
                "numInvoices": int(num_invoices),
                "numExportNotifications": 0,
                "numEurCertificates": 0,
            }
        # ISO 8601 med timezone (t.ex. 2025-10-10T13:00:00+02:00)
        ts = shipping_date.strftime("%Y-%m-%dT%H:%M:%S")
        tz = shipping_date.strftime("%z")
        if len(tz) == 5:
            tz = f"{tz[:3]}:{tz[3:]}"  # +0200 -> +02:00
        payload["shippingDateTime"] = f"{ts}{tz}"

        url = f"{BULKSPLIT_BASE}/bulk-shipments/{bulk_shipment_id}"
        resp = self._session.post(
            url,
            json=payload,
            timeout=self.timeout,
            headers={
                **self._session.headers,
                "X-Bring-Test-Indicator": str(self.test_mode).lower(),
            },
        )
        if resp.status_code >= 400:
            try:
                err = resp.json()
                msg = err.get("message", str(err))
                logger.error(f"Bring Bulksplit register {resp.status_code}: {msg}")
                raise RuntimeError(f"Bring Bulksplit: {msg}")
            except (ValueError, TypeError):
                pass
            resp.raise_for_status()

        data = resp.json()
        return {
            "bulkShipmentId": data.get("bulkShipmentId", bulk_shipment_id),
            "waybillUrl": data.get("waybillUrl", ""),
            "routingLabelsUrl": data.get("routingLabelsUrl", ""),
        }
