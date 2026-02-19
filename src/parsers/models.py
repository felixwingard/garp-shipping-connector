"""Datamodeller för fraktsändningar."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


class CarrierType(Enum):
    DHL = "DHL"
    POSTNORD = "PN"


@dataclass
class Receiver:
    rcvid: str = ""
    name: str = ""
    address1: str = ""
    address2: str = ""
    zipcode: str = ""
    city: str = ""
    country: str = ""
    phone: str = ""
    email: str = ""
    contact: str = ""
    sms: str = ""


@dataclass
class Container:
    container_type: str = "parcel"
    measure: str = ""
    copies: int = 1
    package_code: str = "PC"
    contents: str = ""
    weight: float = 0.0
    volume: float = 0.0
    length: float = 0.0
    width: float = 0.0
    height: float = 0.0


@dataclass
class BookingInfo:
    pickup_booking: bool = False
    pickup_date: str = ""


@dataclass
class Notification:
    opt_id: str = ""
    message: str = ""


@dataclass
class ServiceInfo:
    """Tjänsteinformation parsad från srvid.

    srvid-format i XML: "TRANSPORTÖR:PRODUKTKOD[:TILLÄGG]"
    Exempel: "DHL:104", "DHL:103", "DHL:104:AVIS", "PN:19"
    """
    carrier: CarrierType = CarrierType.DHL
    product_code: str = ""
    addon: str = ""
    raw_srvid: str = ""
    booking: Optional[BookingInfo] = None


@dataclass
class Shipment:
    order_no: str = ""
    sender_name: str = ""
    reference: str = ""
    term_code: str = ""
    service: Optional[ServiceInfo] = None
    receiver: Optional[Receiver] = None
    containers: list[Container] = field(default_factory=list)
    notifications: list[Notification] = field(default_factory=list)
    delivery_instruction: str = ""

    # Fylls i efter API-anrop
    tracking_number: str = ""
    shipment_id: str = ""
    label_data: bytes = b""
    label_format: str = ""
