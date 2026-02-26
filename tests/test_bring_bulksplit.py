"""Tester för Bring Bulksplit API-klient."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from src.carriers.bring_bulksplit import BringBulksplitClient


SENDER = {
    "name": "Ernst P AB",
    "address1": "Möbelgatan 5",
    "zipcode": "43133",
    "city": "Mölndal",
    "country": "SE",
}

BULK_CONFIG = {
    "api_uid": "test@example.com",
    "api_key": "test-key",
    "customer_number": "20000199339",
    "test_mode": True,
    "timeout_seconds": 30,
}


@pytest.fixture
def bulksplit_client():
    return BringBulksplitClient(BULK_CONFIG, SENDER)


class TestListTerminals:
    def test_list_terminals_returns_terminals(self, bulksplit_client):
        with patch.object(bulksplit_client._session, "get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "terminals": [
                    {"id": "NO_OSLO_1", "name": "Østlandsterminalen", "city": "Oslo", "countryCode": "NO"},
                    {"id": "SE_JONKOPING_24", "name": "Bring", "city": "Jönköping", "countryCode": "SE"},
                ]
            }
            result = bulksplit_client.list_terminals()
            assert len(result) == 2
            assert result[0]["id"] == "NO_OSLO_1"
            assert result[0]["countryCode"] == "NO"


class TestReserveBulkId:
    def test_reserve_returns_bulk_id(self, bulksplit_client):
        with patch.object(bulksplit_client._session, "post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"bulkShipmentId": "CS059102945NO"}
            result = bulksplit_client.reserve_bulk_id("NO_OSLO_1")
            assert result == "CS059102945NO"

    def test_reserve_without_customer_number_raises(self):
        config = {**BULK_CONFIG, "customer_number": ""}
        client = BringBulksplitClient(config, SENDER)
        with pytest.raises(ValueError, match="customer_number"):
            client.reserve_bulk_id("NO_OSLO_1")

    def test_reserve_api_error_raises_runtime_error(self, bulksplit_client):
        with patch.object(bulksplit_client._session, "post") as mock_post:
            mock_post.return_value.status_code = 400
            mock_post.return_value.json.return_value = {"message": "Invalid terminal"}
            with pytest.raises(RuntimeError, match="Bring Bulksplit"):
                bulksplit_client.reserve_bulk_id("NO_OSLO_1")


class TestRegisterBulkShipment:
    def test_register_payload_structure(self, bulksplit_client):
        with patch.object(bulksplit_client._session, "post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "bulkShipmentId": "CS059102945NO",
                "waybillUrl": "https://api.bring.com/labels/xxx.pdf",
                "routingLabelsUrl": "https://api.bring.com/labels/yyy.pdf",
            }
            result = bulksplit_client.register_bulk_shipment(
                bulk_shipment_id="CS059102945NO",
                total_weight_kg=50,
            )
            assert result["bulkShipmentId"] == "CS059102945NO"
            assert "waybillUrl" in result
            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            assert "pallets" in payload
            assert payload["pallets"][0]["totalWeightKg"] == 50
            assert payload["pallets"][0]["services"] == ["0332"]
            assert "shippingDateTime" in payload

    def test_register_with_num_packages(self, bulksplit_client):
        with patch.object(bulksplit_client._session, "post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"bulkShipmentId": "CS123", "waybillUrl": "", "routingLabelsUrl": ""}
            bulksplit_client.register_bulk_shipment(
                bulk_shipment_id="CS123",
                total_weight_kg=25,
                num_packages=5,
            )
            payload = mock_post.call_args.kwargs["json"]
            assert payload["pallets"][0]["numberOfPackages"] == 5
