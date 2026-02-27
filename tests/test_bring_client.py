"""Tester för Bring Booking API-klient."""

import pytest
from unittest.mock import MagicMock, patch
import base64

from src.carriers.bring import BringClient, BRING_SERVICES, _clean_postal
from src.parsers.models import Shipment, Receiver, Container, ServiceInfo, CarrierType


SENDER = {
    "name": "Ernst P AB",
    "address1": "Möbelgatan 5",
    "zipcode": "43133",
    "city": "Mölndal",
    "country": "SE",
    "phone": "+46317030770",
    "email": "order@ernstp.se",
}

BRING_CONFIG = {
    "api_uid": "test@example.com",
    "api_key": "test-api-key",
    "customer_number": "12345",
    "consolidated_shipment_id": "CS059102945NO",
    "test_mode": True,
    "timeout_seconds": 30,
}


@pytest.fixture
def bring_client():
    return BringClient(BRING_CONFIG, SENDER)


class TestBuildBookingPayload:
    """Tester för _build_booking_payload."""

    def test_basic_payload_structure(self, bring_client):
        shipment = Shipment(
            order_no="ORD-001",
            reference="REF-001",
            receiver=Receiver(
                name="Norsk Kund AS",
                address1="Karl Johans gate 15",
                zipcode="0154",
                city="OSLO",
                country="NO",
                email="kund@example.no",
            ),
            service=ServiceInfo(carrier=CarrierType.BRING, product_code="0342"),
            containers=[Container(weight=5.0, length=20, width=15, height=5)],
        )

        payload = bring_client._build_booking_payload(shipment, "PICKUP_PARCEL_BULK")

        assert payload["schemaVersion"] == 1
        assert len(payload["consignments"]) == 1
        cons = payload["consignments"][0]
        assert "shippingDateTime" in cons
        assert cons["product"]["id"] == "PICKUP_PARCEL_BULK"
        assert cons["product"]["customerNumber"] == "12345"
        assert len(cons["parties"]["sender"]["addressLine"]) > 0
        assert cons["parties"]["recipient"]["name"] == "Norsk Kund AS"
        assert cons["parties"]["recipient"]["countryCode"] == "NO"
        assert cons["packages"][0]["weightInKg"] == 5.0

    def test_dimensions_from_container(self, bring_client):
        shipment = Shipment(
            order_no="ORD-002",
            receiver=Receiver(
                name="Test", address1="Adr 1", zipcode="0150",
                city="Oslo", country="NO",
            ),
            service=ServiceInfo(carrier=CarrierType.BRING, product_code="0332"),
            containers=[Container(weight=3.0, length=30, width=20, height=10)],
        )

        payload = bring_client._build_booking_payload(shipment, "BUSINESS_PARCEL_BULK")

        pkg = payload["consignments"][0]["packages"][0]
        assert pkg["dimensions"]["lengthInCm"] == 30
        assert pkg["dimensions"]["widthInCm"] == 20
        assert pkg["dimensions"]["heightInCm"] == 10

    def test_no_receiver_raises(self, bring_client):
        shipment = Shipment(
            order_no="ORD-003",
            receiver=None,
            service=ServiceInfo(carrier=CarrierType.BRING, product_code="0342"),
        )

        with pytest.raises(ValueError, match="saknar mottagarinfo"):
            bring_client._build_booking_payload(shipment, "PICKUP_PARCEL_BULK")

    def test_bulk_requires_consolidated_id(self, bring_client):
        """Bulk-produkter kräver consolidatedShipmentId."""
        config_no_bulk = {**BRING_CONFIG, "consolidated_shipment_id": ""}
        client = BringClient(config_no_bulk, SENDER)
        shipment = Shipment(
            order_no="ORD-X",
            receiver=Receiver(name="K", address1="A", zipcode="0150", city="Oslo", country="NO"),
            service=ServiceInfo(carrier=CarrierType.BRING, product_code="0342", addon=""),
        )
        with pytest.raises(ValueError, match="kräver bulk-ID"):
            client._build_booking_payload(shipment, "PICKUP_PARCEL_BULK")

    def test_bulk_id_from_addon(self, bring_client):
        """Bulk-ID kan anges i srvid-addon: BRING:0342:CS12345678."""
        config_no_bulk = {**BRING_CONFIG, "consolidated_shipment_id": ""}
        client = BringClient(config_no_bulk, SENDER)
        shipment = Shipment(
            order_no="ORD-Y",
            receiver=Receiver(name="K", address1="A", zipcode="0150", city="Oslo", country="NO"),
            service=ServiceInfo(carrier=CarrierType.BRING, product_code="0342", addon="CS12345678NO"),
        )
        payload = client._build_booking_payload(shipment, "PICKUP_PARCEL_BULK")
        assert payload["consignments"][0]["references"]["consolidatedShipmentId"] == "CS12345678NO"

    def test_lq_adds_additional_service_0003(self, bring_client):
        """LQ i addon lägger till additionalService 0003 (begränsad mängd)."""
        shipment = Shipment(
            order_no="ORD-LQ",
            receiver=Receiver(name="K", address1="A", zipcode="0150", city="Oslo", country="NO"),
            service=ServiceInfo(carrier=CarrierType.BRING, product_code="0332", addon="LQ"),
        )
        payload = bring_client._build_booking_payload(shipment, "BUSINESS_PARCEL_BULK")
        ids = [s["id"] for s in payload["consignments"][0]["product"]["additionalServices"]]
        assert "0003" in ids

    def test_volume_gt_zero_adds_lq_for_bring_0332(self, bring_client):
        """GARP workaround: volume > 0 aktiverar LQ (additionalService 0003)."""
        shipment = Shipment(
            order_no="ORD-VOL",
            receiver=Receiver(name="K", address1="A", zipcode="0150", city="Oslo", country="NO"),
            service=ServiceInfo(carrier=CarrierType.BRING, product_code="0332", addon=""),
            containers=[Container(weight=8.0, volume=4.0)],
        )
        payload = bring_client._build_booking_payload(shipment, "BUSINESS_PARCEL_BULK")
        ids = [s["id"] for s in payload["consignments"][0]["product"]["additionalServices"]]
        assert "0003" in ids

    def test_volume_zero_no_lq(self, bring_client):
        """volume=0 ger INGET LQ."""
        shipment = Shipment(
            order_no="ORD-NO-LQ",
            receiver=Receiver(name="K", address1="A", zipcode="0150", city="Oslo", country="NO"),
            service=ServiceInfo(carrier=CarrierType.BRING, product_code="0332", addon=""),
            containers=[Container(weight=16.0, volume=0.0)],
        )
        payload = bring_client._build_booking_payload(shipment, "BUSINESS_PARCEL_BULK")
        ids = [s["id"] for s in payload["consignments"][0]["product"]["additionalServices"]]
        assert "0003" not in ids

    def test_use_volume_for_lq_false_disables_volume_lq(self, bring_client):
        """use_volume_for_lq: false → volume påverkar inte LQ (endast 0332/0342)."""
        config = {**BRING_CONFIG, "use_volume_for_lq": False}
        client = BringClient(config, SENDER)
        shipment = Shipment(
            order_no="ORD-VOL-OFF",
            receiver=Receiver(name="K", address1="A", zipcode="0150", city="Oslo", country="NO"),
            service=ServiceInfo(carrier=CarrierType.BRING, product_code="0332", addon=""),
            containers=[Container(weight=8.0, volume=4.0)],
        )
        payload = client._build_booking_payload(shipment, "BUSINESS_PARCEL_BULK")
        ids = [s["id"] for s in payload["consignments"][0]["product"]["additionalServices"]]
        assert "0003" not in ids

    def test_bulk_id_and_lq_combined(self, bring_client):
        """Addon kan kombinera bulk-ID och LQ: BRING:0332:CS123:LQ."""
        config_no_bulk = {**BRING_CONFIG, "consolidated_shipment_id": ""}
        client = BringClient(config_no_bulk, SENDER)
        shipment = Shipment(
            order_no="ORD-C",
            receiver=Receiver(name="K", address1="A", zipcode="0150", city="Oslo", country="NO"),
            service=ServiceInfo(carrier=CarrierType.BRING, product_code="0332", addon="CS12345678NO:LQ"),
        )
        payload = client._build_booking_payload(shipment, "BUSINESS_PARCEL_BULK")
        assert payload["consignments"][0]["references"]["consolidatedShipmentId"] == "CS12345678NO"
        ids = [s["id"] for s in payload["consignments"][0]["product"]["additionalServices"]]
        assert "0003" in ids


class TestCreateShipment:
    """Tester för create_shipment (mockar API)."""

    def test_create_shipment_returns_label_and_tracking(self, bring_client):
        shipment = Shipment(
            order_no="ORD-004",
            receiver=Receiver(
                name="Kund", address1="Gate 1", zipcode="0150",
                city="Oslo", country="NO",
            ),
            service=ServiceInfo(carrier=CarrierType.BRING, product_code="0342"),
            containers=[Container(weight=2.0)],
        )

        mock_response = {
            "consignments": [
                {
                    "confirmation": {"consignmentNumber": "CONS-12345"},
                    "packages": [{"packageNumber": "TRACK-67890"}],
                    "labels": {"base64": base64.b64encode(b"fake-pdf-content").decode()},
                }
            ]
        }

        with patch.object(bring_client.session, "post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_response
            mock_post.return_value.raise_for_status = MagicMock()

            result = bring_client.create_shipment(shipment)

        assert result["shipment_id"] == "CONS-12345"
        assert result["tracking_number"] == "TRACK-67890"
        assert result["label_data"] == b"fake-pdf-content"
        assert result["label_format"] == "pdf"

    def test_create_shipment_label_from_link(self, bring_client):
        shipment = Shipment(
            order_no="ORD-005",
            receiver=Receiver(
                name="Kund", address1="Gate 1", zipcode="0150",
                city="Oslo", country="NO",
            ),
            service=ServiceInfo(carrier=CarrierType.BRING, product_code="0342"),
            containers=[Container(weight=1.0)],
        )

        mock_response = {
            "consignments": [
                {
                    "confirmation": {"consignmentNumber": "C1"},
                    "packages": [{"packageNumber": "T1"}],
                    "labels": {"link": "https://example.com/label.pdf"},
                }
            ]
        }

        with patch.object(bring_client.session, "post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_response
            mock_post.return_value.raise_for_status = MagicMock()

            with patch.object(bring_client.session, "get") as mock_get:
                mock_get.return_value.status_code = 200
                mock_get.return_value.content = b"pdf-from-url"
                mock_get.return_value.raise_for_status = MagicMock()

                result = bring_client.create_shipment(shipment)

        assert result["label_data"] == b"pdf-from-url"


class TestBringServices:
    def test_service_mapping(self):
        assert BRING_SERVICES["0342"] == "PICKUP_PARCEL_BULK"
        assert BRING_SERVICES["0332"] == "BUSINESS_PARCEL_BULK"
        assert BRING_SERVICES["PICKUP_PARCEL_BULK"] == "PICKUP_PARCEL_BULK"


class TestCleanPostal:
    def test_normal_zip(self):
        assert _clean_postal("0154") == "0154"

    def test_strip_whitespace(self):
        assert _clean_postal("  0154  ") == "0154"

    def test_dk_prefix_stripped(self):
        assert _clean_postal("DK-1002") == "1002"
