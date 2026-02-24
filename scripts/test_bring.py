#!/usr/bin/env python3
"""Test av Bring Booking API — skapa test-sändning i sandbox.

Användning:
  python scripts/test_bring.py              # Testa med sample_bring_norge.xml
  python scripts/test_bring.py --product 0332
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import load_config
from src.parsers.xml_parser import GarpXMLParser
from src.carriers.bring import BringClient


def main():
    parser = argparse.ArgumentParser(description="Test Bring API")
    parser.add_argument(
        "--product",
        choices=["0340", "0342", "0330", "0332"],
        default="0340",
        help="Produkt: 0340 (Pickup Parcel), 0342 (Bulk), 0330 (Business), 0332 (Bulk)",
    )
    args = parser.parse_args()

    config = load_config()
    bring_cfg = config.get("bring")
    if not bring_cfg:
        print("Fel: Ingen bring-konfiguration i config.yaml")
        sys.exit(1)

    print(f"Bring test (test_mode={bring_cfg.get('test_mode', True)})")
    print("-" * 50)

    # Parsa sample XML
    fixtures = Path(__file__).parent.parent / "tests" / "fixtures"
    xml_path = fixtures / "sample_bring_norge.xml"
    if not xml_path.exists():
        print(f"Fel: Hittar inte {xml_path}")
        sys.exit(1)

    parser_obj = GarpXMLParser()
    shipments = parser_obj.parse_file(xml_path)
    shipment = shipments[0]

    # Överskriv produkt om annan angiven
    if args.product != "0342":
        shipment.service.product_code = args.product

    client = BringClient(bring_cfg, config["sender"])

    try:
        result = client.create_shipment(shipment)
        print(f"OK!")
        print(f"  Consignment: {result['shipment_id']}")
        print(f"  Tracking:    {result['tracking_number']}")
        print(f"  Etikett:     {len(result['label_data'])} bytes")
        print(f"  Format:      {result['label_format']}")
    except Exception as e:
        print(f"Fel: {e}")
        raise


if __name__ == "__main__":
    main()
