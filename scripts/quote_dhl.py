#!/usr/bin/env python3
"""DHL PriceQuote — prisförfrågan för sändning.

Exempel:
  python scripts/quote_dhl.py --product 102 --to-zip 11122 --to-country SE
  python scripts/quote_dhl.py --product 202 --to-zip 74320 --to-country PL --weight 40 --halvpall --non-stackable
  # Exakt som faktisk sändning (60×80×75 cm, 0.36 m³, 0.2 flakmeter):
  python scripts/quote_dhl.py --product 202 --to-zip 74320 --to-country PL --weight 40 --halvpall \\
    --non-stackable --volume 0.36 --loading-meters 0.2 --length 60 --width 80 --height 75

Avtalspris: Sätt eid_username och eid_password i config (dhl:) eller DHL_EID_USERNAME /
DHL_EID_PASSWORD. Begär eID från DHL (se.dbi@dhl.com).
"""

import argparse
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


def main():
    p = argparse.ArgumentParser(description="DHL PriceQuote — prisuppskattning")
    p.add_argument("--product", default="210", help="Produktkod (102, 210, etc.)")
    p.add_argument("--to-zip", required=True, help="Mottagar-postnummer")
    p.add_argument("--to-country", default="PL", help="Mottagarland (SE, PL, DE, ...)")
    p.add_argument("--to-city", default="", help="Mottag Stad")
    p.add_argument("--weight", type=float, default=40, help="Vikt kg per kolli")
    p.add_argument("--volume", type=float, default=None, help="Volym m³ per kolli (default: 0.01 för PKT, 0.48 för pall)")
    p.add_argument("--copies", type=int, default=1, help="Antal kolli")
    p.add_argument("--halvpall", action="store_true", help="Halvpall (702)")
    p.add_argument("--non-stackable", action="store_true", help="Ej stapelbar")
    p.add_argument("--loading-meters", type=float, default=None, help="Flakmeter (t.ex. 0.2)")
    p.add_argument("--length", type=float, default=0, help="Längd cm")
    p.add_argument("--width", type=float, default=0, help="Bredd cm")
    p.add_argument("--height", type=float, default=0, help="Höjd cm")
    p.add_argument("--gross", action="store_true", help="Listpris (quoteforgrossprice). Default: avtalspris om eID konfigurerat.")
    args = p.parse_args()

    config = load_config()
    client = DHLClient(config["dhl"], config["sender"])

    pkg = "702" if args.halvpall else ("701" if args.product == "210" else "PKT")
    city = args.to_city or "Mottagarstad"

    # Volym: mått → m³, eller default (PKT 0.01, pall 0.48)
    if args.length and args.width and args.height:
        vol = (args.length * args.width * args.height) / 1_000_000
    elif args.volume is not None:
        vol = args.volume
    elif args.halvpall or args.product == "210":
        vol = 0.48
    else:
        vol = 0.01  # PKT default — undvik 0.48 som gav fel taxerat vikt

    shipment = Shipment(
        order_no="QUOTE",
        sender_name=config["sender"]["name"],
        reference="QUOTE",
        term_code="S",
        delivery_instruction="",
        service=ServiceInfo(
            carrier=CarrierType.DHL,
            product_code=args.product,
            addon="",
            raw_srvid=f"DHL:{args.product}",
            booking=BookingInfo(pickup_booking=False, pickup_date=""),
        ),
        receiver=Receiver(
            name="Mottagare",
            address1="Adress 1",
            zipcode=args.to_zip,
            city=city,
            country=args.to_country,
            phone="",
            email="",
        ),
        containers=[
            Container(
                weight=args.weight,
                volume=vol,
                copies=args.copies,
            package_code=pkg,
            length=args.length,
            width=args.width,
            height=args.height,
        )
    ],
)

    extra = {"nonStackable": True} if args.non_stackable else None
    stackable = not args.non_stackable
    use_gross = args.gross
    if not use_gross and getattr(client, "_eid", None):
        print("  (avtalspris — eID konfigurerat)")
    elif not use_gross:
        print("  (försöker avtalspris — kräver eID i config)")

    print(f"Prisförfrågan: {args.product} → {args.to_zip} {args.to_country}, {args.weight} kg")
    if args.halvpall:
        print("  Halvpall")
    if args.non_stackable:
        print("  Ej stapelbar")

    try:
        result = client.get_price_quote(
            shipment,
            use_gross=use_gross,
            additional_services=extra,
            stackable=stackable,
            loading_meters=args.loading_meters,
        )
        items = result.get("priceQuoteResult", [])
        if isinstance(items, list):
            for r in items:
                print(f"  {r.get('descriptionEng', r.get('id', ''))}: {r.get('value', '')} {r.get('unit', '')}")
        else:
            print(result)
    except Exception as e:
        print(f"Fel: {e}")
        if hasattr(e, "response") and e.response is not None:
            try:
                print(e.response.json())
            except Exception:
                print(e.response.text[:500])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
