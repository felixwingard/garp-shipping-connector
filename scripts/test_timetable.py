#!/usr/bin/env python3
"""Testar DHL TimeTable API — hämtar estimerat leveransdatum utan att skapa sändning."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    from src.utils.config import load_config, get_config_path
    from src.parsers.models import Shipment, Receiver, ServiceInfo
    from src.parsers.models import CarrierType
    from src.carriers.dhl import DHLClient

    config_path = get_config_path()
    if not config_path.exists():
        print("Saknar config/config.yaml")
        return 1

    config = load_config()
    sender = config["sender"]
    dhl = DHLClient(config["dhl"], sender)

    # Testshipment — svensk mottagare (DHL 103 = ServicePoint)
    receiver = Receiver(
        name="Test Kund",
        address1="Boarps backar 149",
        zipcode="264 94",
        city="Klippan",
        country="SE",
        email="test@example.com",
    )
    shipment = Shipment(
        order_no="W66344-133251",
        service=ServiceInfo(carrier=CarrierType.DHL, product_code="103"),
        receiver=receiver,
    )
    if shipment.service.booking is None:
        from src.parsers.models import BookingInfo
        shipment.service.booking = BookingInfo(pickup_booking=True, pickup_date="2026-02-26")

    print("Anropar DHL TimeTable API...")
    print(f"  Från: {sender.get('city')} {sender.get('zipcode')} ({sender.get('country')})")
    print(f"  Till: {receiver.city} {receiver.zipcode} ({receiver.country})")
    print(f"  Produkt: {shipment.service.product_code}")
    print()

    date_str = dhl.get_estimated_delivery_date(shipment)
    if date_str:
        print(f"✓ Estimerat leveransdatum: {date_str}")
        return 0
    else:
        print("✗ Inget leveransdatum returnerades")
        return 1


if __name__ == "__main__":
    sys.exit(main())
