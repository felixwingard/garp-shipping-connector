#!/usr/bin/env python3
"""Skript för att testa etikettskapande utan att skicka mail.

Skapar en test-XML i watch-mappen och kör process_file.
Kräver att config.yaml finns med giltiga DHL-uppgifter.
Sätter automatiskt skip_email under körningen.

På Mac/Linux: Använder ./test_data/... om watch_dir pekar på Windows-sökväg.
"""

import sys
import shutil
import platform
from pathlib import Path

# Projektroot
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    from src.utils.config import load_config, get_config_path
    from src.orchestrator import ShipmentOrchestrator

    send_email = "--send-email" in sys.argv
    use_dk = "--dk" in sys.argv
    use_ornskoldsvik = "--ornskoldsvik" in sys.argv or "--örnsköldsvik" in sys.argv
    use_ernstp_self = "--ernstp" in sys.argv or "--self" in sys.argv
    if use_dk:
        sample_name = "sample_dk.xml"
    elif use_ornskoldsvik:
        sample_name = "sample_ornskoldsvik.xml"
    elif use_ernstp_self:
        sample_name = "sample_ernstp_self.xml"
    else:
        sample_name = "sample_garp_format.xml"

    config_path = get_config_path()
    if not config_path.exists():
        print("Saknar config/config.yaml. Kopiera config.example.yaml till config.yaml och fyll i DHL-uppgifter.")
        sys.exit(1)

    config = load_config()

    # skip_email om ej --send-email anges
    config["skip_email"] = not send_email
    if send_email:
        print("Skickar mail till mottagaren i XML...")
    if use_dk:
        print("Använder dansk leveransadress (DK) → mailet blir på danska")
    if use_ornskoldsvik:
        print("Använder ServicePoint till Örnsköldsvik (SE) → mailet blir på svenska")
    if use_ernstp_self:
        print("Använder DHL Företagspaket (102) till Ernst P AB, Mölndal")

    # På Mac/Linux: använd projektlokala mappar om config har Windows-sökvägar
    paths = config["paths"]
    if platform.system() != "Windows" and "C:\\" in str(paths.get("watch_dir", "")):
        test_base = PROJECT_ROOT / "test_data"
        paths = {**paths}
        paths["watch_dir"] = str(test_base / "watch")
        paths["done_dir"] = str(test_base / "done")
        paths["error_dir"] = str(test_base / "error")
        paths["log_dir"] = str(test_base / "logs")
        paths["label_cache_dir"] = str(test_base / "labels")
        config = {**config, "paths": paths}
        print(f"Använder testmappar: {test_base}")

    watch_dir = Path(config["paths"]["watch_dir"])
    watch_dir.mkdir(parents=True, exist_ok=True)

    # Kopiera exempel-XML till watch-mappen
    sample = PROJECT_ROOT / "tests" / "fixtures" / sample_name
    dest = watch_dir / sample_name
    shutil.copy(sample, dest)
    print(f"Kopierat {sample.name} till {watch_dir}")

    # Initiera och kör
    orch = ShipmentOrchestrator(config)
    print("Bearbetar (mail hoppas över)...")
    ok = orch.process_file(dest)
    print("KLAR" if ok else "MISSLYCKADES")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
