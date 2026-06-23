"""Medusa-integration: pusha shipment + tracking tillbaka till webshoppen.

Bakgrund
--------
Connectorn skapar fraktsedeln och får trackingnumret från DHL/Bring. För
WEBSHOP-ordrar vill vi spegla det i Medusa så att:
  * Medusas `shipment-sent`-subscriber skickar "Din order är skickad"-mailet
    (Resend, lokaliserat) med spårningslänk, och
  * kunden ser leveransen + tracking i "Mitt konto".

Webshop-ordrar känns igen på Garp-ordernumret `W{display_id}`. medusa-garp-service
bygger det som `"W" + display_id.ToString("00000")` (CreateOrderHead), så
display_id ligger som siffrorna direkt efter `W` (ev. nollpaddat, ev. följt av
ett Garp-suffix som `-133254`). Vi parsar defensivt OCH validerar mot Medusa:
hittas ingen order med det display_id returnerar vi False och connectorn faller
tillbaka till sitt vanliga SMTP-mail.

Allt är best-effort: varje fel → False + loggning, aldrig en exception som
stoppar fraktflödet (kunden ska få sin etikett oavsett).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Spårnings-URL per transportör (om connectorn inte skickar in en färdig).
_TRACKING_URLS = {
    "DHL": "https://www.dhl.com/se-sv/home/tracking.html?tracking-id={tracking}",
    "BRING": "https://sporing.posten.no/sporing/{tracking}",
    "POSTNORD": "https://www.postnord.se/vara-verktyg/spara-brev-och-paket?shipmentId={tracking}",
}


def parse_display_id(order_no: str, prefix: str = "W") -> Optional[int]:
    """Plocka Medusa display_id ur Garp-ordernumret. None om det inte matchar prefixet.

    `prefix` MÅSTE matcha C#-servicens `order_serie` (default "W" → Garp-ordernr
    W70040). Sätt ett eget prefix (t.ex. "M") i både C#-servicen OCH connectorn om
    ni vill skilja Medusa-ordrar från gamla Woo "W"-ordrar och undvika krock.
    Hanterar nollpaddning + ev. Garp-suffix: "W70040", "W66344-133254", "m00042-9".
    """
    if not order_no:
        return None
    m = re.match(rf"^\s*{re.escape(prefix)}0*(\d+)", order_no, re.IGNORECASE)
    return int(m.group(1)) if m else None


def is_webshop_order(order_no: str, prefix: str = "W") -> bool:
    return parse_display_id(order_no, prefix) is not None


def default_tracking_url(carrier: str, tracking: str) -> str:
    tmpl = _TRACKING_URLS.get((carrier or "").upper())
    return tmpl.format(tracking=tracking) if tmpl and tracking else ""


class MedusaClient:
    """Tunn admin-API-klient mot Medusa. Token-cache + auto-relogin vid 401."""

    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
        *,
        order_prefix: str = "W",
        extra_headers: Optional[dict] = None,
        timeout: int = 20,
    ):
        self.base_url = base_url.rstrip("/")
        self._email = email
        self._password = password
        self.order_prefix = order_prefix or "W"  # måste matcha C#-servicens order_serie
        self._extra_headers = extra_headers or {}  # t.ex. {"X-Garp-Bridge": "..."} för staging
        self.timeout = timeout
        self._token: Optional[str] = None
        self._lock = threading.Lock()

    def is_webshop_order(self, order_no: str) -> bool:
        return is_webshop_order(order_no, self.order_prefix)

    # ---- auth -------------------------------------------------------------
    def _login(self) -> None:
        r = requests.post(
            f"{self.base_url}/auth/user/emailpass",
            json={"email": self._email, "password": self._password},
            headers=self._extra_headers,
            timeout=self.timeout,
        )
        r.raise_for_status()
        self._token = r.json()["token"]

    def _headers(self) -> dict:
        h = dict(self._extra_headers)
        h["Authorization"] = f"Bearer {self._token}"
        h["content-type"] = "application/json"
        return h

    def _request(self, method: str, path: str, **kw) -> requests.Response:
        """Anrop med auto-login + en retry vid 401."""
        with self._lock:
            if not self._token:
                self._login()
        url = f"{self.base_url}{path}"
        kw.setdefault("timeout", self.timeout)
        r = requests.request(method, url, headers=self._headers(), **kw)
        if r.status_code == 401:
            with self._lock:
                self._login()
            r = requests.request(method, url, headers=self._headers(), **kw)
        return r

    # ---- order lookup -----------------------------------------------------
    def find_order_by_display_id(self, display_id: int) -> Optional[dict]:
        """Returnerar ordern (med items) eller None. Validerar display_id exakt."""
        fields = "id,display_id,email,items.id,items.quantity,items.detail.id,fulfillments.id,fulfillments.shipped_at"
        # Medusa v2 admin har inget direkt display_id-filter — `q` söker bl.a. på
        # display_id men är FUZZY (kan returnera andra ordrar först). Vi hämtar ett
        # brett spann och matchar sedan EXAKT nedan så vi aldrig tar fel order.
        r = self._request(
            "GET", f"/admin/orders?q={display_id}&limit=50&fields={fields}"
        )
        if not r.ok:
            logger.warning("Medusa: order-sök display_id=%s gav %s", display_id, r.status_code)
            return None
        for o in r.json().get("orders", []):
            if int(o.get("display_id", -1)) == int(display_id):
                return o
        return None

    # ---- shipment push ----------------------------------------------------
    def push_shipment(
        self,
        order_no: str,
        tracking_number: str,
        carrier: str,
        *,
        tracking_url: str = "",
        label_url: str = "",
    ) -> bool:
        """Spegla shipment + tracking i Medusa för en webshop-order.

        Skapar fulfillment + shipment så ordern blir "skickad" och tracking syns i
        Mitt konto. Medusa mailar INTE (no_notification + metadata.shipped_by) —
        connectorn skickar sitt egna rikare mail (DHL-ledtid + PDF-bilagor).

        Returnerar True om speglingen lyckades (bara för loggning/telemetri).
        False → ingen Medusa-order / fel. Connectorns SMTP-mail går oavsett.
        """
        display_id = parse_display_id(order_no, self.order_prefix)
        if display_id is None:
            return False  # inte en webshop-order (telefon/B2B i Garp)

        try:
            order = self.find_order_by_display_id(display_id)
            if not order:
                logger.info("Medusa: ingen order #%s — hoppar push (SMTP-fallback)", display_id)
                return False

            oid = order["id"]

            # Redan skickad i Medusa? (idempotens — kör inte dubbelt)
            if any(f.get("shipped_at") for f in order.get("fulfillments", [])):
                logger.info("Medusa: order #%s redan shipped — hoppar", display_id)
                return True

            items = [
                {"id": it["id"], "quantity": it["quantity"]}
                for it in order.get("items", [])
                if it.get("id") and it.get("quantity")
            ]
            if not items:
                logger.warning("Medusa: order #%s saknar items — hoppar", display_id)
                return False

            # 1) fulfillment — stämplar metadata.shipped_by så Medusas
            #    shipment-sent-subscriber INTE dubbel-mailar (connectorn skickar
            #    sitt egna rikare mail med DHL-ledtid + PDF-bilagor). no_notification
            #    sätts som bälte-och-hängslen.
            rf = self._request(
                "POST",
                f"/admin/orders/{oid}/fulfillments",
                json={
                    "items": items,
                    "no_notification": True,
                    "metadata": {"shipped_by": "garp-connector"},
                },
            )
            if not rf.ok:
                logger.warning(
                    "Medusa: fulfillment misslyckades för #%s: %s %s",
                    display_id, rf.status_code, rf.text[:200],
                )
                return False
            # Create-svaret listar inte alltid den nya fulfillment:en direkt —
            # läs om ordern och ta senaste OSKEPPADE.
            order2 = self.find_order_by_display_id(display_id) or order
            unshipped = [f for f in order2.get("fulfillments", []) if not f.get("shipped_at")]
            fid = unshipped[-1]["id"] if unshipped else None
            if not fid:
                logger.warning("Medusa: fick inget fulfillment-id för #%s", display_id)
                return False

            # 2) shipment + tracking-label → triggar shipment.created → Resend-mail
            label = {
                "tracking_number": tracking_number,
                "tracking_url": tracking_url or default_tracking_url(carrier, tracking_number),
                "label_url": label_url or "",
            }
            rs = self._request(
                "POST",
                f"/admin/orders/{oid}/fulfillments/{fid}/shipments",
                json={"items": items, "labels": [label], "no_notification": True},
            )
            if not rs.ok:
                logger.warning(
                    "Medusa: shipment misslyckades för #%s: %s %s",
                    display_id, rs.status_code, rs.text[:200],
                )
                return False

            logger.info(
                "Medusa: order #%s markerad skickad (tracking %s) — Resend tar mailet",
                display_id, tracking_number,
            )
            return True

        except Exception as e:  # noqa: BLE001 — får aldrig stoppa fraktflödet
            logger.warning("Medusa: push_shipment-fel för %s: %s", order_no, e)
            return False
