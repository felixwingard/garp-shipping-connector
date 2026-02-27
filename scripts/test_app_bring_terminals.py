#!/usr/bin/env python3
"""Testa om Bring-terminaler laddas som när appen körs.

Simulerar exakt samma flöde som tray-appen: load_config → BringBulkWindow → _load_terminals.
Kör detta på samma maskin som appen (t.ex. Windows) för att felsöka tomma terminaler.

Användning:
  python scripts/test_app_bring_terminals.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    print("Simulerar appens config + Bring terminal-hämtning...")
    print("=" * 55)

    # 1. Samma config som tray-appen
    from src.utils.config import load_config, get_config_path
    config = load_config()
    print(f"Config från: {get_config_path()}")
    print()

    bring = config.get("bring", {})
    if not bring:
        print("FEL: 'bring' saknas i config.yaml")
        print("Lägg till bring-sektionen (api_uid, api_key, customer_number)")
        return 1
    if not bring.get("api_uid") or not bring.get("api_key"):
        print("FEL: bring.api_uid och bring.api_key krävs")
        return 1

    print(f"Bring config: api_uid={bring.get('api_uid', '')[:20]}..., test_mode={bring.get('test_mode')}")
    print()

    # 2. Samma anrop som BringBulkWindow._load_terminals()
    try:
        from src.carriers.bring_bulksplit import BringBulksplitClient
        client = BringBulksplitClient(bring, config.get("sender", {}))
        terminals = client.list_terminals()
        no_terms = [t for t in terminals if t.get("countryCode") == "NO"]
        other = [t for t in terminals if t.get("countryCode") != "NO"]
        items = [f"{t.get('id', '')} — {t.get('name', '')} ({t.get('city', '')})" for t in no_terms + other]
        ids = [t.get("id", "") for t in no_terms + other]

        print(f"Terminaler laddade: {len(terminals)} st ({len(no_terms)} Norge)")
        for i, (item, tid) in enumerate(zip(items[:5], ids[:5])):
            print(f"  {i+1}. {tid}: {item}")
        if len(items) > 5:
            print(f"  ... och {len(items)-5} till")
        print()
        print("OK — appen bör kunna visa dessa i Bring Bulk-fönstret.")
        return 0
    except Exception as e:
        print(f"FEL vid list_terminals: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
