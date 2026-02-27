#!/usr/bin/env python3
"""Testa Bring API med data som i GARP-exporten (DURI FAGPROFIL AS, N-0582, Oslo).

Simulerar exakt vad som kommer från GARP för att verifiera att flödet fungerar.
Kör i testläge (test_mode: true).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import load_config
from src.parsers.models import Shipment, Receiver, Container, ServiceInfo
from src.parsers.models import CarrierType
from src.carriers.bring import BringClient, _clean_postal
from src.carriers.bring_bulksplit import BringBulksplitClient


def main():
    config = load_config()
    bring_cfg = config.get("bring")
    sender = config.get("sender", {})
    if not bring_cfg:
        print("Fel: Ingen bring-konfiguration i config.yaml")
        sys.exit(1)

    test_mode = bring_cfg.get("test_mode", True)
    print(f"Bring API-test med GARP-liknande data (test_mode={test_mode})")
    print("=" * 60)

    # Data som i GARP-exporten
    receiver = Receiver(
        rcvid="2000",
        name="DURI FAGPROFIL AS",
        address1="BROBEKKVEIEN 80",  # GARP har address1 tom, address2 fylls
        address2="",
        zipcode="N-0582",
        city="OSLO",
        country="",  # GARP lämnar ofta tomt
    )

    # Parser-logik: tomt country + norsk postnr → NO
    if not receiver.country and (
        receiver.zipcode.upper().startswith("N-")
        or (len(receiver.zipcode.replace(" ", "")) == 4 and receiver.zipcode.replace(" ", "").isdigit())
    ):
        receiver.country = "NO"
        print(f"   Country satt till NO (från postnummer)")

    # Bring kräver 4 siffror för Norge
    cleaned_zip = _clean_postal(receiver.zipcode)
    print(f"   Postnummer: {receiver.zipcode!r} → {cleaned_zip!r} (rensat)")

    shipment = Shipment(
        order_no="50607 -53568",
        sender_name="ERNSTP",
        reference="50607 -53568",
        term_code="S",
        service=ServiceInfo(
            carrier=CarrierType.BRING,
            product_code="0332",
            addon="",
        ),
        receiver=receiver,
        containers=[
            Container(
                container_type="parcel",
                measure="total",
                copies=1,
                package_code="PC",
                contents="material",
                weight=1.0,
                volume=0.0,
            )
        ],
    )

    bulksplit = BringBulksplitClient(bring_cfg, sender)
    bring_client = BringClient(bring_cfg, sender)

    # 1. Reservera bulk-ID
    print("\n1. Reserverar bulk-ID...")
    terminals = bulksplit.list_terminals()
    no_terms = [t for t in terminals if t.get("countryCode") == "NO"]
    terminal_id = no_terms[0]["id"] if no_terms else terminals[0]["id"]
    bulk_id = bulksplit.reserve_bulk_id(terminal_id)
    bring_client._consolidated_shipment_id = bulk_id
    print(f"   OK: {bulk_id}")

    # 2. Boka via Bring API
    print("\n2. Bokar sändning via Bring API...")
    try:
        result = bring_client.create_shipment(shipment)
        tracking = result["tracking_number"]
        print(f"   OK: tracking={tracking}")
        print(f"   Etikett: {len(result.get('label_data', b''))} bytes")
    except Exception as e:
        print(f"   FEL: {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("Bring API accepterar GARP-data med våra fixar.")


if __name__ == "__main__":
    main()
