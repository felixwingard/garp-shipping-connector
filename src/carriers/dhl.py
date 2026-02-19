"""DHL Paket Sverige API-klient.

Använder DHL Freight API Farm (test-api.freight-logistics.dhl.com):
- TransportInstruction API — skapa sändning (IFTMIN)
- Print API — hämta fraktsedel (ZPL/PDF)
- ServicePointLocator API — hitta ombud
- PickupRequest API — boka upphämtning (IFTMBF)
- AdditionalService API — hämta/validera tilläggstjänster

API-autentisering: Header 'client-key' med GUID-nyckel.
Bas-URL sandbox: https://test-api.freight-logistics.dhl.com
Bas-URL produktion: https://api.freight-logistics.dhl.com

Varje API har sin egen path-prefix:
  /transportinstructionapi/v1/...
  /printapi/v1/...
  /servicepointlocatorapi/v1/...
  /pickuprequestapi/v1/...
  /additionalserviceapi/v1/...

Referens: DHL Produktmanual v5.23
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .base import CarrierClient
from ..parsers.models import Shipment

logger = logging.getLogger(__name__)

# API-sökvägar (relativa till base_url)
API_PATHS = {
    "transport_instruction": "/transportinstructionapi/v1/transportinstruction/sendtransportinstruction",
    "print_documents": "/printapi/v1/print/printdocuments",
    "print_by_id": "/printapi/v1/print/printdocumentsbyid",
    "print_multiple": "/printapi/v1/print/printmultipledocuments",
    "service_points": "/servicepointlocatorapi/v1/servicepoint/findnearestservicepoints",
    "pickup_request": "/pickuprequestapi/v1/pickuprequest/pickuprequest",
    "additional_services": "/additionalserviceapi/v1/additionalservices",
}

# Mappning av tilläggstjänster (addon-kod i srvid -> DHL API-kod)
# Värdet skickas som {api_kod: True} i additionalServices
ADDON_MAPPING = {
    "notification": "notification",
    "AVIS": "notification",
    "preAdviceDelivery": "preAdviceDelivery",
    "tailLiftUnloading": "tailLiftUnloading",
    "tailLiftLoading": "tailLiftLoading",
    "indoorDelivery": "indoorDelivery",
    "dangerousGoods": "dangerousGoods",
    "insurance": "insurance",
    "collectionAtTerminal": "collectionAtTerminal",
    "nonStackable": "nonStackable",
}

# Pakettyp-mappning per produktkod
# 102/103/104/109: PKT (standardkolli)
# 210 (Pall): 701=EUR-pall, 702=halvpall
# 211 (Stycke): PKT
PACKAGE_TYPE_DEFAULTS = {
    "210": "701",  # EUR-pall
}

# Produkter som kräver AccessPoint i parties
PRODUCTS_REQUIRING_ACCESSPOINT = {"103", "104"}


def clean_postal_code(zipcode: str, country: str = "") -> str:
    """Rensar postnummer från landskod-prefix.

    GARP kan exportera postnummer som t.ex. "DK-5220" eller "NO-1234".
    DHL API vill bara ha siffror: "5220".
    """
    cleaned = zipcode.strip()
    # Ta bort landskod-prefix (t.ex. "DK-", "NO-", "FI-")
    if len(cleaned) > 3 and cleaned[2] == "-" and cleaned[:2].isalpha():
        cleaned = cleaned[3:]
    return cleaned


class DHLClient(CarrierClient):
    """Klient för DHL Freight API Farm.

    Alla API-anrop går mot base_url + per-API sökväg.
    Autentisering via 'client-key' header.

    Flöde:
      1. create_shipment() → skapar sändning, returnerar shipment_id + tracking
      2. get_label() → hämtar fraktsedel (ZPL/PDF) via Print API
      3. request_pickup() → bokar upphämtning (valfritt)
    """

    def __init__(self, config: dict, sender_config: dict):
        self.base_url = config["base_url"].rstrip("/")
        self.customer_number = sender_config.get("customer_number_dhl", "")
        self.sender = sender_config
        self.timeout = config.get("timeout_seconds", 30)
        self.session = self._create_session(config)

        # Cache av transportInstruction-svar (behövs för Print API)
        # Nyckel: shipment_id (str), värde: dict (hela TI-objektet)
        self._ti_cache: dict[str, dict] = {}

    def _create_session(self, config: dict) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "client-key": config["api_key"],
        })
        retries = Retry(
            total=config.get("retry_attempts", 3),
            backoff_factor=config.get("retry_delay_seconds", 5),
            status_forcelist=[429, 502, 503, 504],
            allowed_methods=["POST", "GET"],
        )
        session.mount("https://", HTTPAdapter(max_retries=retries))
        return session

    # ------------------------------------------------------------------
    # TransportInstruction API
    # ------------------------------------------------------------------

    def create_shipment(self, shipment: Shipment) -> dict:
        """Skapar sändning via TransportInstruction API.

        POST /transportinstructionapi/v1/transportinstruction/sendtransportinstruction

        Svaret wrappas i {"status": "Succes", "transportInstruction": {...}}.
        TransportInstruction-objektet sparas i cache (behövs för Print API).

        Returns:
            {
                "shipment_id": str,     # DHL:s transport-ID
                "tracking_number": str,  # Kollinummer (barcodeId / pieces[0].id[0])
            }
        """
        payload = self._build_transport_instruction(shipment)
        logger.info(
            f"DHL: Skapar sändning för order {shipment.order_no}, "
            f"produkt {shipment.service.product_code}"
        )
        logger.debug(f"DHL: Payload: {payload}")

        url = f"{self.base_url}{API_PATHS['transport_instruction']}"
        response = self.session.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()

        # Svaret kan ha transportInstruction som nested objekt
        ti = data.get("transportInstruction", data)
        ti_id = str(ti.get("id", ""))

        # Kollinummer finns i pieces[0].id[0] (inte barcodeId)
        pieces = ti.get("pieces", [])
        barcode_id = ""
        if pieces:
            piece_ids = pieces[0].get("id", [])
            if piece_ids and isinstance(piece_ids, list):
                barcode_id = piece_ids[0]
            else:
                barcode_id = pieces[0].get("barcodeId", "")

        # Spara TI-data i cache (behövs för Print API:s printdocuments)
        self._ti_cache[ti_id] = ti

        logger.info(
            f"DHL: Sändning skapad — id={ti_id}, "
            f"barcode={barcode_id}"
        )

        return {
            "shipment_id": ti_id,
            "tracking_number": barcode_id,
        }

    # ------------------------------------------------------------------
    # Print API
    # ------------------------------------------------------------------

    def get_label(self, shipment_id: str, label_format: str = "pdf") -> bytes:
        """Hämtar fraktsedel (PDF) via Print API.

        DHL Print API genererar alltid PDF-etiketter.
        Använder printdocuments (POST) med cachad TI-data + options.

        Args:
            shipment_id: ID från create_shipment.
            label_format: Ignoreras — DHL returnerar alltid PDF.

        Returns:
            PDF-data som bytes.
        """
        logger.info(f"DHL: Hämtar etikett för {shipment_id}")

        # Metod 1: printdocuments med cachad TI-data (verifierad fungerande)
        ti_data = self._ti_cache.get(shipment_id)
        if ti_data:
            try:
                return self._print_documents(ti_data)
            except Exception as e:
                logger.warning(f"DHL: printdocuments misslyckades: {e}")

        # Metod 2: printdocumentsbyid (fallback)
        try:
            return self._print_documents_by_id(shipment_id)
        except Exception as e:
            logger.warning(f"DHL: printdocumentsbyid misslyckades: {e}")

        raise RuntimeError(
            f"DHL: Kunde inte hämta etikett för {shipment_id}. "
            f"Varken printdocuments eller printdocumentsbyid fungerade."
        )

    def get_all_documents(self, shipment_id: str) -> dict:
        """Hämtar etikett + eventuella övriga dokument separat.

        Anropar Print API med olika options:
        - {"label": True} → fraktetikett (alltid)
        - {"shipmentList": True} → fraktlista/följesedel (om tillgängligt)

        Args:
            shipment_id: ID från create_shipment.

        Returns:
            {
                "label": bytes,               # Fraktetikett (PDF)
                "shipment_list": bytes | None  # Fraktlista (PDF) eller None
            }
        """
        logger.info(f"DHL: Hämtar alla dokument för {shipment_id}")

        ti_data = self._ti_cache.get(shipment_id)
        if not ti_data:
            raise RuntimeError(
                f"DHL: Ingen cachad TI-data för {shipment_id}. "
                f"Anropa create_shipment() först."
            )

        # 1. Etikett (obligatorisk)
        label = self._print_documents(ti_data)

        # 2. Fraktlista (valfri — alla produkter har inte det)
        shipment_list = None
        try:
            url = f"{self.base_url}{API_PATHS['print_documents']}"
            payload = {
                "shipment": ti_data,
                "options": {"shipmentList": True},
            }
            response = self.session.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            shipment_list = self._extract_document_from_response(
                response, "ShipmentList"
            )
            logger.info(f"DHL: Fraktlista hämtad ({len(shipment_list)} bytes)")
        except Exception as e:
            logger.debug(f"DHL: Ingen fraktlista tillgänglig: {e}")

        return {
            "label": label,
            "shipment_list": shipment_list,
        }

    def _print_documents(self, ti_data: dict) -> bytes:
        """POST /printapi/v1/print/printdocuments

        Genererar etikett från full sändningsdata.

        Payload:
            {
                "shipment": <transportInstruction-data>,
                "options": {"label": true}
            }

        Response:
            {
                "reports": [{
                    "name": "label_XXXX.pdf",
                    "content": "<base64-PDF>",
                    "contentType": "application/pdf",
                    "type": "Label",
                    "valid": true
                }]
            }
        """
        url = f"{self.base_url}{API_PATHS['print_documents']}"
        payload = {
            "shipment": ti_data,
            "options": {
                "label": True,
            },
        }

        response = self.session.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()

        return self._extract_label_from_response(response, "printdocuments")

    def _print_documents_by_id(self, shipment_id: str) -> bytes:
        """POST /printapi/v1/print/printdocumentsbyid

        Hämtar etikett för redan skapad sändning (fallback).
        """
        url = f"{self.base_url}{API_PATHS['print_by_id']}"
        payload = {
            "transportInstructionId": shipment_id,
            "options": {
                "label": True,
            },
        }

        response = self.session.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()

        return self._extract_label_from_response(response, "printdocumentsbyid")

    def _extract_label_from_response(self, response: requests.Response,
                                      endpoint: str) -> bytes:
        """Extraherar etikettdata från Print API-svar.

        Print API returnerar JSON med reports som innehåller
        base64-kodad PDF i 'content'-fältet.
        """
        import base64

        content_type = response.headers.get("Content-Type", "")

        # Om svaret är direkt binärdata (PDF)
        if "application/pdf" in content_type or "application/octet-stream" in content_type:
            logger.info(f"DHL: Etikett via {endpoint} ({len(response.content)} bytes, binär)")
            return response.content

        # JSON-svar med reports (normalt flöde)
        if "json" in content_type:
            data = response.json()
            reports = data.get("reports", [])

            if not reports:
                raise RuntimeError(
                    f"DHL {endpoint}: Svar 200 men inga reports. "
                    f"Response: {response.text[:200]}"
                )

            # Hämta label-rapporten (type=Label om det finns)
            label_report = None
            for report in reports:
                if report.get("type") == "Label":
                    label_report = report
                    break
            if label_report is None:
                label_report = reports[0]

            # Dekodera base64-innehållet
            content_b64 = label_report.get("content", "")
            if content_b64:
                label_data = base64.b64decode(content_b64)
                label_ct = label_report.get("contentType", "unknown")
                logger.info(
                    f"DHL: Etikett via {endpoint} "
                    f"({len(label_data)} bytes, {label_ct})"
                )
                return label_data

            raise RuntimeError(
                f"DHL {endpoint}: Report finns men 'content' är tomt. "
                f"Report keys: {list(label_report.keys())}"
            )

        # Okänd Content-Type — returnera rådatan
        logger.warning(
            f"DHL {endpoint}: Okänd Content-Type '{content_type}', "
            f"returnerar rådata ({len(response.content)} bytes)"
        )
        return response.content

    def _extract_document_from_response(self, response: requests.Response,
                                         doc_type: str) -> Optional[bytes]:
        """Extraherar ett specifikt dokument (type) från Print API-svar.

        Letar efter en report med matchande 'type'-fält.

        Args:
            response: HTTP-svar från Print API.
            doc_type: Report type att leta efter (t.ex. "ShipmentList", "Label").

        Returns:
            Dokumentdata som bytes, eller None om inte hittat.
        """
        import base64

        content_type = response.headers.get("Content-Type", "")
        if "json" not in content_type:
            return None

        data = response.json()
        reports = data.get("reports", [])

        for report in reports:
            if report.get("type") == doc_type:
                content_b64 = report.get("content", "")
                if content_b64:
                    return base64.b64decode(content_b64)

        # Om vi inte hittade specifik typ, returnera None
        return None

    # ------------------------------------------------------------------
    # ServicePointLocator API
    # ------------------------------------------------------------------

    def find_service_points(self, zipcode: str, country: str = "SE",
                            max_results: int = 5) -> list:
        """Hittar närmaste DHL-ombud via ServicePointLocator API.

        GET /servicepointlocatorapi/v1/servicepoint/findnearestservicepoints
        """
        logger.info(f"DHL: Söker ombud nära {zipcode}, {country}")

        url = f"{self.base_url}{API_PATHS['service_points']}"
        response = self.session.get(
            url,
            params={
                "postalCode": zipcode,
                "countryCode": country,
                "maxResults": max_results,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        points = response.json().get("servicePoints", [])

        logger.info(f"DHL: Hittade {len(points)} ombud")
        return points

    # ------------------------------------------------------------------
    # PickupRequest API
    # ------------------------------------------------------------------

    def request_pickup(self, shipment_id: str, pickup_date: str) -> dict:
        """Bokar upphämtning via PickupRequest API (IFTMBF).

        POST /pickuprequestapi/v1/pickuprequest/pickuprequest
        """
        logger.info(f"DHL: Bokar upphämtning {shipment_id} för {pickup_date}")

        url = f"{self.base_url}{API_PATHS['pickup_request']}"
        response = self.session.post(
            url,
            json={
                "transportInstructionId": shipment_id,
                "pickupDate": pickup_date,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()

        logger.info(f"DHL: Upphämtning bokad")
        return response.json()

    # ------------------------------------------------------------------
    # Payload-bygge
    # ------------------------------------------------------------------

    def _build_transport_instruction(self, shipment: Shipment) -> dict:
        """Bygger JSON-payload för TransportInstruction API.

        Verifierat format mot DHL sandbox (status 200):
        - parties[].address: nested objekt med street, cityName, postalCode, countryCode
        - references: string array (ej objekt-array)
        - additionalServices: objekt med bool-värden, t.ex. {"notification": true}
        - pieces[].id: string array ['']
        - postalCode: rensad från landskod-prefix (DK-5220 → 5220)

        Ref: DHL Produktmanual v5.23 + verifierad sandbox-test
        """
        recv = shipment.receiver
        container = shipment.containers[0] if shipment.containers else None
        product_code = shipment.service.product_code

        weight = container.weight if container else 1.0
        volume = container.volume if container else 0.001
        # Minimum volym — DHL godtar inte 0.0
        if volume <= 0:
            volume = 0.001
        copies = container.copies if container else 1

        shipping_date = date.today().isoformat()
        if shipment.service.booking and shipment.service.booking.pickup_date:
            shipping_date = shipment.service.booking.pickup_date

        # Rensa postnummer från landskod-prefix
        sender_zip = clean_postal_code(self.sender.get("zipcode", ""))
        recv_zip = clean_postal_code(recv.zipcode)

        # Parties — address MÅSTE vara nested objekt
        parties = [
            {
                "id": self.customer_number,
                "type": "Consignor",
                "name": self.sender.get("name", ""),
                "references": [shipment.reference] if shipment.reference else [],
                "address": {
                    "street": self.sender.get("address1", ""),
                    "cityName": self.sender.get("city", ""),
                    "postalCode": sender_zip,
                    "countryCode": self.sender.get("country", "SE"),
                },
                "phone": self.sender.get("phone", ""),
                "email": self.sender.get("email", ""),
            },
            {
                "type": "Consignee",
                "name": recv.name,
                "references": [],
                "address": {
                    "street": recv.address1,
                    "cityName": recv.city,
                    "postalCode": recv_zip,
                    "countryCode": recv.country,
                },
                "phone": recv.phone,
                "email": recv.email,
            },
        ]

        # Pakettyp — standardmappning per produktkod
        if container and container.package_code:
            pkg_type = container.package_code
        else:
            pkg_type = PACKAGE_TYPE_DEFAULTS.get(product_code, "PKT")

        # Pieces — id måste vara string array
        pieces = [{
            "id": [""],
            "packageType": pkg_type,
            "numberOfPieces": copies,
            "weight": weight,
            "volume": volume,
        }]

        # Lägg till dimensioner om de finns
        if container and container.length > 0:
            pieces[0]["length"] = container.length
        if container and container.width > 0:
            pieces[0]["width"] = container.width
        if container and container.height > 0:
            pieces[0]["height"] = container.height

        # additionalServices: objekt med bool-värden
        # {"notification": true} — INTE {"notification": {}}
        additional_services = {}
        if shipment.service.addon:
            addon_code = ADDON_MAPPING.get(
                shipment.service.addon, shipment.service.addon
            )
            additional_services[addon_code] = True

        payload = {
            "id": "",
            "productCode": product_code,
            "shippingDate": shipping_date,
            "deliveryInstruction": shipment.delivery_instruction or "",
            "pickupInstruction": "",
            "totalNumberOfPieces": copies,
            "totalWeight": weight,
            "totalVolume": volume,
            "payerCode": {
                "code": "1",  # 1 = Consignor betalar
                "location": "",
            },
            "parties": parties,
            "additionalServices": additional_services,
            "pieces": pieces,
        }

        return payload
