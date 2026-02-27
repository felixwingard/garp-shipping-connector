#!/usr/bin/env python3
"""Skapa en Bring-testetikett via API och spara till test_labels.

Kör hela flödet (Bulksplit + Booking) och sparar etikett-PDF till test_labels/.
Användning:
  python scripts/test_bring_label.py
"""

import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import load_config
from src.parsers.xml_parser import GarpXMLParser
from src.carriers.bring import BringClient
from src.carriers.bring_bulksplit import BringBulksplitClient


def main():
    config = load_config()
    bring_cfg = config.get("bring")
    sender = config.get("sender", {})
    if not bring_cfg:
        print("Fel: Ingen bring-konfiguration i config.yaml")
        sys.exit(1)

    test_mode = bring_cfg.get("test_mode", True)
    print(f"Bring testetikett (test_mode={test_mode})")
    print("=" * 50)

    bulksplit = BringBulksplitClient(bring_cfg, sender)
    bring_client = BringClient(bring_cfg, sender)

    # 1. Lista terminaler
    print("\n1. Bulksplit: list_terminals")
    terminals = bulksplit.list_terminals()
    no_terms = [t for t in terminals if t.get("countryCode") == "NO"]
    terminal_id = (no_terms[0].get("id", "") if no_terms
                   else (terminals[0].get("id", "") if terminals else ""))
    print(f"   OK: terminal={terminal_id}")

    # 2. Reservera bulk-ID
    print("\n2. Bulksplit: reserve_bulk_id")
    bulk_id = bulksplit.reserve_bulk_id(terminal_id)
    bring_client._consolidated_shipment_id = bulk_id
    print(f"   OK: {bulk_id}")

    # 3. Boka paket (Booking API)
    print("\n3. Booking: create_shipment (0332)")
    fixtures = Path(__file__).parent.parent / "tests" / "fixtures"
    xml_path = fixtures / "sample_bring_norge.xml"
    if not xml_path.exists():
        print(f"   FEL: {xml_path} saknas")
        sys.exit(1)

    parser_obj = GarpXMLParser()
    shipments = parser_obj.parse_file(xml_path)
    shipment = shipments[0]
    shipment.service.product_code = "0332"
    shipment.service.addon = ""

    result = bring_client.create_shipment(shipment)
    tracking = result["tracking_number"]
    label_data = result["label_data"]
    print(f"   OK: consignment={result['shipment_id']}, tracking={tracking}")
    print(f"   Etikett: {len(label_data)} bytes")

    # 4. Spara till test_labels/
    out_dir = Path(__file__).parent.parent / "test_labels"
    out_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"bring_{timestamp}_{tracking or 'label'}.pdf"
    out_path = out_dir / filename
    out_path.write_bytes(label_data)
    print(f"\n   Sparad: {out_path}")

    # 5. Registrera pall (avsluta bulk)
    print("\n4. Bulksplit: register_bulk_shipment")
    bulksplit.register_bulk_shipment(
        bulk_shipment_id=bulk_id,
        total_weight_kg=25,
        num_packages=1,
        service_code="0332",
    )
    print("   OK")

    print("\n" + "=" * 50)
    print("Testetikett skapad!")


if __name__ == "__main__":
    main()
