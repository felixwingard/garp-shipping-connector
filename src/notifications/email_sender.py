"""E-postnotifieringar till kunder med spårningslänk.

Skickar "tack för din order"-mail med spårningsnummer och
direktlänk till transportörens spårningssida.
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from ..parsers.models import CarrierType

logger = logging.getLogger(__name__)


# Spårningslänkar per transportör
TRACKING_URLS = {
    CarrierType.DHL: "https://www.dhl.com/se-sv/home/tracking.html?tracking-id={tracking}",
}

CARRIER_NAMES = {
    CarrierType.DHL: "DHL",
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

    def send_tracking_email(
        self,
        to_email: str,
        order_no: str,
        tracking_number: str,
        carrier: CarrierType,
        custom_message: str = "",
    ) -> bool:
        """Skickar spårningsmail till kund.

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

        subject = f"Din order {order_no} har skickats!"
        html_body = self._build_html(
            order_no=order_no,
            tracking_number=tracking_number,
            tracking_url=tracking_url,
            carrier_name=carrier_name,
            custom_message=custom_message,
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{self.from_name} <{self.from_addr}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))

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

    def _build_html(
        self,
        order_no: str,
        tracking_number: str,
        tracking_url: str,
        carrier_name: str,
        custom_message: str,
    ) -> str:
        """Bygger HTML-mailkropp."""
        msg_html = f"<p>{custom_message}</p>" if custom_message else ""

        return f"""\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto; }}
    .header {{ background: #2c3e50; color: white; padding: 20px; text-align: center; }}
    .content {{ padding: 20px; }}
    .tracking-box {{ background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px; padding: 15px; margin: 20px 0; text-align: center; }}
    .tracking-number {{ font-size: 18px; font-weight: bold; color: #2c3e50; }}
    .btn {{ display: inline-block; background: #e74c3c; color: white; text-decoration: none; padding: 12px 24px; border-radius: 5px; margin: 10px 0; }}
    .footer {{ color: #999; font-size: 12px; text-align: center; padding: 20px; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>{self.from_name}</h1>
  </div>
  <div class="content">
    <h2>Din order {order_no} har skickats!</h2>
    <p>Vi har skickat din order med {carrier_name}.</p>

    <div class="tracking-box">
      <p>Spårningsnummer:</p>
      <p class="tracking-number">{tracking_number}</p>
      <a href="{tracking_url}" class="btn">Spåra din leverans</a>
    </div>

    {msg_html}

    <p>Vänliga hälsningar,<br>{self.from_name}</p>
  </div>
  <div class="footer">
    <p>Detta mail skickades automatiskt. Svara inte på detta mail.</p>
  </div>
</body>
</html>"""
