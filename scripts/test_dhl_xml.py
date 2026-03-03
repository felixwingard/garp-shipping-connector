#!/usr/bin/env python3
"""Testar DHL API med XML-fil — skapar sändning och hämtar etikett.

Användning:
  python scripts/test_dhl_xml.py tests/fixtures/sample_dhl_112_dk.xml
  python scripts/test_dhl_xml.py path/to/your.xml

Skapar sändning via DHL API, hämtar etikett, sparar till label_cache.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parsers.xml_parser import GarpXMLParser
from src.carriers.dhl import DHLClient
from src.utils.config import load_config, get_config_path


def main():
    parser = argparse.ArgumentParser(description="Testa DHL API med XML-fil")
    parser.add_argument(
        "xml_file",
        help="Sökväg till XML-fil (t.ex. tests/fixtures/sample_dhl_112_dk.xml)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Spara etikett till label_cache (config paths.label_cache_dir)",
    )
    parser.add_argument(
        "--no-pickup",
        action="store_true",
        help="Hoppa över upphämtningsbokning",
    )
    args = parser.parse_args()

    xml_path = Path(args.xml_file)
    if not xml_path.exists():
        print(f"Filen finns inte: {xml_path}")
        sys.exit(1)

    config_path = get_config_path()
    if not config_path.exists():
        print("Saknar config/config.yaml. Kopiera config.example.yaml till config.yaml.")
        sys.exit(1)

    config = load_config()

    # Parsa XML
    parser = GarpXMLParser()
    shipments = parser.parse_file(xml_path)
    if not shipments:
        print("Ingen sändning i XML-filen.")
        sys.exit(1)

    shipment = shipments[0]
    print(f"Order: {shipment.order_no}")
    print(f"Produkt: DHL:{shipment.service.product_code}")
    print(f"Mottagare: {shipment.receiver.name or '—'} ({shipment.receiver.country or '—'})")
    print()

    # DHL-klient
    dhl = DHLClient(config["dhl"], config["sender"])

    try:
        # 1. Skapa sändning
        print("1. Skapar sändning...")
        result = dhl.create_shipment(shipment)
        shipment_id = result["shipment_id"]
        tracking = result["tracking_number"]
        print(f"   OK — shipment_id: {shipment_id}, tracking: {tracking}")
        print()

        # 2. Hämta etikett + fraktlista
        print("2. Hämtar etikett...")
        documents = dhl.get_all_documents(shipment_id)
        label_data = documents["label"]
        shipment_list = documents.get("shipment_list")
        print(f"   OK — etikett: {len(label_data)} bytes")
        if shipment_list:
            print(f"   OK — fraktlista: {len(shipment_list)} bytes")
        print()

        # 3. Upphämtning (om ej --no-pickup)
        if not args.no_pickup and shipment.service.booking and shipment.service.booking.pickup_booking:
            pickup_date = shipment.service.booking.pickup_date
            if pickup_date:
                print("3. Bokar upphämtning...")
                try:
                    dhl.request_pickup(shipment_id, pickup_date)
                    print("   OK")
                except Exception as e:
                    print(f"   Varning: {e}")
        else:
            print("3. Upphämtning hoppad över.")

        # 4. Spara etikett
        if args.save:
            label_cache = Path(config["paths"]["label_cache_dir"])
            label_cache.mkdir(parents=True, exist_ok=True)
            out_path = label_cache / f"{shipment.order_no}_etikett.pdf"
            out_path.write_bytes(label_data)
            print(f"\nEtikett sparad: {out_path}")

        print("\n--- KLAR ---")
        print(f"Tracking: {tracking}")
        print(f"Shipment ID: {shipment_id}")

    except Exception as e:
        print(f"\nFEL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
