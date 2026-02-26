#!/usr/bin/env python3
"""Kör flera PriceQuote-scenarier och skriver ut pris — jämför med MyDHL portal.

  python3 scripts/run_pricequote_tests.py

Jämför totalpriserna med samma sändningar i MyDHL — om de stämmer har ni avtalspris.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parsers.models import (
    Shipment,
    Receiver,
    Container,
    ServiceInfo,
    BookingInfo,
    CarrierType,
)
from src.carriers.dhl import DHLClient


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


def run_quote(client, name, product, to_zip, to_country, weight=5, halvpall=False,
              non_stackable=False, volume=None, loading_meters=None, use_gross=False):
    """Kör ett quote och returnerar (total_price_str, success, error_msg)."""
    pkg = "702" if halvpall else ("701" if product == "210" else "PKT")
    vol = volume if volume is not None else (0.48 if halvpall or product == "210" else 0.01)

    shipment = Shipment(
        order_no="QUOTE",
        sender_name=client.sender.get("name", ""),
        reference="QUOTE",
        term_code="S",
        delivery_instruction="",
        service=ServiceInfo(
            carrier=CarrierType.DHL,
            product_code=str(product),
            addon="",
            raw_srvid=f"DHL:{product}",
            booking=BookingInfo(pickup_booking=False, pickup_date=""),
        ),
        receiver=Receiver(
            name="Mottagare",
            address1="Adress 1",
            zipcode=to_zip,
            city="Mottagarstad",
            country=to_country,
            phone="",
            email="",
        ),
        containers=[
            Container(
                weight=weight,
                volume=vol,
                copies=1,
                package_code=pkg,
                length=60 if halvpall else 0,
                width=80 if halvpall else 0,
                height=75 if halvpall else 0,
            )
        ],
    )

    extra = {"nonStackable": True} if non_stackable else None
    stackable = not non_stackable

    try:
        result = client.get_price_quote(
            shipment,
            use_gross=use_gross,
            additional_services=extra,
            stackable=stackable,
            loading_meters=loading_meters,
        )
        items = result.get("priceQuoteResult", [])
        if isinstance(items, list):
            total = next((r for r in items if r.get("id") == "TotalPrice"), None)
            if total:
                return (f"{total.get('value', '?')} {total.get('unit', '')}", True, None)
            return ("(ingen TotalPrice)", True, None)
        return ("(okänt format)", True, None)
    except Exception as e:
        return (None, False, str(e))


def main():
    config = load_config()
    client = DHLClient(config["dhl"], config["sender"])
    has_eid = getattr(client, "_eid", None) is not None

    scenarios = [
        # (namn, product, to_zip, to_country, weight, halvpall, non_stackable, vol, loading_m)
        ("102 Paket SE → Stockholm 5kg", "102", "11122", "SE", 5, False, False, None, None),
        ("102 Paket SE → Göteborg 10kg", "102", "41101", "SE", 10, False, False, None, None),
        ("109 Paket SE → Köpenhamn 5kg", "109", "2100", "DK", 5, False, False, None, None),
        ("202 Halvpall SE → Polen 40kg", "202", "74320", "PL", 40, True, True, 0.36, 0.2),
        ("210 Fullpall inrikes 500kg", "210", "11122", "SE", 500, False, False, 0.48, 0.8),
    ]

    print("=" * 70)
    print("DHL PriceQuote — Jämför med MyDHL portal")
    print("=" * 70)
    print(f"eID konfigurerat: {'Ja (avtalspris)' if has_eid else 'Nej (listpris endast)'}")
    print()

    for name, product, to_zip, to_country, weight, halvpall, ns, vol, lm in scenarios:
        # Avtalspris (om eID)
        price_avtal, ok_avtal, err_avtal = run_quote(
            client, name, product, to_zip, to_country, weight, halvpall, ns, vol, lm, use_gross=False
        )
        # Listpris
        price_gross, ok_gross, err_gross = run_quote(
            client, name, product, to_zip, to_country, weight, halvpall, ns, vol, lm, use_gross=True
        )

        print(f"\n{name}")
        print("-" * 50)
        if has_eid:
            avtal_str = price_avtal if ok_avtal else f"Fel: {err_avtal}"
            print(f"  Avtalspris (API):  {avtal_str}")
        gross_str = price_gross if ok_gross else f"Fel: {err_gross}"
        print(f"  Listpris (API):    {gross_str}")
        if has_eid and ok_avtal and ok_gross and price_avtal and price_gross:
            if price_avtal != price_gross:
                print("  → Olika = avtalspris används korrekt")
            else:
                print("  → Samma = kontrollera i MyDHL om det är avtal eller listpris")

    print("\n" + "=" * 70)
    print("Ange samma sändningar i MyDHL portal och jämför priserna ovan.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
