#!/usr/bin/env python3
"""Förhandsgranska e-postmall för ett land (sparar HTML till fil).

Användning:
  python3 scripts/preview_email.py --dk     # Dansk mail
  python3 scripts/preview_email.py --de     # Tysk mail
  python3 scripts/preview_email.py --sv     # Svensk mail
  python3 scripts/preview_email.py --en     # Engelsk mail

Öppna den sparade HTML-filen i webbläsaren för att se mailet.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    lang = "sv"
    if "--dk" in sys.argv:
        lang = "da"
    elif "--de" in sys.argv:
        lang = "de"
    elif "--en" in sys.argv:
        lang = "en"
    elif "--no" in sys.argv:
        lang = "no"
    elif "--pl" in sys.argv:
        lang = "pl"

    from src.utils.config import load_config, get_config_path
    from src.notifications.email_sender import (
        EmailSender,
        EMAIL_TEXTS,
        CARRIER_NAMES,
        TRACKING_URLS,
        DHL_HAMTA_URL,
    )
    from src.parsers.models import CarrierType

    config_path = get_config_path()
    if not config_path.exists():
        print("Saknar config/config.yaml. Skapar mall med exempeldata...")
        smtp_config = {
            "host": "smtp.example.com",
            "port": 587,
            "username": "user",
            "password": "pass",
            "use_tls": True,
            "from_address": "no-reply@ernstp.se",
            "from_name": "Ernst P",
            "google_review_url": "",
            "company_contact_email": "info@ernstp.se",
            "company_contact_phone": "031-703 07 70",
        }
    else:
        config = load_config()
        smtp_config = config["smtp"]

    sender = EmailSender(smtp_config)
    texts = EMAIL_TEXTS.get(lang, EMAIL_TEXTS["en"])
    carrier = CarrierType.DHL
    carrier_name = CARRIER_NAMES[carrier]
    order_no = "W66344-133252"
    tracking_number = "1234567890"
    tracking_url = TRACKING_URLS[carrier].format(tracking=tracking_number)

    html = sender._build_html(
        order_no=order_no,
        tracking_number=tracking_number,
        tracking_url=tracking_url,
        carrier=carrier,
        carrier_name=carrier_name,
        service_description="DHL Parcel Connect • Utrikes",
        dhl_hamta_id="abc123",
        custom_message="",
        has_attachments=True,
        google_review_url=smtp_config.get("google_review_url", ""),
        company_email=smtp_config.get("company_contact_email", ""),
        company_phone=smtp_config.get("company_contact_phone", ""),
        texts=texts,
        lang=lang,
        estimated_delivery_date="2026-02-28",
    )

    out_path = PROJECT_ROOT / "test_data" / f"email_preview_{lang}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"Sparat: {out_path}")
    print(f"Öppna i webbläsare: open {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
