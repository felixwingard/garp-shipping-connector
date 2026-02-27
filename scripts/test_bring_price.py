#!/usr/bin/env python3
"""Test Bring Shipping Guide API — hämta prisuppskattningar.

Användning:
  python scripts/test_bring_price.py
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from src.utils.config import load_config

SHIPPING_GUIDE_URL = "https://api.bring.com/shippingguide/api/v2/products"


def main():
    config = load_config()
    bring = config.get("bring", {})
    sender = config.get("sender", {})

    if not bring:
        print("Fel: Ingen bring-konfiguration i config.yaml")
        sys.exit(1)

    api_uid = bring.get("api_uid")
    api_key = bring.get("api_key")
    customer_number = bring.get("customer_number", "")
    test_mode = bring.get("test_mode", True)

    # Svenskt avsändarpostnr → Norskt mottagarpostnr (Oslo)
    from_postal = sender.get("zipcode", "43133").replace(" ", "")
    to_postal = "0154"  # Oslo

    # Paket: 40x30x20 cm, 8.2 kg
    now = datetime.now(timezone.utc)
    payload = {
        "language": "no",
        "withPrice": True,
        "withExpectedDelivery": False,
        "withGuiInformation": True,
        "edi": True,
        "postingAtPostOffice": False,
        "consignments": [
            {
                "id": 1,
                "products": [
                    {"id": "BUSINESS_PARCEL_BULK", "customerNumber": customer_number}
                    if customer_number
                    else {"id": "BUSINESS_PARCEL_BULK"},
                    {"id": "PICKUP_PARCEL_BULK", "customerNumber": customer_number}
                    if customer_number
                    else {"id": "PICKUP_PARCEL_BULK"},
                ],
                "fromCountryCode": "SE",
                "toCountryCode": "NO",
                "fromPostalCode": from_postal,
                "toPostalCode": to_postal,
                "addressLine": "Karl Johans gate 15",
                "shippingDate": {
                    "day": str(now.day),
                    "hour": str(now.hour),
                    "minute": str(now.minute),
                    "month": str(now.month),
                    "year": str(now.year),
                },
                "packages": [
                    {
                        "id": "1",
                        "length": 40,
                        "width": 30,
                        "height": 20,
                        "grossWeight": 8200,
                    }
                ],
            }
        ],
    }

    headers = {
        "Content-Type": "application/json",
        "X-Mybring-API-Uid": api_uid,
        "X-Mybring-API-Key": api_key,
        "X-Bring-Client-URL": "https://ernstp.se",
    }
    if test_mode:
        headers["X-Bring-Test-Indicator"] = "true"

    print("Bring Shipping Guide API — Prishämtning")
    print("=" * 55)
    print(f"Från: {from_postal} (SE) → {to_postal} (NO)")
    print(f"Paket: 40x30x20 cm, 8.2 kg")
    print(f"Test: {test_mode}, Kundnr: {customer_number or '(ej angivet)'}")
    print()

    try:
        resp = requests.post(SHIPPING_GUIDE_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.HTTPError as e:
        print(f"HTTP-fel: {e}")
        if hasattr(e, "response") and e.response is not None:
            try:
                body = e.response.json()
                print(json.dumps(body, indent=2, ensure_ascii=False))
            except Exception:
                print(e.response.text[:500])
        sys.exit(1)
    except Exception as e:
        print(f"Fel: {e}")
        sys.exit(1)

    # Tolka svar
    consignments = data.get("consignments", [])
    if not consignments:
        print("Inga consignments i svar.")
        print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])
        return

    for cons in consignments:
        products = cons.get("products", [])
        for prod in products:
            pid = prod.get("id", "?")
            gui = prod.get("guiInformation", {})
            name = gui.get("displayName", gui.get("productName", pid))

            price_info = prod.get("price", {})
            list_price = price_info.get("listPrice", {})
            net_price = price_info.get("netPrice", {})
            source = net_price or list_price
            if not source:
                print(f"  {name} ({pid}): (ingen pris)")
                continue

            pwo = source.get("priceWithoutAdditionalServices", {})
            pwa = source.get("priceWithAdditionalServices", pwo)
            amt_ex = pwa.get("amountWithoutVAT", "—")  # Exkl. moms (visas i connector)
            amt_inc = pwa.get("amountWithVAT", "—")
            curr = source.get("currencyCode", "SEK")
            price_type = "avtalspris" if net_price else "listpris"
            print(f"  {name} ({pid}): {amt_ex} {curr} exkl. moms ({price_type})")
            if amt_inc and amt_inc != amt_ex:
                print(f"    Inkl. moms: {amt_inc} {curr}")

        trace = data.get("traceMessages", [])
        if trace:
            print("\n  Trace:", trace[:3])

    print()
    print("=" * 55)


if __name__ == "__main__":
    main()
