#!/usr/bin/env python3
"""Test av alla Bring API:er — Bulksplit + Booking.

Kör hela flödet:
  1. Lista terminaler (Bulksplit)
  2. Reservera bulk-ID (Bulksplit)
  3. Boka paket mot bulk-ID (Booking)
  4. Registrera pall (Bulksplit)

Användning:
  python scripts/test_bring_all.py
  python scripts/test_bring_all.py --no-register   # Hoppa över steg 4 (sparar bulk för manuell reg)
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import load_config
from src.parsers.xml_parser import GarpXMLParser
from src.carriers.bring import BringClient
from src.carriers.bring_bulksplit import BringBulksplitClient


def main():
    parser = argparse.ArgumentParser(description="Test alla Bring API:er")
    parser.add_argument(
        "--no-register",
        action="store_true",
        help="Hoppa över registrering av pall (behåll bulk-ID för senare)",
    )
    parser.add_argument(
        "--skip-booking",
        action="store_true",
        help="Hoppa över Bokning (t.ex. vid saknat bulk-avtal)",
    )
    args = parser.parse_args()

    config = load_config()
    bring_cfg = config.get("bring")
    sender = config.get("sender", {})
    if not bring_cfg:
        print("Fel: Ingen bring-konfiguration i config.yaml")
        sys.exit(1)

    test_mode = bring_cfg.get("test_mode", True)
    print(f"Bring API-tester (test_mode={test_mode})")
    print("=" * 55)

    bulksplit = BringBulksplitClient(bring_cfg, sender)
    bring_client = BringClient(bring_cfg, sender)

    # --- 1. Lista terminaler ---
    print("\n1. Bulksplit: list_terminals")
    try:
        terminals = bulksplit.list_terminals()
        no_terms = [t for t in terminals if t.get("countryCode") == "NO"]
        print(f"   OK: {len(terminals)} terminaler ({len(no_terms)} i Norge)")
        if no_terms:
            t0 = no_terms[0]
            print(f"   Första NO: {t0.get('id')} — {t0.get('name')} ({t0.get('city')})")
            terminal_id = t0.get("id", "")
        else:
            terminal_id = terminals[0].get("id", "") if terminals else ""
            print(f"   Använder: {terminal_id}")
    except Exception as e:
        print(f"   FEL: {e}")
        sys.exit(1)

    # --- 2. Reservera bulk-ID ---
    print("\n2. Bulksplit: reserve_bulk_id")
    try:
        bulk_id = bulksplit.reserve_bulk_id(terminal_id)
        print(f"   OK: {bulk_id}")
        # Temporärt för Bokning
        bring_client._consolidated_shipment_id = bulk_id
    except Exception as e:
        print(f"   FEL: {e}")
        sys.exit(1)

    # --- 3. Boka paket (Booking API) mot bulk-ID ---
    print("\n3. Booking: create_shipment (0332 med bulk-ID)")
    if args.skip_booking:
        print("   Hoppat över (--skip-booking)")
    else:
        fixtures = Path(__file__).parent.parent / "tests" / "fixtures"
        xml_path = fixtures / "sample_bring_norge.xml"
        if not xml_path.exists():
            print(f"   Hoppar: {xml_path} saknas")
        else:
            parser_obj = GarpXMLParser()
            shipments = parser_obj.parse_file(xml_path)
            shipment = shipments[0]
            shipment.service.product_code = "0332"  # Business Parcel Bulk
            shipment.service.addon = ""

            try:
                result = bring_client.create_shipment(shipment)
                print(f"   OK: consignment={result['shipment_id']}, tracking={result['tracking_number']}")
                print(f"   Etikett: {len(result['label_data'])} bytes")
            except Exception as e:
                print(f"   FEL: {e}")
                print("   (Kund saknar bulk-avtal? Kör med --skip-booking för att testa övriga API:er)")
                sys.exit(1)

    # --- 4. Registrera pall ---
    if not args.no_register:
        print("\n4. Bulksplit: register_bulk_shipment")
        try:
            result = bulksplit.register_bulk_shipment(
                bulk_shipment_id=bulk_id,
                total_weight_kg=25,
                num_packages=1,
                service_code="0332",
            )
            print(f"   OK: bulkShipmentId={result.get('bulkShipmentId')}")
            if result.get("waybillUrl"):
                print(f"   Waybill: {result['waybillUrl'][:60]}...")
            if result.get("routingLabelsUrl"):
                print(f"   Routing: {result['routingLabelsUrl'][:60]}...")
        except Exception as e:
            print(f"   FEL: {e}")
            sys.exit(1)
    else:
        print("\n4. Registrera pall — hoppat över (--no-register)")

    print("\n" + "=" * 55)
    print("Alla Bring API:er OK!")


if __name__ == "__main__":
    main()
