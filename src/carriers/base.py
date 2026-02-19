"""Abstrakt basklass för transportörklienter."""

from abc import ABC, abstractmethod
from ..parsers.models import Shipment


class CarrierClient(ABC):
    """Basklass som alla transportörklienter implementerar."""

    @abstractmethod
    def create_shipment(self, shipment: Shipment) -> dict:
        """Skapar en sändning hos transportören.

        Returns:
            dict med minst:
                "shipment_id": str
                "tracking_number": str
                "label_data": bytes
                "label_format": str  ("zpl" eller "pdf")
        """

    @abstractmethod
    def get_label(self, shipment_id: str, label_format: str = "zpl") -> bytes:
        """Hämtar fraktsedel för en sändning."""
