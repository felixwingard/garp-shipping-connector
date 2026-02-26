#!/usr/bin/env python3
"""Testa utskrift — listar skrivare, kollar SumatraPDF, skriver test-PDF.

  python scripts/test_print.py
  python scripts/test_print.py --printer "ZDesigner ZD420"
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.printing.printer import LabelPrinter, list_windows_printers


def main():
    p = argparse.ArgumentParser(description="Testa PDF-utskrift")
    p.add_argument("--printer", help="Skrivarnamn att testa (annars listar vi bara)")
    args = p.parse_args()

    printers = list_windows_printers()
    print(f"\nInstallerade skrivare ({len(printers)} st):")
    for i, name in enumerate(printers, 1):
        print(f"  {i}. {name!r}")

    # Ladda config
    import yaml
    import os, re
    cfg_path = Path(__file__).parent.parent / "config" / "config.yaml"
    if not cfg_path.exists():
        cfg_path = Path(__file__).parent.parent / "config" / "config.example.yaml"
    raw = cfg_path.read_text(encoding="utf-8")
    resolved = re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), raw)
    config = yaml.safe_load(resolved)

    printer_cfg = config.get("printers", config.get("printer", {}))
    label_printer = printer_cfg.get("label_printer_name") or printer_cfg.get("windows_printer_name", "")
    print(f"\nConfig etikettskrivare: {label_printer!r}")
    if label_printer and label_printer not in printers:
        print(f"  VARNING: Skrivaren finns inte i listan ovan — namnet måste matcha exakt!")

    lp = LabelPrinter(printer_cfg)
    sumatra = lp._find_sumatra()
    print(f"\nSumatraPDF: {sumatra}")
    if sumatra == "SumatraPDF.exe":
        print("  VARNING: SumatraPDF hittades inte! Lägg den i projektmappen.")
        return 1

    if not args.printer and not label_printer:
        print("\nAnge --printer 'Skrivarnamn' för att testa utskrift.")
        return 0

    printer_to_use = args.printer or label_printer
    if not printer_to_use:
        return 0

    # Använd test-PDF från fixtures (eller skapa enkel)
    test_pdf = Path(__file__).parent.parent / "tests" / "fixtures" / "test_label_dhl.pdf"
    if test_pdf.exists():
        pdf_test = test_pdf.read_bytes()
    else:
        pdf_test = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 297 420] >>\nendobj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n0000000101 00000 n \ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n206\n%%EOF"

    print(f"\nTestar utskrift på {printer_to_use!r}...")
    ok = lp.print_label(pdf_test, "pdf", "TEST")
    print(f"Resultat: {'OK' if ok else 'MISSLYCKADES'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
