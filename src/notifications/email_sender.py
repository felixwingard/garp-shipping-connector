"""E-postnotifieringar till kunder med spårningslänk.

Skickar "tack för din order"-mail med spårningsnummer,
direktlänk till transportörens spårningssida och
eventuella bilagor (fraktlista, följesedel från GARP).
"""

import base64
import logging
import smtplib
from pathlib import Path
from typing import Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from ..parsers.models import CarrierType

logger = logging.getLogger(__name__)

# Projektets assets-mapp (logotyper etc.)
_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"

# Spårningslänkar per transportör
TRACKING_URLS = {
    CarrierType.DHL: "https://www.dhl.com/se-sv/home/tracking.html?tracking-id={tracking}",
    CarrierType.BRING: "https://sporing.posten.no/sporing/{tracking}",
}

# DHL Hamta — hantera leverans (byt ombud, leveransalternativ etc.)
DHL_HAMTA_URL = "https://hamta.dhl.com/{tracking}"

CARRIER_NAMES = {
    CarrierType.DHL: "DHL",
    CarrierType.BRING: "Bring/Posten",
}

# Transportörens kontaktuppgifter (frågor om frakten)
CARRIER_CONTACT = {
    CarrierType.DHL: ("0771-345 345", "https://www.dhl.com/se-sv/contact-us.html"),
    CarrierType.BRING: ("22 00 00 00", "https://www.bring.no/"),  # Posten/Bring Norge
}

# Landkod → språkkod för e-post. Sverige/Norge = sv/no. Övriga länder = deras språk.
# Standard: en om landet saknas eller inte finns i listan.
COUNTRY_TO_LANG = {
    "SE": "sv",
    "NO": "no",
    "DK": "da",
    "FI": "fi",
    "DE": "de",
    "AT": "de",
    "CH": "de",
    "PL": "pl",
    "NL": "nl",
    "BE": "nl",
    "GB": "en",
    "UK": "en",
    "US": "en",
    "IE": "en",
    "FR": "fr",
    "ES": "es",
    "IT": "it",
}
# Fallback för okända länder
DEFAULT_LANG = "en"

# Översatta texter för e-postmall
EMAIL_TEXTS = {
    "sv": {
        "subject": "Din order {order} har skickats!",
        "order_display_suffix": "Följesedel",
        "header_subtitle": "Fraktbekräftelse",
        "title": "Din order har skickats! 🚚✨",
        "intro": "Order {order} är på väg till dig med {carrier}.",
        "tracking_label": "Spårningsnummer",
        "track_btn": "Spåra leverans 📦",
        "hamta_btn": "Byt ombud eller leveransalternativ",
        "hamta_note": "Länken aktiveras när DHL har bekräftat upphämtningen (vanligtvis inom några timmar).",
        "attachments_note": "📎 <em>Följesedel och fraktlista bifogas som PDF.</em>",
        "review_title": "Nöjda med din beställning?",
        "review_sub": "Hjälp andra genom att dela din erfarenhet på Google",
        "review_btn": "Skriv en recension på Google",
        "shipping_questions": "Frågor om frakten?",
        "contact_carrier": "Kontakta",
        "other_questions": "Övriga frågor?",
        "estimated_delivery": "Estimerad leverans",
        "signoff": "Vänliga hälsningar,",
        "footer": "Detta mail skickades automatiskt • Detta mail går inte att svara på",
    },
    "en": {
        "subject": "Your order {order} has been shipped!",
        "order_display_suffix": "Delivery note",
        "header_subtitle": "Shipping confirmation",
        "title": "Your order has been shipped! 🚚✨",
        "intro": "Order {order} is on its way to you via {carrier}.",
        "tracking_label": "Tracking number",
        "track_btn": "Track delivery 📦",
        "hamta_btn": "Change pickup point or delivery options",
        "hamta_note": "The link is activated when DHL has confirmed the pickup (usually within a few hours).",
        "attachments_note": "📎 <em>Delivery note and shipping list are attached as PDF.</em>",
        "review_title": "Happy with your order?",
        "review_sub": "Help others by sharing your experience on Google",
        "review_btn": "Write a review on Google",
        "shipping_questions": "Questions about shipping?",
        "contact_carrier": "Contact",
        "other_questions": "Other questions?",
        "estimated_delivery": "Estimated delivery",
        "signoff": "Best regards,",
        "footer": "This email was sent automatically • Do not reply to this email",
    },
    "de": {
        "subject": "Ihre Bestellung {order} wurde versendet!",
        "order_display_suffix": "Lieferschein",
        "header_subtitle": "Versandbestätigung",
        "title": "Ihre Bestellung wurde versendet! 🚚✨",
        "intro": "Bestellung {order} ist mit {carrier} auf dem Weg zu Ihnen.",
        "tracking_label": "Sendungsverfolgungsnummer",
        "track_btn": "Sendung verfolgen 📦",
        "hamta_btn": "Abholstelle oder Lieferoptionen ändern",
        "hamta_note": "Der Link wird aktiviert, wenn DHL die Abholung bestätigt hat (in der Regel innerhalb weniger Stunden).",
        "attachments_note": "📎 <em>Lieferschein und Frachtliste sind als PDF beigefügt.</em>",
        "review_title": "Zufrieden mit Ihrer Bestellung?",
        "review_sub": "Helfen Sie anderen, indem Sie Ihre Erfahrung bei Google teilen",
        "review_btn": "Bewertung bei Google schreiben",
        "shipping_questions": "Fragen zur Lieferung?",
        "contact_carrier": "Kontakt",
        "other_questions": "Weitere Fragen?",
        "estimated_delivery": "Voraussichtliche Lieferung",
        "signoff": "Freundliche Grüße,",
        "footer": "Diese E-Mail wurde automatisch gesendet • Diese E-Mail kann nicht beantwortet werden",
    },
    "da": {
        "subject": "Din ordre {order} er blevet sendt!",
        "order_display_suffix": "Følgeseddel",
        "header_subtitle": "Fragtbekræftelse",
        "title": "Din ordre er blevet sendt! 🚚✨",
        "intro": "Ordre {order} er på vej til dig med {carrier}.",
        "tracking_label": "Sporingsnummer",
        "track_btn": "Spor levering 📦",
        "hamta_btn": "Skift afhentningssted eller leveringsmuligheder",
        "hamta_note": "Linket aktiveres, når DHL har bekræftet afhentningen (normalt inden for få timer).",
        "attachments_note": "📎 <em>Følgeseddel og fragtliste vedhæftes som PDF.</em>",
        "review_title": "Tilfreds med din ordre?",
        "review_sub": "Hjælp andre ved at dele din oplevelse på Google",
        "review_btn": "Skriv en anmeldelse på Google",
        "shipping_questions": "Spørgsmål om fragten?",
        "contact_carrier": "Kontakt",
        "other_questions": "Andre spørgsmål?",
        "estimated_delivery": "Forventet levering",
        "signoff": "Venlig hilsen,",
        "footer": "Denne e-mail blev sendt automatisk • Svar ikke på denne e-mail",
    },
    "no": {
        "subject": "Din ordre {order} er sendt!",
        "order_display_suffix": "Følgeseddel",
        "header_subtitle": "Fraktbekreftelse",
        "title": "Din ordre har blitt sendt! 🚚✨",
        "intro": "Ordre {order} er på vei til deg med {carrier}.",
        "tracking_label": "Sporingsnummer",
        "track_btn": "Spor levering 📦",
        "hamta_btn": "Bytt hentested eller leveringsalternativer",
        "hamta_note": "Lenken aktiveres når DHL har bekreftet henting (vanligvis innen noen timer).",
        "attachments_note": "📎 <em>Følgeseddel og fraktliste vedlegges som PDF.</em>",
        "review_title": "Fornøyd med bestillingen?",
        "review_sub": "Hjelp andre ved å dele din opplevelse på Google",
        "review_btn": "Skriv en anmeldelse på Google",
        "shipping_questions": "Spørsmål om frakten?",
        "contact_carrier": "Kontakt",
        "other_questions": "Andre spørsmål?",
        "estimated_delivery": "Forventet levering",
        "signoff": "Vennlig hilsen,",
        "footer": "Denne e-posten ble sendt automatisk • Svar ikke på denne e-posten",
    },
    "pl": {
        "subject": "Twoje zamówienie {order} zostało wysłane!",
        "order_display_suffix": "List przewozowy",
        "header_subtitle": "Potwierdzenie wysyłki",
        "title": "Twoje zamówienie zostało wysłane! 🚚✨",
        "intro": "Zamówienie {order} jest w drodze do Ciebie przez {carrier}.",
        "tracking_label": "Numer śledzenia",
        "track_btn": "Śledź dostawę 📦",
        "hamta_btn": "Zmień punkt odbioru lub opcje dostawy",
        "hamta_note": "Link zostanie aktywowany, gdy DHL potwierdzi odbiór (zwykle w ciągu kilku godzin).",
        "attachments_note": "📎 <em>List przewozowy i lista wysyłkowa są dołączone w formacie PDF.</em>",
        "review_title": "Zadowolony z zamówienia?",
        "review_sub": "Pomóż innym, dzieląc się swoimi doświadczeniami na Google",
        "review_btn": "Napisz recenzję na Google",
        "shipping_questions": "Pytania dotyczące wysyłki?",
        "contact_carrier": "Kontakt",
        "other_questions": "Inne pytania?",
        "estimated_delivery": "Szacowana dostawa",
        "signoff": "Z poważaniem,",
        "footer": "Ta wiadomość została wysłana automatycznie • Nie odpowiadaj na tę wiadomość",
    },
    "nl": {
        "subject": "Uw bestelling {order} is verzonden!",
        "order_display_suffix": "Zending",
        "header_subtitle": "Verzendbevestiging",
        "title": "Uw bestelling is verzonden! 🚚✨",
        "intro": "Bestelling {order} is onderweg naar u via {carrier}.",
        "tracking_label": "Track & trace-nummer",
        "track_btn": "Volg zending 📦",
        "hamta_btn": "Wijzig afhaalpunt of bezorgopties",
        "hamta_note": "De link wordt actief wanneer DHL de afhaling heeft bevestigd (meestal binnen enkele uren).",
        "attachments_note": "📎 <em>Pakbon en verzendlijst zijn als PDF bijgevoegd.</em>",
        "review_title": "Tevreden met uw bestelling?",
        "review_sub": "Help anderen door uw ervaring te delen op Google",
        "review_btn": "Schrijf een beoordeling op Google",
        "shipping_questions": "Vragen over de verzending?",
        "contact_carrier": "Neem contact op met",
        "other_questions": "Overige vragen?",
        "estimated_delivery": "Verwachte levering",
        "signoff": "Met vriendelijke groet,",
        "footer": "Deze e-mail is automatisch verzonden • Reageer niet op deze e-mail",
    },
    "fi": {
        "subject": "Tilauksesi {order} on lähetetty!",
        "order_display_suffix": "Kuittilappu",
        "header_subtitle": "Lähetyksen vahvistus",
        "title": "Tilauksesi on lähetetty! 🚚✨",
        "intro": "Tilaus {order} on matkalla sinulle {carrier}n kautta.",
        "tracking_label": "Seurantanumero",
        "track_btn": "Seuraa lähetystä 📦",
        "hamta_btn": "Vaihda noutopiste tai toimitusvaihtoehdot",
        "hamta_note": "Linkki aktivoituu, kun DHL on vahvistanut noudon (yleensä muutamassa tunnissa).",
        "attachments_note": "📎 <em>Kuittilappu ja lähetyslista liitteenä PDF-muodossa.</em>",
        "review_title": "Tyydyttynyt tilaukseesi?",
        "review_sub": "Auta muita jakamalla kokemuksesi Googlessa",
        "review_btn": "Kirjoita arvostelu Googleen",
        "shipping_questions": "Kysymyksiä lähetyksestä?",
        "contact_carrier": "Ota yhteyttä",
        "other_questions": "Muut kysymykset?",
        "estimated_delivery": "Arvioitu toimitus",
        "signoff": "Ystävällisin terveisin,",
        "footer": "Tämä sähköposti lähetettiin automaattisesti • Älä vastaa tähän sähköpostiin",
    },
    "fr": {
        "subject": "Votre commande {order} a été expédiée!",
        "order_display_suffix": "Bon de livraison",
        "header_subtitle": "Confirmation d'expédition",
        "title": "Votre commande a été expédiée! 🚚✨",
        "intro": "La commande {order} est en route vers vous via {carrier}.",
        "tracking_label": "Numéro de suivi",
        "track_btn": "Suivre la livraison 📦",
        "hamta_btn": "Changer le point relais ou les options de livraison",
        "hamta_note": "Le lien est activé lorsque DHL a confirmé la collecte (généralement en quelques heures).",
        "attachments_note": "📎 <em>Bon de livraison et liste d'expédition joints en PDF.</em>",
        "review_title": "Satisfait de votre commande?",
        "review_sub": "Aidez les autres en partageant votre expérience sur Google",
        "review_btn": "Écrire un avis sur Google",
        "shipping_questions": "Questions sur l'expédition?",
        "contact_carrier": "Contacter",
        "other_questions": "Autres questions?",
        "estimated_delivery": "Livraison estimée",
        "signoff": "Cordialement,",
        "footer": "Cet e-mail a été envoyé automatiquement • Ne pas répondre à cet e-mail",
    },
    "es": {
        "subject": "¡Tu pedido {order} ha sido enviado!",
        "order_display_suffix": "Albarán",
        "header_subtitle": "Confirmación de envío",
        "title": "¡Tu pedido ha sido enviado! 🚚✨",
        "intro": "El pedido {order} está en camino hacia ti con {carrier}.",
        "tracking_label": "Número de seguimiento",
        "track_btn": "Seguir envío 📦",
        "hamta_btn": "Cambiar punto de recogida u opciones de entrega",
        "hamta_note": "El enlace se activa cuando DHL haya confirmado la recogida (normalmente en pocas horas).",
        "attachments_note": "📎 <em>Albarán y lista de envío adjuntos en PDF.</em>",
        "review_title": "¿Satisfecho con tu pedido?",
        "review_sub": "Ayuda a otros compartiendo tu experiencia en Google",
        "review_btn": "Escribir una reseña en Google",
        "shipping_questions": "¿Preguntas sobre el envío?",
        "contact_carrier": "Contactar",
        "other_questions": "¿Otras preguntas?",
        "estimated_delivery": "Entrega estimada",
        "signoff": "Atentamente,",
        "footer": "Este correo se envió automáticamente • No responder a este correo",
    },
    "it": {
        "subject": "Il tuo ordine {order} è stato spedito!",
        "order_display_suffix": "Bolla di consegna",
        "header_subtitle": "Conferma di spedizione",
        "title": "Il tuo ordine è stato spedito! 🚚✨",
        "intro": "L'ordine {order} è in viaggio verso di te con {carrier}.",
        "tracking_label": "Numero di tracking",
        "track_btn": "Traccia la spedizione 📦",
        "hamta_btn": "Cambia punto di ritiro o opzioni di consegna",
        "hamta_note": "Il link si attiva quando DHL ha confermato il ritiro (di solito entro poche ore).",
        "attachments_note": "📎 <em>Bolla di consegna e lista di spedizione allegate in PDF.</em>",
        "review_title": "Soddisfatto del tuo ordine?",
        "review_sub": "Aiuta gli altri condividendo la tua esperienza su Google",
        "review_btn": "Scrivi una recensione su Google",
        "shipping_questions": "Domande sulla spedizione?",
        "contact_carrier": "Contatta",
        "other_questions": "Altre domande?",
        "estimated_delivery": "Consegna stimata",
        "signoff": "Cordiali saluti,",
        "footer": "Questa e-mail è stata inviata automaticamente • Non rispondere a questa e-mail",
    },
}

# Produktbeskrivningar för mailet (DHL: produktkod → beskrivning)
PRODUCT_DESCRIPTIONS = {
    "102": "DHL Paket • Hemleverans",
    "103": "DHL ServicePoint • Ombud",
    "109": "DHL Parcel Connect • Utrikes",
    "112": "DHL Parcel Connect Plus • Utrikes",
    "210": "DHL Pall • Pallfrakt",
    "211": "DHL Stycke • Styckegods",
    "202": "DHL Euroconnect",
    "205": "DHL Euroline",
    "0340": "Bring Pickup Parcel • Ombud",
    "0342": "Bring Pickup Parcel Bulk",
    "0330": "Bring Business Parcel",
    "0332": "Bring Business Parcel Bulk",
}


class EmailSender:
    """Skickar fraktbekräftelse via SMTP (Loopia)."""

    def __init__(self, config: dict):
        self.host = config["host"]
        self.port = config["port"]
        self.username = config["username"]
        self.password = config["password"]
        self.use_tls = config.get("use_tls", True)
        self.from_addr = config["from_address"]
        self.from_name = config["from_name"]
        self.google_review_url = (config.get("google_review_url") or "").strip()
        self.company_email = (config.get("company_contact_email") or "").strip()
        self.company_phone = (config.get("company_contact_phone") or "").strip()

    def send_tracking_email(
        self,
        to_email: str,
        order_no: str,
        tracking_number: str,
        carrier: CarrierType,
        product_code: str = "",
        dhl_hamta_id: str = "",
        custom_message: str = "",
        attachments: Optional[list[tuple[str, bytes]]] = None,
        receiver_country: str = "",
        estimated_delivery_date: str = "",
    ) -> bool:
        """Skickar spårningsmail till kund.

        Args:
            attachments: Lista med (filnamn, pdf-bytes), t.ex.
                        [("Fraktlista.pdf", pdf_bytes), ("Följesedel.pdf", pdf_bytes)]

        Returns:
            True om mailet skickades.
        """
        if not to_email:
            logger.warning(f"Ingen e-post för order {order_no}, hoppar över mail")
            return False

        if not tracking_number:
            logger.warning(f"Inget spårningsnr för order {order_no}, hoppar över mail")
            return False

        carrier_name = CARRIER_NAMES.get(carrier, str(carrier))
        tracking_url = TRACKING_URLS.get(carrier, "").format(tracking=tracking_number)

        # Välj språk utifrån leveransland (SE/NO = sv/no, övriga = deras språk)
        # GARP: tomt country = Sverige som standard
        country = (receiver_country or "").strip().upper()
        if not country:
            country = "SE"
        lang = COUNTRY_TO_LANG.get(country, DEFAULT_LANG)
        # Säkerställ att språket finns i EMAIL_TEXTS
        texts = EMAIL_TEXTS.get(lang, EMAIL_TEXTS[DEFAULT_LANG])

        # Format: W66344-133251 → W66344-Följesedel 133251 (eller översatt)
        parts = order_no.split("-", 1)
        suffix = texts["order_display_suffix"]
        order_display = f"{parts[0]}-{suffix} {parts[1]}" if len(parts) == 2 else order_no
        subject = f"🎉 {texts['subject'].format(order=order_display)}"
        service_desc = PRODUCT_DESCRIPTIONS.get(product_code, carrier_name)
        html_body = self._build_html(
            order_no=order_no,
            tracking_number=tracking_number,
            tracking_url=tracking_url,
            carrier=carrier,
            carrier_name=carrier_name,
            service_description=service_desc,
            dhl_hamta_id=dhl_hamta_id,
            custom_message=custom_message,
            has_attachments=bool(attachments),
            google_review_url=self.google_review_url,
            company_email=self.company_email,
            company_phone=self.company_phone,
            texts=texts,
            lang=lang,
            estimated_delivery_date=estimated_delivery_date,
        )

        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = f"{self.from_name} <{self.from_addr}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        for filename, data in attachments or []:
            part = MIMEBase("application", "pdf")
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                "attachment",
                filename=("utf-8", "", filename),
            )
            msg.attach(part)
            logger.debug(f"Bifogat {filename} ({len(data)} bytes)")

        try:
            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)

            logger.info(f"Spårningsmail skickat till {to_email} för order {order_no}")
            return True

        except Exception as e:
            logger.error(
                f"Kunde inte skicka mail för order {order_no} "
                f"till {to_email}: {e}"
            )
            return False

    def _get_logo_data_uri(self, filename: str) -> str:
        """Returnerar logotyp som data URI (base64) för inbädding i HTML."""
        logo_path = _ASSETS_DIR / filename
        if logo_path.exists():
            try:
                data = logo_path.read_bytes()
                b64 = base64.b64encode(data).decode("ascii")
                return f"data:image/png;base64,{b64}"
            except Exception as e:
                logger.warning(f"Kunde inte ladda logotyp {filename}: {e}")
        return ""

    def _get_dhl_logo_data_uri(self) -> str:
        """Returnerar DHL-logotyp som data URI."""
        return self._get_logo_data_uri("dhl_logo.png")

    def _build_html(
        self,
        order_no: str,
        tracking_number: str,
        tracking_url: str,
        carrier: CarrierType,
        carrier_name: str,
        service_description: str = "",
        dhl_hamta_id: str = "",
        custom_message: str = "",
        has_attachments: bool = False,
        google_review_url: str = "",
        company_email: str = "",
        company_phone: str = "",
        texts: dict = None,
        lang: str = "sv",
        estimated_delivery_date: str = "",
    ) -> str:
        """Bygger HTML-mailkropp — professionell B2B-frakbekräftelse."""
        texts = texts or EMAIL_TEXTS.get(lang, EMAIL_TEXTS["sv"])
        msg_html = f'<p style="color:#555; line-height:1.6;">{custom_message}</p>' if custom_message else ""
        attachments_note = (
            f'<p style="color:#666; font-size:14px; margin-top:20px;">{texts["attachments_note"]}</p>'
            if has_attachments
            else ""
        )
        hamta_link = ""
        if carrier == CarrierType.DHL and dhl_hamta_id:
            hamta_url = DHL_HAMTA_URL.format(tracking=dhl_hamta_id)
            hamta_link = f'''
            <div style="margin:16px 0 0; padding-top:16px; border-top:1px solid #e2e8f0;">
              <a href="{hamta_url}" style="display:inline-block; color:#0f172a; font-size:14px; font-weight:500; text-decoration:none; padding:10px 18px; border:1px solid #cbd5e1; border-radius:8px; background:#ffffff;">📍 {texts["hamta_btn"]}</a>
              <p style="margin:8px 0 0; color:#94a3b8; font-size:11px;">{texts["hamta_note"]}</p>
            </div>'''

        carrier_logo_html = ""
        if carrier == CarrierType.DHL:
            dhl_logo = self._get_dhl_logo_data_uri()
            if dhl_logo:
                carrier_logo_html = f'<img src="{dhl_logo}" alt="DHL" width="80" height="auto" style="max-width:80px; height:auto; display:block; margin:0 auto 12px;" />'
        ernstp_logo = self._get_logo_data_uri("ernstp_logo.png")
        header_logo_html = f'<img src="{ernstp_logo}" alt="{self.from_name}" width="120" height="auto" style="max-width:120px; height:auto; display:block; margin:0 auto 12px;" />' if ernstp_logo else f'<img src="https://ernstp.se/wp-content/uploads/2020/05/ernstp.jpg" alt="{self.from_name}" width="120" height="auto" style="max-width:120px; height:auto; display:block; margin:0 auto 12px;" />'
        estimated_delivery_line = ""
        if estimated_delivery_date and estimated_delivery_date.strip():
            label = texts.get("estimated_delivery", "Estimated delivery")
            estimated_delivery_line = f'<p style="margin:0 0 16px; color:#0f172a; font-size:15px;"><strong>📅 {label}:</strong> {estimated_delivery_date.strip()}</p>'
        service_line = (
            f'<p style="margin:0 0 16px; color:#94a3b8; font-size:13px;">{service_description}</p>'
            if service_description and service_description != carrier_name else ""
        )
        carrier_phone, carrier_link = CARRIER_CONTACT.get(carrier, ("", ""))
        contact_section = ""
        if carrier_phone or carrier_link or company_email or company_phone:
            carrier_line = ""
            if carrier_phone or carrier_link:
                parts = []
                if carrier_phone:
                    parts.append(carrier_phone)
                if carrier_link:
                    contact = texts.get("contact_carrier", "Contact")
                    parts.append(f'<a href="{carrier_link}" style="color:#0f172a; text-decoration:underline;">{contact} {carrier_name}</a>')
                carrier_line = f'<p style="margin:0 0 6px; color:#64748b; font-size:13px;"><strong>{texts["shipping_questions"]}</strong> {carrier_name}: {" · ".join(parts)}</p>'
            company_line = ""
            if company_email or company_phone:
                email_part = f'<a href="mailto:{company_email}" style="color:#0f172a; text-decoration:underline;">{company_email}</a>' if company_email else ""
                phone_part = company_phone or ""
                company_line = f'<p style="margin:0; color:#64748b; font-size:13px;"><strong>{texts["other_questions"]}</strong> {email_part} · {phone_part}</p>'
            contact_section = f'''
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0; border-radius:8px; margin-top:24px; background:#f8fafc;">
              <tr><td style="padding:16px;">
                {carrier_line}
                {company_line}
              </td></tr>
            </table>'''

        review_cta = ""
        if google_review_url:
            review_cta = f'''
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fef3c7; border:1px solid #fcd34d; border-radius:10px; margin:24px 0;">
              <tr>
                <td style="padding:20px; text-align:center;">
                  <p style="margin:0 0 12px; color:#92400e; font-size:14px; font-weight:600;">⭐ {texts["review_title"]}</p>
                  <p style="margin:0 0 16px; color:#b45309; font-size:13px;">{texts["review_sub"]}</p>
                  <a href="{google_review_url}" style="display:inline-block; background:#f59e0b; color:#ffffff !important; text-decoration:none; padding:12px 24px; border-radius:8px; font-size:14px; font-weight:600;">{texts["review_btn"]}</a>
                </td>
              </tr>
            </table>'''

        return f"""\
<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Order {order_no}</title>
  <style>
    body {{ margin: 0; padding: 0; background: #f4f4f5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }}
    .email {{ max-width: 520px; margin: 0 auto; background: #ffffff; }}
  </style>
</head>
<body>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5; padding: 32px 16px;">
    <tr><td align="center">
      <table role="presentation" class="email" width="520" cellpadding="0" cellspacing="0" style="background:#ffffff; border-radius:12px; overflow:hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
        <!-- Header -->
        <tr>
          <td style="background:#1e293b; padding: 28px 32px; text-align:center;">
            {header_logo_html}
            <h1 style="margin:0; color:#ffffff; font-size:22px; font-weight:600; letter-spacing:0.5px;">{self.from_name}</h1>
            <p style="margin:8px 0 0; color:#94a3b8; font-size:13px;">{texts["header_subtitle"]}</p>
          </td>
        </tr>
        <!-- Content -->
        <tr>
          <td style="padding: 36px 32px 32px;">
            <h2 style="margin:0 0 8px; color:#0f172a; font-size:20px; font-weight:600;">{texts["title"]}</h2>
            <p style="margin:0 0 8px; color:#64748b; font-size:15px;">{texts["intro"].format(order=order_no, carrier=carrier_name)}</p>
            {estimated_delivery_line}
            {service_line}
            {carrier_logo_html}

            <!-- Tracking card -->
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; margin-bottom:24px;">
              <tr>
                <td style="padding: 24px; text-align:center;">
                  <p style="margin:0 0 6px; color:#64748b; font-size:12px; text-transform:uppercase; letter-spacing:0.8px;">{texts["tracking_label"]}</p>
                  <p style="margin:0 0 20px; color:#0f172a; font-size:18px; font-weight:700; font-family: monospace; letter-spacing:1px;">{tracking_number}</p>
                  <a href="{tracking_url}" style="display:inline-block; background:#0f172a; color:#ffffff !important; text-decoration:none; padding:14px 28px; border-radius:8px; font-size:15px; font-weight:600;">{texts["track_btn"]}</a>
                  {hamta_link}
                </td>
              </tr>
            </table>

            {review_cta}
            {attachments_note}
            {msg_html}
            {contact_section}

            <p style="margin:28px 0 0; color:#334155; font-size:15px;">{texts["signoff"]}<br><strong>{self.from_name}</strong></p>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:#f8fafc; padding: 20px 32px; text-align:center; border-top:1px solid #e2e8f0;">
            <p style="margin:0; color:#94a3b8; font-size:12px;">{texts["footer"]}</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
