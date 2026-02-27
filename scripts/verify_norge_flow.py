#!/usr/bin/env python3
"""Verifiera Norge-flödet end-to-end.

Kör hela kedjan som i produktion:
  1. Reservera bulk-ID (Bulksplit)
  2. XML med BRING:0332 → orchestrator.process_file()
  3. Etikett skapas och sparas (test_labels på Mac, Zebra på Windows)
  4. Registrera pall (avsluta bulk)

Kräver: config.yaml med bring.api_uid, api_key, customer_number.
Användning:
  python scripts/verify_norge_flow.py
"""

import logging
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Tysta ner icke-kritiska loggar under verifiering
logging.getLogger("urllib3").setLevel(logging.WARNING)


def main():
    from src.utils.config import load_config, save_config
    from src.parsers.xml_parser import GarpXMLParser
    from src.orchestrator import ShipmentOrchestrator
    from src.carriers.bring_bulksplit import BringBulksplitClient

    print("=" * 55)
    print("Verifierar Norge-flödet (Bring 0332 end-to-end)")
    print("=" * 55)

    config = load_config()
    bring_cfg = config.get("bring")
    if not bring_cfg:
        print("FEL: Ingen bring-konfiguration i config.yaml")
        sys.exit(1)

    original_paths = dict(config.get("paths", {}))
    original_skip_email = config.get("skip_email")

    # Temp-mappar för att inte påverka produktion
    tmp = Path(tempfile.mkdtemp(prefix="garp_verify_"))
    watch_dir = tmp / "watch"
    done_dir = tmp / "done"
    error_dir = tmp / "error"
    label_cache = tmp / "labels"
    for d in [watch_dir, done_dir, error_dir, label_cache]:
        d.mkdir(parents=True, exist_ok=True)

    # Överskriv paths
    config["paths"] = {
        "watch_dir": str(watch_dir),
        "done_dir": str(done_dir),
        "error_dir": str(error_dir),
        "label_cache_dir": str(label_cache),
    }
    config["skip_email"] = True  # Skicka inga mail under verifiering

    sender = config.get("sender", {})
    bulksplit = BringBulksplitClient(bring_cfg, sender)

    # 1. Reservera bulk-ID
    print("\n1. Bulksplit: list_terminals + reserve_bulk_id")
    terminals = bulksplit.list_terminals()
    no_terms = [t for t in terminals if t.get("countryCode") == "NO"]
    terminal_id = no_terms[0].get("id", "") if no_terms else terminals[0].get("id", "")
    bulk_id = bulksplit.reserve_bulk_id(terminal_id)
    config["bring"]["consolidated_shipment_id"] = bulk_id
    print(f"   OK: bulk_id={bulk_id}")

    # 2. Skapa test-XML med BRING:0332
    fixtures = Path(__file__).parent.parent / "tests" / "fixtures"
    sample = fixtures / "sample_bring_norge.xml"
    if not sample.exists():
        print(f"FEL: {sample} saknas")
        sys.exit(1)
    xml_content = sample.read_text(encoding="utf-8").replace("BRING:0340", "BRING:0332")
    test_xml = watch_dir / "verify_norge_0332.xml"
    test_xml.write_text(xml_content, encoding="utf-8")
    print(f"\n2. Test-XML skapad: {test_xml.name}")

    # 3. Kör orchestrator (samma som vid riktig XML från GARP)
    print("\n3. Orchestrator: process_file")
    orchestrator = ShipmentOrchestrator(config, on_event=None)
    success = orchestrator.process_file(test_xml)

    if not success:
        print("   FEL: process_file returnerade False")
        for f in error_dir.glob("*.error.txt"):
            print("   ", f.read_text().strip()[:200])
        config["paths"] = original_paths
        config["skip_email"] = original_skip_email
        save_config(config)
        shutil.rmtree(tmp, ignore_errors=True)
        sys.exit(1)

    # 4. Kontrollera att etikett sparats
    # På Mac: printer sparar till /tmp/garp-labels/; på Windows skrivs till Zebra
    garp_labels = Path(tempfile.gettempdir()) / "garp-labels"
    test_labels = Path(__file__).parent.parent / "test_labels"
    test_labels.mkdir(exist_ok=True)

    saved_labels = list(garp_labels.glob("*.pdf")) if garp_labels.exists() else []
    if saved_labels:
        latest = max(saved_labels, key=lambda p: p.stat().st_mtime)
        dest = test_labels / f"verify_{latest.name}"
        shutil.copy2(latest, dest)
        print(f"   Etikett sparad: {dest}")
    else:
        print("   (Etikett skickad till skrivare eller sparad i annan mapp)")

    # 5. Registrera pall (avsluta bulk)
    print("\n4. Bulksplit: register_bulk_shipment")
    bulksplit.register_bulk_shipment(
        bulk_shipment_id=bulk_id,
        total_weight_kg=10,
        num_packages=1,
        service_code="0332",
    )
    # Återställ bulk i config (pallen är registrerad)
    config["paths"] = original_paths
    config["skip_email"] = original_skip_email
    config["bring"]["consolidated_shipment_id"] = ""
    config["bring"]["bulk_parcel_count"] = 0
    save_config(config)
    print("   OK: Pall registrerad, config uppdaterad")

    shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 55)
    print("Norge-flödet verifierat!")
    print("=" * 55)


if __name__ == "__main__":
    main()
