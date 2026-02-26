#!/usr/bin/env python3
"""Dump PriceQuote request JSON för att skicka till DHL support.

Kör: python scripts/dump_pricequote_request.py --product 202 --to-zip 74320 --to-country PL
Skriv ut till fil: python scripts/dump_pricequote_request.py --no-mask ... > pricequote_request.json

Default: maskerar känsliga fält. Använd --no-mask för riktiga uppgifter (att skicka till DHL).
"""

import argparse
import json
import os
import re
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
    import yaml
    config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    if not config_path.exists():
        config_path = Path(__file__).parent.parent / "config" / "config.example.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        raw = f.read()
    resolved = re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), raw)
    return yaml.safe_load(resolved)


def main():
    p = argparse.ArgumentParser(description="Dump PriceQuote request för DHL support")
    p.add_argument("--product", default="202", help="Produktkod (102, 202, 210, ...)")
    p.add_argument("--to-zip", default="74320", help="Mottagar-postnummer")
    p.add_argument("--to-country", default="PL", help="Mottagarland")
    p.add_argument("--weight", type=float, default=40)
    p.add_argument("--halvpall", action="store_true", help="Halvpall (702)")
    p.add_argument("--non-stackable", action="store_true", default=True)
    p.add_argument("--volume", type=float, default=0.36)
    p.add_argument("--loading-meters", type=float, default=0.2)
    p.add_argument("--gross", action="store_true", help="Listpris (quoteforgrossprice)")
    p.add_argument("--no-mask", action="store_true",
                   help="Inkludera riktiga uppgifter (api_key, eID, kundnr) — för att skicka till DHL")
    args = p.parse_args()

    config = load_config()
    client = DHLClient(config["dhl"], config["sender"])

    pkg = "702" if args.halvpall else ("701" if args.product == "210" else "PKT")
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
            city="Mottagarstad",
            country=args.to_country,
            phone="",
            email="",
        ),
        containers=[
            Container(
                weight=args.weight,
                volume=args.volume,
                copies=1,
                package_code=pkg,
                length=60,
                width=80,
                height=75,
            )
        ],
    )

    extra = {"nonStackable": True} if args.non_stackable else None
    stackable = not args.non_stackable

    shipment_model = client._build_price_quote_shipment(
        shipment, additional_services=extra, stackable=stackable,
        loading_meters_override=args.loading_meters,
    )

    path_key = "price_quote_gross" if args.gross else "price_quote"
    url = f"{client.base_url}/pricequoteapi/v1/pricequote/quoteforgrossprice" if args.gross \
        else f"{client.base_url}/pricequoteapi/v1/pricequote/quoteforprice"

    body = {
        "shipment": shipment_model,
        "ownSurCharge": {"percentage": 0, "value": 0},
    }
    eid = client._eid if not args.gross and getattr(client, "_eid", None) else None
    if eid:
        body["eid"] = eid

    if not args.no_mask:
        # Maskera känsliga fält i shipment
        for p in body["shipment"].get("parties", []):
            if p.get("type") == "Consignor" and p.get("id"):
                p["id"] = "<ert-kundnummer>"
        if "eid" in body:
            body["eid"] = {"userName": "<ert-eID-user>", "password": "<ert-eID>"}

    out = {
        "url": url,
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "client-key": config["dhl"].get("api_key", "") if args.no_mask else "<ert-client-key-GUID>",
        },
        "body": body,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
