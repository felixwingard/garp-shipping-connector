#!/usr/bin/env python3
"""DHL Prisguide — snabb prisuppslag på kolli + vikt + destination.

Inga dimensioner behövs. Använder standardvärden som ger rimlig debitering.

Exempel:
  python scripts/prisguide_dhl.py paket-dk 1 15 5220    # 1 kolli 15kg till DK 5220
  python scripts/prisguide_dhl.py paket-dk 2 30 5220    # 2 kolli 30kg till DK 5220
  python scripts/prisguide_dhl.py pall-inrikes 1 500 11122
  python scripts/prisguide_dhl.py paket-inrikes 1 10 11122
  python scripts/prisguide_dhl.py stycke 1 50 11122
  python scripts/prisguide_dhl.py alla                    # Kör alla scenarion under
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def load_config():
    import os
    import re
    import yaml
    config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    if not config_path.exists():
        config_path = Path(__file__).parent.parent / "config" / "config.example.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        raw = f.read()
    resolved = re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), raw)
    return yaml.safe_load(resolved)


SCENARIOS = {
    "paket-inrikes": {"product": "102", "zip": "11122", "country": "SE", "label": "Paket B2B inrikes"},
    "ombud-inrikes": {"product": "103", "zip": "11122", "country": "SE", "label": "ServicePoint inrikes"},
    "paket-dk": {"product": "112", "zip": "5220", "country": "DK", "label": "Parcel Connect Plus B2B DK"},
    "paket-no": {"product": "112", "zip": "0150", "country": "NO", "label": "Parcel Connect Plus B2B NO"},
    "paket-pl": {"product": "112", "zip": "00-001", "country": "PL", "label": "Parcel Connect Plus PL"},
    "pall-inrikes": {"product": "210", "zip": "11122", "country": "SE", "label": "Pall inrikes"},
    "halvpall-inrikes": {"product": "210", "zip": "11122", "country": "SE", "halvpall": True, "label": "Halvpall inrikes"},
    "stycke": {"product": "211", "zip": "11122", "country": "SE", "label": "Styckegods inrikes"},
}


def quote(client, product: str, kolli: int, kg_per_kolli: float, zipcode: str, country: str,
         halvpall: bool = False) -> tuple[dict, str]:
    """Returnerar (dict med totalPrice, totalPriceIncVat, chargedWeight), fel_str)."""
    from src.parsers.models import Shipment, Receiver, Container, ServiceInfo, CarrierType

    pkg = "702" if halvpall else ("701" if product == "210" else "PKT")
    vol = 0.48 if (halvpall or product == "210") else 0.01
    weight = max(1.0, kg_per_kolli)
    if weight <= 0:
        weight = 1.0

    shipment = Shipment(
        order_no="PRIS",
        sender_name="Ernst P",
        reference="",
        term_code="S",
        service=ServiceInfo(carrier=CarrierType.DHL, product_code=product),
        receiver=Receiver(name="K", address1="A", zipcode=zipcode, city="X", country=country),
        containers=[Container(weight=weight, volume=vol, copies=kolli, package_code=pkg)],
    )
    try:
        result = client.get_price_quote(shipment, use_gross=False, stackable=not halvpall)
        items = result.get("priceQuoteResult", [])
        if isinstance(items, list):
            out = {}
            for r in items:
                tid = r.get("id", "")
                if tid == "TotalPrice":
                    out["totalPrice"] = f"{r.get('value', '')} {r.get('unit', 'SEK')}"
                elif tid == "TotalPriceIncVAT":
                    out["totalIncVat"] = f"{r.get('value', '')} {r.get('unit', 'SEK')}"
                elif tid == "ChargedWeight":
                    out["chargedWeight"] = f"{r.get('value', '')} {r.get('unit', 'KG')}"
            return out, ""
    except Exception as e:
        return {}, str(e)
    return {}, "Okänt fel"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nScenarion: paket-inrikes, ombud-inrikes, paket-dk, paket-no, paket-pl,")
        print("           pall-inrikes, halvpall-inrikes, stycke")
        print("           eller 'alla' för att köra alla.")
        return 1

    config = load_config()
    from src.carriers.dhl import DHLClient
    client = DHLClient(config["dhl"], config["sender"])

    scenario_key = sys.argv[1].lower()

    if scenario_key == "alla":
        presets = [
            ("paket-inrikes", 1, 10, None, None),
            ("ombud-inrikes", 1, 5, None, None),
            ("paket-dk", 1, 15, "5220", "DK"),
            ("paket-dk", 2, 15, "5220", "DK"),
            ("paket-no", 1, 15, "0150", "NO"),
            ("pall-inrikes", 1, 500, None, None),
            ("halvpall-inrikes", 1, 250, None, None),
            ("stycke", 1, 50, None, None),
        ]
        print("DHL Prisguide (avtalspris)\n" + "=" * 60)
        for skey, kolli, kg, zipcode, country in presets:
            s = SCENARIOS[skey]
            z = zipcode or s["zip"]
            c = country or s["country"]
            halvpall = s.get("halvpall", False)
            data, err = quote(client, s["product"], kolli, kg, z, c, halvpall)
            label = f"{s['label']}: {kolli} kolli × {kg} kg"
            if data:
                inc = data.get("totalIncVat", data.get("totalPrice", ""))
                print(f"  {label:42} → {inc} (ta betalt)")
            else:
                print(f"  {label:42} → Fel: {err}")
        return 0

    if scenario_key not in SCENARIOS:
        print(f"Okänt scenario: {scenario_key}")
        return 1

    s = SCENARIOS[scenario_key]
    kolli = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    kg = float(sys.argv[3]) if len(sys.argv) > 3 else 15.0
    zipcode = sys.argv[4] if len(sys.argv) > 4 else s["zip"]
    country = s["country"]

    halvpall = s.get("halvpall", False)
    data, err = quote(client, s["product"], kolli, kg, zipcode, country, halvpall)

    print(f"{s['label']}: {kolli} kolli × {kg} kg → {zipcode} {country}")
    if data:
        print(f"  Exkl. moms: {data.get('totalPrice', '-')}")
        print(f"  Inkl. moms (ta betalt): {data.get('totalIncVat', data.get('totalPrice', '-'))}")
        if data.get("chargedWeight"):
            print(f"  Debiterad vikt: {data['chargedWeight']}")
    else:
        print(f"  Fel: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
