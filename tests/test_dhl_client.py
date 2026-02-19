"""Tester for DHL-klienten.

Testar payload-bygge och svar-parsning utan att anropa riktigt API.
"""

import pytest
import json
import base64
from unittest.mock import MagicMock, patch

from src.carriers.dhl import DHLClient, ADDON_MAPPING, API_PATHS, clean_postal_code, PACKAGE_TYPE_DEFAULTS
from src.parsers.models import (
    Shipment, Receiver, Container, ServiceInfo, BookingInfo,
    Notification, CarrierType,
)


@pytest.fixture
def dhl_config():
    return {
        "base_url": "https://test-api.freight-logistics.dhl.com",
        "api_key": "test-key-1234",
        "timeout_seconds": 10,
        "retry_attempts": 1,
        "retry_delay_seconds": 1,
    }


@pytest.fixture
def sender_config():
    return {
        "name": "Ernst P AB",
        "address1": "Mobelgatan 5",
        "zipcode": "43133",
        "city": "Molndal",
        "country": "SE",
        "phone": "+46317030770",
        "email": "order@ernstp.se",
        "customer_number_dhl": "101733",
    }


@pytest.fixture
def client(dhl_config, sender_config):
    return DHLClient(dhl_config, sender_config)


@pytest.fixture
def sample_shipment():
    return Shipment(
        order_no="107739-132888",
        sender_name="Ernst P AB",
        reference="107739-132888",
        term_code="S",
        delivery_instruction="Lamna vid dorren",
        service=ServiceInfo(
            carrier=CarrierType.DHL,
            product_code="102",
            addon="",
            raw_srvid="DHL:102",
            booking=BookingInfo(pickup_booking=True, pickup_date="2026-02-19"),
        ),
        receiver=Receiver(
            rcvid="7631",
            name="Test Mottagare AB",
            address1="Kungsgatan 1",
            zipcode="41101",
            city="Goteborg",
            country="SE",
            phone="+46701234567",
            email="test@test.se",
        ),
        containers=[
            Container(
                container_type="parcel",
                copies=1,
                package_code="PKT",
                weight=5.5,
                volume=0.004,
                length=20,
                width=20,
                height=10,
            )
        ],
    )


class TestBuildTransportInstruction:
    """Testar payload-bygge for TransportInstruction API."""

    def test_basic_payload_structure(self, client, sample_shipment):
        payload = client._build_transport_instruction(sample_shipment)

        assert payload["productCode"] == "102"
        assert payload["shippingDate"] == "2026-02-19"
        assert payload["totalWeight"] == 5.5
        assert payload["totalVolume"] == 0.004
        assert payload["totalNumberOfPieces"] == 1

    def test_parties_nested_address(self, client, sample_shipment):
        """Address MASTE vara nested objekt under parties."""
        payload = client._build_transport_instruction(sample_shipment)
        parties = payload["parties"]

        # Consignor
        consignor = parties[0]
        assert consignor["type"] == "Consignor"
        assert consignor["id"] == "101733"
        assert consignor["name"] == "Ernst P AB"
        assert "address" in consignor
        assert consignor["address"]["street"] == "Mobelgatan 5"
        assert consignor["address"]["cityName"] == "Molndal"
        assert consignor["address"]["postalCode"] == "43133"
        assert consignor["address"]["countryCode"] == "SE"
        # Street ska INTE finnas direkt pa party-nivå
        assert "street" not in consignor

        # Consignee
        consignee = parties[1]
        assert consignee["type"] == "Consignee"
        assert consignee["name"] == "Test Mottagare AB"
        assert "address" in consignee
        assert consignee["address"]["street"] == "Kungsgatan 1"
        assert consignee["address"]["postalCode"] == "41101"

    def test_references_are_string_array(self, client, sample_shipment):
        """References ska vara string array, inte objekt-array."""
        payload = client._build_transport_instruction(sample_shipment)
        refs = payload["parties"][0]["references"]

        assert isinstance(refs, list)
        assert all(isinstance(r, str) for r in refs)
        assert refs == ["107739-132888"]

    def test_additional_services_is_object(self, client, sample_shipment):
        """additionalServices MASTE vara objekt {}, ej array []."""
        payload = client._build_transport_instruction(sample_shipment)
        assert isinstance(payload["additionalServices"], dict)

    def test_additional_services_empty(self, client, sample_shipment):
        """Utan addon ska additionalServices vara tomt objekt."""
        sample_shipment.service.addon = ""
        payload = client._build_transport_instruction(sample_shipment)
        assert payload["additionalServices"] == {}

    def test_additional_services_with_addon(self, client, sample_shipment):
        """Med addon ska additionalServices ha rätt nyckel med True-värde."""
        sample_shipment.service.addon = "AVIS"
        payload = client._build_transport_instruction(sample_shipment)
        assert payload["additionalServices"]["notification"] is True

    def test_pieces_id_is_string_array(self, client, sample_shipment):
        """pieces[].id ska vara string array ['']."""
        payload = client._build_transport_instruction(sample_shipment)
        piece_id = payload["pieces"][0]["id"]
        assert isinstance(piece_id, list)
        assert piece_id == [""]

    def test_pieces_dimensions(self, client, sample_shipment):
        """Dimensioner ska inkluderas om de finns."""
        payload = client._build_transport_instruction(sample_shipment)
        piece = payload["pieces"][0]
        assert piece["length"] == 20
        assert piece["width"] == 20
        assert piece["height"] == 10
        assert piece["weight"] == 5.5
        assert piece["volume"] == 0.004

    def test_pieces_no_dimensions(self, client, sample_shipment):
        """Utan dimensioner ska de inte inkluderas."""
        sample_shipment.containers[0].length = 0
        sample_shipment.containers[0].width = 0
        sample_shipment.containers[0].height = 0
        payload = client._build_transport_instruction(sample_shipment)
        piece = payload["pieces"][0]
        assert "length" not in piece
        assert "width" not in piece
        assert "height" not in piece

    def test_payer_code(self, client, sample_shipment):
        payload = client._build_transport_instruction(sample_shipment)
        assert payload["payerCode"]["code"] == "1"

    def test_booking_date_as_shipping_date(self, client, sample_shipment):
        """Om bokning finns, anvand pickup_date som shippingDate."""
        payload = client._build_transport_instruction(sample_shipment)
        assert payload["shippingDate"] == "2026-02-19"

    def test_no_booking_uses_today(self, client, sample_shipment):
        """Utan bokning, anvand dagens datum."""
        sample_shipment.service.booking = None
        payload = client._build_transport_instruction(sample_shipment)
        from datetime import date
        assert payload["shippingDate"] == date.today().isoformat()

    def test_no_container_defaults(self, client, sample_shipment):
        """Utan container, anvand standardvarden."""
        sample_shipment.containers = []
        payload = client._build_transport_instruction(sample_shipment)
        assert payload["totalWeight"] == 1.0
        assert payload["totalVolume"] == 0.001
        assert payload["pieces"][0]["packageType"] == "PKT"


class TestCreateShipmentResponseParsing:
    """Testar parsning av TransportInstruction-svar."""

    def test_parse_nested_response(self, client):
        """Svaret wrappas i transportInstruction."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "Succes",
            "transportInstruction": {
                "id": "2906212275",
                "productCode": "102",
                "pieces": [
                    {"id": ["373221512524402940"], "packageType": "PKT"}
                ],
                "routingCode": "2LSE41101+02000000",
            },
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.session, "post", return_value=mock_response):
            shipment = Shipment(
                order_no="TEST",
                service=ServiceInfo(carrier=CarrierType.DHL, product_code="102"),
                receiver=Receiver(name="Test", address1="Test 1", zipcode="11111", city="Test", country="SE"),
            )
            result = client.create_shipment(shipment)

        assert result["shipment_id"] == "2906212275"
        assert result["tracking_number"] == "373221512524402940"

    def test_ti_data_cached(self, client):
        """TI-data ska cachas for Print API."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "Succes",
            "transportInstruction": {
                "id": "12345",
                "pieces": [{"id": ["BARCODE123"]}],
            },
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.session, "post", return_value=mock_response):
            shipment = Shipment(
                order_no="TEST",
                service=ServiceInfo(carrier=CarrierType.DHL, product_code="102"),
                receiver=Receiver(name="Test", address1="Test 1", zipcode="11111", city="Test", country="SE"),
            )
            client.create_shipment(shipment)

        assert "12345" in client._ti_cache
        assert client._ti_cache["12345"]["id"] == "12345"


class TestExtractLabelFromResponse:
    """Testar parsning av Print API-svar."""

    def test_json_with_reports(self, client):
        """Normalt svar: JSON med reports och base64-content."""
        pdf_content = b"%PDF-1.6 test content"
        b64_content = base64.b64encode(pdf_content).decode()

        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {
            "reports": [{
                "name": "label_12345.pdf",
                "content": b64_content,
                "contentType": "application/pdf",
                "type": "Label",
                "valid": True,
            }]
        }

        result = client._extract_label_from_response(mock_response, "test")
        assert result == pdf_content

    def test_json_empty_reports_raises(self, client):
        """Tomt reports-svar ska ge RuntimeError."""
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"reports": []}
        mock_response.text = '{"reports": []}'

        with pytest.raises(RuntimeError, match="inga reports"):
            client._extract_label_from_response(mock_response, "test")

    def test_binary_pdf_response(self, client):
        """Direkt PDF-svar (inte JSON)."""
        pdf_content = b"%PDF-1.6 binary content"
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "application/pdf"}
        mock_response.content = pdf_content

        result = client._extract_label_from_response(mock_response, "test")
        assert result == pdf_content

    def test_multiple_reports_picks_label(self, client):
        """Med flera reports, välj type=Label."""
        label_content = b"LABEL PDF"
        list_content = b"LIST PDF"

        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {
            "reports": [
                {
                    "name": "shipmentlist.pdf",
                    "content": base64.b64encode(list_content).decode(),
                    "contentType": "application/pdf",
                    "type": "ShipmentList",
                    "valid": True,
                },
                {
                    "name": "label.pdf",
                    "content": base64.b64encode(label_content).decode(),
                    "contentType": "application/pdf",
                    "type": "Label",
                    "valid": True,
                },
            ]
        }

        result = client._extract_label_from_response(mock_response, "test")
        assert result == label_content


class TestAPIURLs:
    """Verifiera att API-sökvägar stämmer."""

    def test_transport_instruction_url(self):
        assert "/transportinstructionapi/v1/" in API_PATHS["transport_instruction"]

    def test_print_documents_url(self):
        assert "/printapi/v1/" in API_PATHS["print_documents"]

    def test_service_points_url(self):
        assert "/servicepointlocatorapi/v1/" in API_PATHS["service_points"]

    def test_pickup_request_url(self):
        assert "/pickuprequestapi/v1/" in API_PATHS["pickup_request"]


class TestAddonMapping:
    """Verifiera tilläggstjänst-mappning."""

    def test_avis_maps_to_notification(self):
        assert ADDON_MAPPING["AVIS"] == "notification"

    def test_known_addons(self):
        expected = {
            "notification", "preAdviceDelivery", "tailLiftUnloading",
            "tailLiftLoading", "indoorDelivery", "dangerousGoods",
            "insurance", "collectionAtTerminal", "nonStackable",
        }
        assert expected.issubset(set(ADDON_MAPPING.values()))


class TestCleanPostalCode:
    """Testar postnummer-rensning."""

    def test_normal_se_zip(self):
        assert clean_postal_code("43133") == "43133"

    def test_dk_prefix(self):
        assert clean_postal_code("DK-5220") == "5220"

    def test_no_prefix(self):
        assert clean_postal_code("NO-1234") == "1234"

    def test_fi_prefix(self):
        assert clean_postal_code("FI-00100") == "00100"

    def test_whitespace(self):
        assert clean_postal_code("  43133  ") == "43133"

    def test_dk_prefix_with_whitespace(self):
        assert clean_postal_code("  DK-5220  ") == "5220"

    def test_short_zip_no_strip(self):
        """Kort postnummer utan prefix ska inte strippas."""
        assert clean_postal_code("123") == "123"


class TestPackageTypeDefaults:
    """Testar pakettyps-mappning."""

    def test_pall_default(self):
        assert PACKAGE_TYPE_DEFAULTS["210"] == "701"

    def test_paket_not_in_defaults(self):
        """Produkt 102 har inget default — ska falla tillbaka till PKT."""
        assert "102" not in PACKAGE_TYPE_DEFAULTS

    def test_payload_pall_package_type(self, client, sample_shipment):
        """Produkt 210 utan packagecode ska ge 701."""
        sample_shipment.service.product_code = "210"
        sample_shipment.containers[0].package_code = ""
        payload = client._build_transport_instruction(sample_shipment)
        assert payload["pieces"][0]["packageType"] == "701"

    def test_payload_explicit_package_code(self, client, sample_shipment):
        """Explicit packagecode ska användas oavsett produkt."""
        sample_shipment.service.product_code = "210"
        sample_shipment.containers[0].package_code = "702"
        payload = client._build_transport_instruction(sample_shipment)
        assert payload["pieces"][0]["packageType"] == "702"


class TestExtractDocumentFromResponse:
    """Testar parsning av specifik dokumenttyp från Print API-svar."""

    def test_extract_shipment_list(self, client):
        """Ska kunna extrahera ShipmentList från reports."""
        list_content = b"SHIPMENT LIST PDF"

        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {
            "reports": [{
                "name": "shipmentlist.pdf",
                "content": base64.b64encode(list_content).decode(),
                "contentType": "application/pdf",
                "type": "ShipmentList",
                "valid": True,
            }]
        }

        result = client._extract_document_from_response(mock_response, "ShipmentList")
        assert result == list_content

    def test_extract_missing_type_returns_none(self, client):
        """Om typ inte finns ska None returneras."""
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {
            "reports": [{
                "name": "label.pdf",
                "content": base64.b64encode(b"LABEL").decode(),
                "type": "Label",
            }]
        }

        result = client._extract_document_from_response(mock_response, "ShipmentList")
        assert result is None

    def test_extract_non_json_returns_none(self, client):
        """Om svaret inte är JSON ska None returneras."""
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "application/pdf"}

        result = client._extract_document_from_response(mock_response, "ShipmentList")
        assert result is None


class TestGetAllDocuments:
    """Testar hämtning av alla dokument (label + shipmentList)."""

    def test_returns_label_and_list(self, client):
        """Ska returnera label och shipmentList."""
        label_content = b"LABEL PDF"
        list_content = b"LIST PDF"

        # Lägg till TI-data i cache
        client._ti_cache["12345"] = {"id": "12345", "pieces": []}

        # Mock label-anrop
        label_response = MagicMock()
        label_response.headers = {"Content-Type": "application/json"}
        label_response.json.return_value = {
            "reports": [{
                "content": base64.b64encode(label_content).decode(),
                "type": "Label",
            }]
        }
        label_response.raise_for_status = MagicMock()

        # Mock list-anrop
        list_response = MagicMock()
        list_response.headers = {"Content-Type": "application/json"}
        list_response.json.return_value = {
            "reports": [{
                "content": base64.b64encode(list_content).decode(),
                "type": "ShipmentList",
            }]
        }
        list_response.raise_for_status = MagicMock()

        with patch.object(client.session, "post", side_effect=[label_response, list_response]):
            result = client.get_all_documents("12345")

        assert result["label"] == label_content
        assert result["shipment_list"] == list_content

    def test_returns_label_only_if_no_list(self, client):
        """Ska returnera label med shipment_list=None om ej tillgänglig."""
        label_content = b"LABEL PDF"

        client._ti_cache["12345"] = {"id": "12345", "pieces": []}

        label_response = MagicMock()
        label_response.headers = {"Content-Type": "application/json"}
        label_response.json.return_value = {
            "reports": [{
                "content": base64.b64encode(label_content).decode(),
                "type": "Label",
            }]
        }
        label_response.raise_for_status = MagicMock()

        # List-anrop misslyckas
        list_response = MagicMock()
        list_response.raise_for_status.side_effect = Exception("400 Bad Request")

        with patch.object(client.session, "post", side_effect=[label_response, list_response]):
            result = client.get_all_documents("12345")

        assert result["label"] == label_content
        assert result["shipment_list"] is None

    def test_no_cache_raises(self, client):
        """Utan cachad TI-data ska RuntimeError kastas."""
        with pytest.raises(RuntimeError, match="Ingen cachad TI-data"):
            client.get_all_documents("nonexistent")


class TestPostalCodeInPayload:
    """Testar att postnummer rensas i payload."""

    def test_dk_receiver_postal_code(self, client, sample_shipment):
        """DK-prefix ska rensas i Consignee."""
        sample_shipment.receiver.zipcode = "DK-5220"
        payload = client._build_transport_instruction(sample_shipment)
        assert payload["parties"][1]["address"]["postalCode"] == "5220"

    def test_normal_se_postal_code(self, client, sample_shipment):
        """SE-postnummer utan prefix ska vara oförändrat."""
        sample_shipment.receiver.zipcode = "41101"
        payload = client._build_transport_instruction(sample_shipment)
        assert payload["parties"][1]["address"]["postalCode"] == "41101"

    def test_zero_volume_gets_minimum(self, client, sample_shipment):
        """Volym 0.0 ska sättas till minimum 0.001."""
        sample_shipment.containers[0].volume = 0.0
        payload = client._build_transport_instruction(sample_shipment)
        assert payload["totalVolume"] == 0.001
