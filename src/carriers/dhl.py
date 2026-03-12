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
from datetime import date, datetime, timezone
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
    "price_quote": "/pricequoteapi/v1/pricequote/quoteforprice",
    "price_quote_gross": "/pricequoteapi/v1/pricequote/quoteforgrossprice",
    "timetable": "/timetableapi/v1/timetable/gettimetable",
}

# Mappning av tilläggstjänster (addon-kod i srvid -> DHL API-kod)
# Värdet skickas som {api_kod: True} i additionalServices
# Flera addons i srvid: DHL:102:AVIS:LQ → både notification och dangerousGoods
ADDON_MAPPING = {
    "notification": "notification",
    "AVIS": "notification",
    "preAdviceDelivery": "preAdviceDelivery",
    "tailLiftUnloading": "tailLiftUnloading",
    "tailLiftLoading": "tailLiftLoading",
    "indoorDelivery": "indoorDelivery",
    "dangerousGoods": "dangerousGoods",
    "DG": "dangerousGoods",
    "LQ": "dangerousGoods",
    "DANGER": "dangerousGoods",
    "insurance": "insurance",
    "collectionAtTerminal": "collectionAtTerminal",
    "nonStackable": "nonStackable",
}

# Pakettyp-mappning per produktkod
# 102/103/104/109: PKT (standardkolli)
# 210 (Pall): 701=EUR-pall, 702=halvpall
# 211 (Stycke): PKT
# GARP/Unifaun kan skicka "PC" (parcel) — DHL kräver PKT för standardkolli
PACKAGE_CODE_NORMALIZE = {"PC": "PKT", "ZP": "701", "Z1": "702"}
PACKAGE_TYPE_DEFAULTS = {
    "210": "701",  # EUR-pall
}

# Produkter som kräver AccessPoint i parties (104 C2B retur stöds ej)
PRODUCTS_REQUIRING_ACCESSPOINT = {"103"}

# Payer code per produkt — 1=Consignor (inrikes), DDP=Delivered Duty Paid (utrikes 109)
# API returnerar "Payercode 1 is not valid for product" för 109 utan denna override
PAYER_CODE_BY_PRODUCT = {
    "109": "DDP",  # Parcel Connect (utrikes)
    "112": "DDP",  # Parcel Connect Plus (utrikes)
    "202": "DDP",  # Euroconnect (utrikes)
    "205": "DDP",  # Euroline (utrikes)
}

# Internationella produkter — använder ALLTID internationellt kundnummer
# (customer_number_dhl_international), oavsett om mottagarlandet ligger i domestic_countries.
# domestic_countries styr enbart inrikesprodukter som 102/103/210/211.
INTERNATIONAL_PRODUCTS = {"109", "112", "202", "205"}

# PriceQuote API: dhlProductCode (Swagger ShipmentModel)
# Paket 102/103: använd numerisk kod (DHL:s exempel: quoteforgrossprice med "103")
# DHLPaket ger fel pris för 103; "103" ger korrekt ombudspris (48 vs 74)
DHL_PRODUCT_CODE_FOR_QUOTE = {
    "102": "102",  # DHL Paket företag (hemleverans)
    "103": "103",  # DHL ServicePoint (ombud)
    "109": "DHLParcelConnect",
    "112": "DHLParcelConnect",  # Plus = variant; prova samma som 109
    "202": "DHLEuroconnect",
    "205": "DHLEuroline",
    "210": "DHLPall",
    "211": "DHLStycke",
    "SPI": "DHLStandardPalletInternational",
    "PPI": "DHLPremiumPalletInternational",
}


def format_sender_name(name: str) -> str:
    """Formaterar avsändarnamn till läsbar form (t.ex. ERNST P AB → Ernst P AB).

    Bevarar AB, HB, KB etc. i versaler.
    """
    if not name or not name.strip():
        return name
    words = name.strip().split()
    result = []
    for w in words:
        w_upper = w.upper()
        if w_upper in ("AB", "HB", "KB", "GMBH", "AS", "OY"):
            result.append(w_upper)
        elif len(w) == 1:
            result.append(w.upper())  # "P" förblir P
        else:
            result.append(w.capitalize())
    return " ".join(result)


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
        self.customer_number_international = sender_config.get(
            "customer_number_dhl_international", ""
        ) or self.customer_number
        # Länder som använder inrikes kundnr. Övriga → utrikes. Default: Norden.
        _dom = sender_config.get("customer_number_dhl_domestic_countries", None)
        self._domestic_countries = (
            {c.upper() for c in _dom} if _dom else {"SE"}
        )
        self.sender = sender_config
        self.timeout = config.get("timeout_seconds", 30)
        self.session = self._create_session(config)
        self._eid = None
        eid_user = config.get("eid_username", "").strip()
        eid_pass = config.get("eid_password", "").strip()
        if eid_user and "${" not in eid_user and eid_pass and "${" not in eid_pass:
            self._eid = {"userName": eid_user, "password": eid_pass}

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
        if response.status_code >= 400:
            try:
                err_body = response.json()
                logger.error(
                    f"DHL TransportInstruction {response.status_code}: "
                    f"{err_body.get('UserMessage', err_body.get('Message', response.text[:300]))}"
                )
            except Exception:
                logger.error(f"DHL TransportInstruction {response.status_code}: {response.text[:300]}")
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

        # Spara TI i cache: merge request (parties, etc.) med response (id, pieces med barcode)
        # Behövs för Print API och PickupRequest. Behåll ALLA pieces så flerkolli får rätt antal etiketter.
        merged = {**payload}
        merged["id"] = ti_id
        our_pieces = payload.get("pieces", [])
        if pieces and our_pieces:
            # Merga: använd DHL:s id (barcode) för varje piece, behåll våra dimensioner
            merged_pieces = []
            for i, resp_piece in enumerate(pieces):
                our_p = our_pieces[i] if i < len(our_pieces) else our_pieces[0]
                mp = {**our_p}
                mp["id"] = resp_piece.get("id", our_p.get("id", [""]))
                merged_pieces.append(mp)
            merged["pieces"] = merged_pieces
        else:
            merged["pieces"] = pieces if pieces else our_pieces
        self._ti_cache[ti_id] = merged

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
        """Hämtar etikett + fraktlista i ETT API-anrop (per DHL:s rekommendation).

        Använder printdocumentsbyid med shipmentIds + options (label, shipmentList).
        Ett anrop istället för två — DHL rekommenderar denna metod.

        Returns:
            {
                "label": bytes,               # Fraktetikett (PDF)
                "shipment_list": bytes | None  # Fraktlista (PDF) eller None
            }
        """
        logger.info(f"DHL: Hämtar alla dokument för {shipment_id} (ett anrop)")

        url = f"{self.base_url}{API_PATHS['print_by_id']}"
        payload = {
            "shipmentIds": [str(shipment_id)],
            "options": {
                "label": True,
                "shipmentList": True,
                "waybill": True,
                "guarantee": True,
                "returnLabel": True,
                "licensePlateBarCode": "GS1",
                "pageOptions": {
                    "pageType": "Label",
                    "marginLeft": 0,
                    "marginTop": 0,
                    "padding": 0,
                },
            },
        }

        response = self.session.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()

        label, shipment_list = self._extract_label_and_shipment_list(response)
        if not label:
            raise RuntimeError(
                f"DHL printdocumentsbyid: Ingen etikett i svaret för {shipment_id}"
            )
        if shipment_list:
            logger.info(f"DHL: Etikett + fraktlista hämtad ({len(label)} + {len(shipment_list)} bytes)")
        else:
            logger.info(f"DHL: Etikett hämtad ({len(label)} bytes)")

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

    def _extract_label_and_shipment_list(
        self, response: requests.Response
    ) -> tuple[bytes | None, bytes | None]:
        """Extraherar Label och ShipmentList från printdocumentsbyid-svar.

        Returns:
            (label_bytes, shipment_list_bytes) — shipment_list kan vara None.
        """
        import base64

        content_type = response.headers.get("Content-Type", "")
        if "json" not in content_type:
            return None, None

        data = response.json()
        reports = data.get("reports", [])
        label = None
        shipment_list = None

        for report in reports:
            t = report.get("type")
            content_b64 = report.get("content", "")
            if not content_b64:
                continue
            decoded = base64.b64decode(content_b64)
            if t == "Label":
                label = decoded
            elif t == "ShipmentList":
                shipment_list = decoded

        return label, shipment_list

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
    # PriceQuote API
    # ------------------------------------------------------------------

    def _build_price_quote_shipment(
        self,
        shipment: Shipment,
        additional_services: Optional[dict] = None,
        stackable: bool = True,
        loading_meters_override: Optional[float] = None,
    ) -> dict:
        """Bygger ShipmentModel enligt PriceQuote Swagger-schema."""
        recv = shipment.receiver
        if not recv:
            raise ValueError("Shipment saknar receiver")
        container = shipment.containers[0] if shipment.containers else None
        product_code = shipment.service.product_code

        weight = container.weight if container else 1.0
        volume = container.volume if container else 0.001
        copies = container.copies if container else 1
        pkg_type = container.package_code if container else "PKT"

        recv_country = (recv.country or "SE").upper()
        use_domestic = (
            recv_country in self._domestic_countries
            and product_code not in INTERNATIONAL_PRODUCTS
        )
        consignor_id = (
            self.customer_number
            if use_domestic
            else self.customer_number_international
        )
        # Utrikes kräver ofta DDP; inrikes använder 1
        payer = (
            PAYER_CODE_BY_PRODUCT.get(product_code)
            or ("DDP" if recv_country != "SE" else "1")
        )

        dhl_product = DHL_PRODUCT_CODE_FOR_QUOTE.get(
            product_code, f"DHL_{product_code}"
        )

        # Pallet-fält för 210/202
        n_half = 1 if pkg_type == "702" else 0
        n_full = copies if pkg_type == "701" else 0
        if product_code not in ("210", "202", "205", "SPI", "PPI"):
            n_half = n_full = 0
        pallet_places = n_full + 0.5 * n_half if (n_full or n_half) else 0
        # loadingMeters: override eller halvpall ~0.4, fullpall ~0.8
        if loading_meters_override is not None:
            loading_meters = loading_meters_override
        else:
            loading_meters = n_full * 0.8 + n_half * 0.4 if (n_full or n_half) else 0

        shipment_model = {
            "dhlProductCode": dhl_product,
            "totalNumberOfPieces": copies,
            "totalWeight": weight,
            "totalVolume": volume,
            "totalLoadingMeters": loading_meters,
            "totalPalletPlaces": pallet_places,
            "numberOfEURPallets": 0,
            "numberOfFullPallets": n_full,
            "numberOfHalfPallets": n_half,
            "goodsValue": "",
            "payerCode": payer,
            "importExport": "E" if recv_country != "SE" else "I",
            "piece": [
                {
                    "numberOfPieces": copies,
                    "weight": weight,
                    "volume": volume,
                    "loadingMeters": loading_meters,
                    "palletPlaces": pallet_places,
                    "width": container.width if container else 0,
                    "height": container.height if container else 0,
                    "length": container.length if container else 0,
                    "stackable": stackable,
                    "packageType": pkg_type,
                }
            ],
            "parties": [
                {
                    "id": consignor_id,
                    "name": format_sender_name(self.sender.get("name", "")),
                    "type": "Consignor",
                    "address": {
                        "street": self.sender.get("address1", ""),
                        "streetNumber": "",
                        "cityName": self.sender.get("city", ""),
                        "postalCode": clean_postal_code(
                            self.sender.get("zipcode", "")
                        ),
                        "countryCode": self.sender.get("country", "SE"),
                    },
                },
                {
                    "id": "",
                    "name": recv.name,
                    "type": "Consignee",
                    "address": {
                        "street": recv.address1,
                        "streetNumber": "",
                        "cityName": recv.city,
                        "postalCode": clean_postal_code(recv.zipcode),
                        "countryCode": recv.country or "SE",
                    },
                },
            ],
            "additionalServices": additional_services or {},
        }
        if product_code in PRODUCTS_REQUIRING_ACCESSPOINT and recv.zipcode:
            points = self.find_service_points(
                clean_postal_code(recv.zipcode),
                recv.country or "SE",
                street=recv.address1,
                city=recv.city,
                max_results=1,
            )
            if points:
                shipment_model["parties"].append(
                    self._service_point_to_access_point(points[0])
                )
        return shipment_model

    def get_price_quote(
        self,
        shipment: Shipment,
        use_gross: bool = True,
        eid: Optional[dict] = None,
        additional_services: Optional[dict] = None,
        stackable: bool = True,
        loading_meters: Optional[float] = None,
    ) -> dict:
        """Hämtar prisuppskattning via PriceQuote API.

        Endpoints:
        - quoteforgrossprice: listpris
        - quoteforprice: avtalspris (kräver ofta eID)

        Args:
            shipment: Sändning att kalkylera pris för.
            use_gross: True = quoteforgrossprice, False = quoteforprice.
            eid: Valfritt {"userName": "...", "password": "..."} för avtalspris.
            additional_services: Extra tjänster för additionalServices.
            stackable: False för ej stapelbar (halvpall).

        Returns:
            Dict med priceQuoteResult (lista: FreightCost, TotalPrice, etc.)
        """
        shipment_model = self._build_price_quote_shipment(
            shipment, additional_services, stackable, loading_meters
        )

        path_key = "price_quote_gross" if use_gross else "price_quote"
        url = f"{self.base_url}{API_PATHS[path_key]}"

        body = {
            "shipment": shipment_model,
            "ownSurCharge": {"percentage": 0, "value": 0},
        }
        eid_to_use = eid or (self._eid if not use_gross else None)
        if eid_to_use:
            body["eid"] = eid_to_use

        logger.info(
            f"DHL: Prisförfrågan för produkt {shipment.service.product_code} "
            f"till {shipment.receiver.country}"
        )
        response = self.session.post(url, json=body, timeout=self.timeout)

        if response.status_code >= 400:
            err = {}
            try:
                err = response.json()
            except Exception:
                pass
            logger.error(
                f"DHL PriceQuote {response.status_code}: {err.get('UserMessage', err.get('Message', response.text))}"
            )
        response.raise_for_status()
        data = response.json()

        result = data
        if isinstance(data, dict):
            result = data.get("priceQuoteResult", data.get("result", data))
        if isinstance(result, list):
            total = next(
                (r for r in result if r.get("id") == "TotalPrice"),
                {},
            )
            logger.info(
                f"DHL: Prisberäknad — {total.get('value', '?')} {total.get('unit', '')}"
            )
        return {"priceQuoteResult": result, "raw": data}

    # ------------------------------------------------------------------
    # ServicePointLocator API
    # ------------------------------------------------------------------

    def find_service_points(self, zipcode: str, country: str = "SE",
                            street: str = "", city: str = "",
                            max_results: int = 10) -> list:
        """Hittar närmaste DHL-ombud via ServicePointLocator API.

        POST med address i body (DHL rekommenderar hela adressen).
        Ref: Sample-findnearestservicepoints-request.txt
        """
        logger.info(f"DHL: Söker ombud nära {zipcode}, {country}")

        url = f"{self.base_url}{API_PATHS['service_points']}"
        payload = {
            "address": {
                "street": street or "Adress",
                "cityName": city or "",
                "postalCode": zipcode,
                "countryCode": country,
            },
            "maxNumberOfItems": max_results,
        }
        response = self.session.post(
            url,
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        points = response.json().get("servicePoints", [])

        logger.info(f"DHL: Hittade {len(points)} ombud")
        return points

    # ------------------------------------------------------------------
    # TimeTable API — estimerat leveransdatum
    # ------------------------------------------------------------------

    def get_estimated_delivery_date(self, shipment: Shipment) -> Optional[str]:
        """Hämtar estimerat leveransdatum via TimeTable API.

        POST /timetableapi/v1/timetable/gettimetable
        Returnerar deliveryDateString för matchande produkt, t.ex. "2026-02-28".

        Returns:
            Leveransdatum som str (YYYY-MM-DD) eller None om API-anrop misslyckas.
        """
        recv = shipment.receiver
        if not recv:
            return None
        product_code = (shipment.service.product_code or "").strip()
        if not product_code:
            return None

        sender_zip = clean_postal_code(self.sender.get("zipcode", ""))
        recv_zip = clean_postal_code(recv.zipcode)
        sender_country = (self.sender.get("country") or "SE").upper()
        recv_country = (recv.country or "SE").upper()

        # dateTime: upphämtningsdatum + tid (ISO 8601)
        shipping_date = date.today()
        if shipment.service.booking and shipment.service.booking.pickup_date:
            try:
                shipping_date = datetime.strptime(
                    shipment.service.booking.pickup_date, "%Y-%m-%d"
                ).date()
            except ValueError:
                pass
        dt = datetime(
            shipping_date.year,
            shipping_date.month,
            shipping_date.day,
            8,
            0,
            0,
            tzinfo=timezone.utc,
        )
        date_time_iso = dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        body = {
            "cityName": self.sender.get("city", ""),
            "postalCode": sender_zip,
            "countryCode": sender_country,
            "street": self.sender.get("address1", ""),
            "streetNumber": "",
            "deliveryCityName": recv.city or "",
            "deliveryPostalCode": recv_zip,
            "deliveryCountryCode": recv_country,
            "deliveryStreet": recv.address1 or "",
            "deliveryStreetNumber": "",
            "earliestSent": True,
            "dateTime": date_time_iso,
        }

        url = f"{self.base_url}{API_PATHS['timetable']}"
        params = {"productcode": product_code}

        try:
            response = self.session.post(
                url, json=body, params=params, timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.warning(f"DHL TimeTable: Kunde inte hämta leveransdatum: {e}")
            return None

        if isinstance(data, list) and data:
            item = data[0]
            delivery_str = item.get("deliveryDateString") or item.get("deliveryDate")
            if delivery_str:
                logger.info(f"DHL: Estimerat leveransdatum: {delivery_str}")
                return str(delivery_str)
        return None

    # ------------------------------------------------------------------
    # PickupRequest API
    # ------------------------------------------------------------------

    def request_pickup(self, shipment_id: str, pickup_date: str,
                       pickup_instruction: str = "") -> dict:
        """Bokar upphämtning via PickupRequest API (IFTMBF).

        DHL kräver full pickup instruction med samma struktur som TransportInstruction.
        Ref: https://dhlpaket.se/dashboard/services/api-farm/pickuprequest/

        POST /pickuprequestapi/v1/pickuprequest/pickuprequest
        """
        logger.info(f"DHL: Bokar upphämtning {shipment_id} för {pickup_date}")

        ti_data = self._ti_cache.get(shipment_id)
        if not ti_data:
            raise RuntimeError(
                f"Ingen cachad TI-data för {shipment_id}. "
                "Anropa create_shipment() först."
            )

        # Bygg full pickup instruction (IFTMBF) — DHL kräver all info
        pickup_payload = self._build_pickup_instruction(
            ti_data, shipment_id, pickup_date, pickup_instruction
        )

        url = f"{self.base_url}{API_PATHS['pickup_request']}"
        response = self.session.post(
            url,
            json=pickup_payload,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            try:
                err = response.json()
                msg = err.get("UserMessage") or err.get("Message") or err.get("message") or response.text[:500]
                logger.error(
                    f"DHL PickupRequest {response.status_code}: {msg}"
                )
            except Exception:
                logger.error(f"DHL PickupRequest {response.status_code}: {response.text[:500]}")
        response.raise_for_status()
        data = response.json()

        # Tolka status: 0/"Accepted"=OK, 1/"Rejected"=avvisad, 2/"Moved"=flyttad
        status = data.get("status", -1)
        ok = status in (0, "Accepted", "0") or (
            isinstance(status, str) and status.lower() == "accepted"
        )
        if ok:
            logger.info(f"DHL: Upphämtning bokad — {data.get('bookingNumber', '')}")
        elif status in (1, "Rejected", "1"):
            logger.warning(f"DHL: Upphämtning avvisad — {data}")
        elif status in (2, "Moved", "2"):
            logger.info(
                f"DHL: Upphämtning flyttad till annat datum — "
                f"{data.get('pickupDateTime', data.get('pickupDate', ''))}"
            )

        return data

    def _build_pickup_instruction(
        self,
        ti_data: dict,
        shipment_id: str,
        pickup_date: str,
        pickup_instruction: str,
    ) -> dict:
        """Bygger PickupRequestModel enligt DHL-exempel.

        Ref: pickupInstruction-request-service-point-103.txt
        - pickupDate: enkel datumsträng (yyyy-MM-dd)
        - Consignor id: kundnummer från sender_config
        """
        payload = dict(ti_data)
        payload["id"] = str(shipment_id)
        # DHL-exempel använder enkel datumsträng "2020-01-04"
        payload["pickupDate"] = pickup_date
        payload["pickupInstruction"] = pickup_instruction or "Upphämtning bokad via GARP"
        return payload

    # ------------------------------------------------------------------
    # Payload-bygge
    # ------------------------------------------------------------------

    @staticmethod
    def _service_point_to_access_point(sp: dict) -> dict:
        """Konverterar ServicePointLocator-svar till AccessPoint-party.

        Ref: DHL-exempel parties[].type=AccessPoint
        """
        return {
            "id": str(sp.get("id", "")),
            "type": "AccessPoint",
            "name": str(sp.get("name", "")),
            "address": {
                "street": str(sp.get("street", "")),
                "cityName": str(sp.get("cityName", "")),
                "postalCode": str(sp.get("postalCode", "")),
                "countryCode": str(sp.get("countryCode", "SE")),
            },
        }

    def _build_transport_instruction(self, shipment: Shipment) -> dict:
        """Bygger JSON-payload för TransportInstruction API.

        Verifierat format mot DHL sandbox (status 200):
        - parties[].address: nested objekt med street, cityName, postalCode, countryCode
        - För 103/104: AccessPoint hämtas via ServicePointLocator (närmaste ombud)
        - additionalServices: objekt med bool-värden
        - pieces[].id: string array ['']

        Ref: DHL Produktmanual v5.23 + verifierad sandbox-test
        """
        recv = shipment.receiver
        if not recv:
            raise ValueError(
                f"Order {shipment.order_no} saknar mottagarinfo. "
                "DHL kräver receiver i sändningen."
            )
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

        # För 103/104: hämta närmaste ombud via ServicePointLocator
        access_point = None
        if product_code in PRODUCTS_REQUIRING_ACCESSPOINT and recv.zipcode:
            points = self.find_service_points(
                recv_zip,
                recv.country or "SE",
                street=recv.address1,
                city=recv.city,
                max_results=1,
            )
            if points:
                access_point = self._service_point_to_access_point(points[0])
                logger.info(f"  Ombud: {access_point.get('name', '')} ({access_point.get('id', '')})")
            else:
                raise ValueError(
                    f"Order {shipment.order_no}: Inget DHL-ombud hittades "
                    f"nära {recv_zip}. Produkt {product_code} kräver ServicePoint."
                )

        # Consignor id: internationella produkter (109/112/202/205) använder ALLTID
        # internationellt kundnr. Övriga (102/103/210/211) baseras på domestic_countries.
        recv_country = (recv.country or "SE").upper()
        use_domestic = (
            recv_country in self._domestic_countries
            and product_code not in INTERNATIONAL_PRODUCTS
        )
        consignor_id = (
            self.customer_number
            if use_domestic
            else self.customer_number_international
        )

        # Parties — address MÅSTE vara nested objekt
        parties = [
            {
                "id": consignor_id,
                "type": "Consignor",
                "name": format_sender_name(self.sender.get("name", "")),
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
                    "countryCode": recv.country or "SE",
                },
                "phone": recv.phone,
                "email": recv.email,
            },
        ]
        if access_point:
            parties.append(access_point)

        # Pakettyp — standardmappning per produktkod
        raw_pkg = ((container.package_code if container else "") or "").upper()
        pkg_type = PACKAGE_CODE_NORMALIZE.get(raw_pkg, raw_pkg) or PACKAGE_TYPE_DEFAULTS.get(
            product_code, "PKT"
        )

        # Flerkolli: en piece per fysiskt paket så att fraktsedeln visar rätt antal
        weight_per = weight / copies if copies > 0 else weight
        volume_per = volume / copies if copies > 0 else volume
        pieces = []
        for _ in range(max(1, copies)):
            p = {
                "id": [""],
                "packageType": pkg_type,
                "numberOfPieces": 1,
                "weight": weight_per,
                "volume": volume_per,
            }
            if container and container.length > 0:
                p["length"] = container.length
            if container and container.width > 0:
                p["width"] = container.width
            if container and container.height > 0:
                p["height"] = container.height
            dg = getattr(shipment, "dangerous_goods", None)
            if dg and dg.un_number and product_code not in ("102", "103"):
                p["dangerousGoods"] = {
                    "unNumber": dg.un_number,
                    "adrClass": dg.adr_class or "",
                    "packingGroup": dg.packing_group or "",
                    "technicalName": dg.technical_name or "",
                }
                if dg.flash_point:
                    p["dangerousGoods"]["flashPoint"] = dg.flash_point
            pieces.append(p)

        # additionalServices: objekt med bool-värden
        # {"notification": true} — INTE {"notification": {}}
        # Flera addons: DHL:102:AVIS:LQ → addon="AVIS:LQ", splittar på ":"
        # DHL Paket 102/103 stöder inte farligt gods — skippa dangerousGoods
        additional_services = {}
        if shipment.service.addon:
            for part in shipment.service.addon.replace(",", ":").split(":"):
                part = part.strip().upper()
                if not part:
                    continue
                api_code = ADDON_MAPPING.get(part)
                if api_code:
                    if api_code == "dangerousGoods" and product_code in ("102", "103"):
                        continue  # Paket 102/103 stöder ej farligt gods
                    additional_services[api_code] = True

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
                "code": PAYER_CODE_BY_PRODUCT.get(product_code, "1"),
                "location": "",
            },
            "parties": parties,
            "additionalServices": additional_services,
            "pieces": pieces,
        }

        return payload
