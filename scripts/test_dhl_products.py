#!/usr/bin/env python3
"""DHL API-test — testar alla DHL Freight API Farm-endpoints.

Testade API:er:
  1. ServicePointLocator API — hitta ombud (standalone)
  2. TransportInstruction API — skapa sändning
  3. Print API — hämta etikett + fraktlista
  4. PickupRequest API — boka upphämtning

Användning:
  python scripts/test_dhl_products.py --all      # Alla produkter (102,103,109,210,211)
  python scripts/test_dhl_products.py            # Endast produkt 102
  python scripts/test_dhl_products.py --product 102 103 210
  python scripts/test_dhl_products.py --no-pickup  # Hoppa över PickupRequest

Ref: https://dhlpaket.se/dashboard/services/uncategorized/api-farm-2/
"""

import argparse
import sys
from pathlib import Path

# Lägg projektrot i path
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
from datetime import date, timedelta


# Produkter att testa — anpassa adress/gewicht efter DHL:s krav per produkt
PRODUCT_TESTS = {
    "102": {  # DHL Paket (B2B)
        "name": "DHL Paket (102)",
        "receiver": Receiver(
            name="DHL Test Mottagare AB",
            address1="Storgatan 1",
            zipcode="11122",
            city="Stockholm",
            country="SE",
            phone="+46701234567",
            email="test@example.com",
        ),
        "container": Container(weight=2.0, volume=0.002, copies=1, package_code="PKT"),
        "requires_accesspoint": False,
    },
    "103": {  # DHL ServicePoint B2C — AccessPoint hämtas automatiskt
        "name": "DHL ServicePoint B2C (103)",
        "receiver": Receiver(
            name="Test Konsument",
            address1="Karlsrovägen 25A",
            zipcode="30294",  # Halmstad — ServicePointLocator hittar ombud
            city="Halmstad",
            country="SE",
            phone="+4611223344",
            email="test@example.com",
        ),
        "container": Container(weight=2.0, volume=0.002, copies=1, package_code="PKT"),
        "requires_accesspoint": False,  # Hämtas via ServicePointLocator
    },
    "109": {  # DHL Parcel Connect (utrikes)
        "name": "DHL Parcel Connect (109)",
        "receiver": Receiver(
            name="EU Test AB",
            address1="Teststraße 10",
            zipcode="10115",
            city="Berlin",
            country="DE",
            phone="+4930123456",
            email="test@example.com",
        ),
        "container": Container(weight=2.0, volume=0.002, copies=1, package_code="PKT"),
        "requires_accesspoint": False,
    },
    "210": {  # DHL Pall
        "name": "DHL Pall (210)",
        "receiver": Receiver(
            name="Pall Mottagare AB",
            address1="Industrigatan 10",
            zipcode="43133",
            city="Mölndal",
            country="SE",
            phone="+46317030770",
            email="test@example.com",
        ),
        "container": Container(
            weight=500.0,
            volume=0.96,
            copies=1,
            package_code="701",  # EUR-pall
        ),
        "requires_accesspoint": False,
    },
    "211": {  # DHL Stycke
        "name": "DHL Stycke (211)",
        "receiver": Receiver(
            name="Styckgods Mottagare AB",
            address1="Lastgatan 5",
            zipcode="11122",
            city="Stockholm",
            country="SE",
            phone="+46701234567",
            email="test@example.com",
        ),
        "container": Container(weight=50.0, volume=0.1, copies=1, package_code="PKT"),
        "requires_accesspoint": False,
    },
}


def load_config():
    import os
    import re
    import yaml

    config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    if not config_path.exists():
        config_path = Path(__file__).parent.parent / "config" / "config.example.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            "config/config.yaml eller config.example.yaml saknas. "
            "Kopiera config.example.yaml till config.yaml."
        )

    with open(config_path, "r", encoding="utf-8") as f:
        raw = f.read()

    def replace_env(match):
        return os.environ.get(match.group(1), match.group(0))

    resolved = re.sub(r"\$\{(\w+)\}", replace_env, raw)
    return yaml.safe_load(resolved)


def run_product_test(client: DHLClient, product_code: str, do_pickup: bool) -> dict:
    """Kör full test för en produkt. Returnerar resultat-dict."""
    if product_code not in PRODUCT_TESTS:
        return {"ok": False, "error": f"Okänd produkt: {product_code}"}

    spec = PRODUCT_TESTS[product_code]

    order_no = f"TEST-{product_code}-{date.today().strftime('%Y%m%d')}"
    pickup_date = (date.today() + timedelta(days=1)).isoformat()

    shipment = Shipment(
        order_no=order_no,
        sender_name="Ernst P AB",
        reference=order_no,
        term_code="S",
        delivery_instruction="Testleverans från GARP",
        service=ServiceInfo(
            carrier=CarrierType.DHL,
            product_code=product_code,
            addon="",
            raw_srvid=f"DHL:{product_code}",
            booking=BookingInfo(pickup_booking=True, pickup_date=pickup_date),
        ),
        receiver=spec["receiver"],
        containers=[spec["container"]],
    )

    result = {"product": product_code, "name": spec["name"], "steps": {}}

    try:
        # 1. TransportInstruction
        ti = client.create_shipment(shipment)
        result["steps"]["TransportInstruction"] = {
            "ok": True,
            "shipment_id": ti["shipment_id"],
            "tracking": ti["tracking_number"],
        }

        # 2. Print API
        documents = client.get_all_documents(ti["shipment_id"])
        result["steps"]["Print"] = {
            "ok": True,
            "label_bytes": len(documents["label"]),
            "shipment_list": documents.get("shipment_list") is not None,
        }
        result["label_data"] = documents["label"]
        result["shipment_list_data"] = documents.get("shipment_list")
        result["order_no"] = order_no

        # 3. PickupRequest
        if do_pickup:
            pickup = client.request_pickup(
                ti["shipment_id"],
                pickup_date,
                pickup_instruction="Test upphämtning för DHL verifiering",
            )
            status = pickup.get("status", -1)
            result["steps"]["PickupRequest"] = {
                "ok": status in (0, 2),  # 0=Accepted, 2=Moved
                "status": status,
                "booking_number": pickup.get("bookingNumber", ""),
            }
        else:
            result["steps"]["PickupRequest"] = {"skipped": True}

        result["ok"] = all(
            s.get("ok", s.get("skipped"))
            for s in result["steps"].values()
        )

    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)
        import traceback
        result["traceback"] = traceback.format_exc()

    return result


def run_servicepoint_test(client: DHLClient) -> dict:
    """Testar ServicePointLocator API (standalone)."""
    try:
        points = client.find_service_points("11122", "SE", city="Stockholm", max_results=5)
        return {
            "ok": len(points) > 0,
            "count": len(points),
            "first": points[0].get("name", "") if points else "",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(
        description="Testa alla DHL API:er (ServicePointLocator, TransportInstruction, Print, PickupRequest)"
    )
    parser.add_argument(
        "--product",
        nargs="+",
        default=None,
        help="Produktkoder att testa (102, 103, 109, 210, 211)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Testa alla produkter: 102, 103, 109, 210, 211",
    )
    parser.add_argument(
        "--no-pickup",
        action="store_true",
        help="Hoppa över PickupRequest (för snabbare test)",
    )
    parser.add_argument(
        "--save-labels",
        action="store_true",
        help="Spara etiketter till label_cache_dir (paths.label_cache_dir)",
    )
    args = parser.parse_args()

    products = args.product if args.product is not None else (["102", "103", "109", "210", "211"] if args.all else ["102"])

    print("=" * 60)
    print("DHL API Farm — Produkttest")
    print("=" * 60)

    try:
        config = load_config()
    except FileNotFoundError as e:
        print(f"FEL: {e}")
        return 1

    dhl_config = config.get("dhl", {})
    sender = config.get("sender", {})

    if not dhl_config.get("api_key") or "${" in str(dhl_config.get("api_key", "")):
        print("FEL: Sätt DHL_API_KEY i config eller miljövariabel.")
        return 1

    client = DHLClient(dhl_config, sender)
    base_url = dhl_config.get("base_url", "")
    env_name = "Sandbox" if "test-api" in base_url else "Produktion"
    print(f"Miljö: {env_name}")
    print(f"Produkter: {', '.join(products)}")
    print(f"PickupRequest: {'Nej' if args.no_pickup else 'Ja'}")
    print()

    # 0. ServicePointLocator API (standalone)
    print("[ServicePointLocator] Hittar ombud nära 11122 Stockholm...")
    sp_result = run_servicepoint_test(client)
    if sp_result.get("ok"):
        print(f"  OK — {sp_result['count']} ombud, t.ex. {sp_result.get('first', '')[:40]}")
    else:
        print(f"  MISSLYCKAD — {sp_result.get('error', '')}")
    print()

    all_ok = sp_result.get("ok", True)  # ServicePointLocator måste lyckas
    for product_code in products:
        result = run_product_test(client, product_code, do_pickup=not args.no_pickup)
        status = "OK" if result.get("ok") else "MISSLYCKAD" if not result.get("skip") else "HOPPAD ÖVER"
        print(f"[{status}] {result.get('name', product_code)}")
        if result.get("skip"):
            print(f"  → {result.get('reason', '')}")
            continue
        if result.get("error"):
            print(f"  → Fel: {result['error']}")
            if result.get("traceback"):
                print(result["traceback"][:500])
            all_ok = False
            continue
        # Spara etiketter om --save-labels
        if args.save_labels and result.get("label_data") and result.get("order_no"):
            label_dir = Path(config.get("paths", {}).get("label_cache_dir", "C:\\GARP\\Labels"))
            if str(label_dir).startswith("C:") and Path("/").exists():  # Windows path på Mac/Linux
                label_dir = Path(__file__).parent.parent / "test_labels"
            label_dir = Path(label_dir)
            label_dir.mkdir(parents=True, exist_ok=True)
            label_path = label_dir / f"{result['order_no']}.pdf"
            label_path.write_bytes(result["label_data"])
            if result.get("shipment_list_data"):
                list_path = label_dir / f"{result['order_no']}_shipmentlist.pdf"
                list_path.write_bytes(result["shipment_list_data"])
            print(f"  → Etikett sparad: {label_path}")
        for step, step_result in result.get("steps", {}).items():
            if step_result.get("skipped"):
                print(f"  - {step}: (hoppad)")
            elif step_result.get("ok"):
                det = []
                if "shipment_id" in step_result:
                    det.append(f"id={step_result['shipment_id']}")
                if "tracking" in step_result:
                    det.append(f"tracking={step_result['tracking']}")
                if "label_bytes" in step_result:
                    det.append(f"etikett {step_result['label_bytes']} bytes")
                if "status" in step_result:
                    det.append(f"status={step_result['status']}")
                print(f"  - {step}: OK {', '.join(det)}")
            else:
                print(f"  - {step}: MISSLYCKAD {step_result}")
                all_ok = False
        print()

    print("=" * 60)
    print("KLAR" if all_ok else "NÅGRA TEST MISSLYCKADES")
    print("=" * 60)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
