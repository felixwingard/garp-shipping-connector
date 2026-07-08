"""Tack-rad med recensions-QR på DHL-etikettens tomma nederkant.

DHL:s etiketter (105×210 mm) har en fri remsa på ~19 mm längst ned på alla
produkter vi bokar. Här stämplas Ernst P-emblemet, en tack-text och en QR-kod
till Googles recensionssida innan etiketten går till skrivaren.

Layouten är verifierad mot sandbox-etiketter för 102/103/109/210/211 samt
skarpa etiketter — remsan ligger på samma ställe överallt. QR på 17 mm ger
~4 skrivarpunkter per modul på Zebra 203 dpi.

Får ALDRIG stoppa en utskrift: vid minsta fel returneras originaletiketten.
"""

import io
import logging
import math
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)

_MARGIN = 5 * mm
_QR_SIZE = 17 * mm      # max i den ~19 mm fria remsan utan att nudda DHL-text
_LOGO_SIZE = 16 * mm
_BOTTOM = 1.5 * mm

_DEFAULT_TITLE = "Tack för din order!"
_DEFAULT_LINE1 = "Nöjd med Ernst P AB? Skanna koden"
_DEFAULT_LINE2 = "och lämna ett omdöme på Google."

_LOGO_PATH = Path(__file__).resolve().parents[2] / "assets" / "ernstp_logo.png"


def _qr_drawing(url: str, size_pt: float) -> Drawing:
    widget = QrCodeWidget(url, barLevel="M")
    x0, y0, x1, y1 = widget.getBounds()
    d = Drawing(
        size_pt, size_pt,
        transform=[size_pt / (x1 - x0), 0, 0, size_pt / (y1 - y0), 0, 0],
    )
    d.add(widget)
    return d


def _draw_star(c: canvas.Canvas, cx: float, cy: float, r: float) -> None:
    """Solid femuddig stjärna som vektorbana (fontoberoende)."""
    path = c.beginPath()
    pts = []
    for i in range(10):
        ang = math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.4
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    path.moveTo(*pts[0])
    for pt in pts[1:]:
        path.lineTo(*pt)
    path.close()
    c.drawPath(path, fill=1, stroke=0)


def _build_overlay(page_w: float, page_h: float, cfg: dict, url: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    y0 = _BOTTOM
    qr = _QR_SIZE

    want_logo = cfg.get("logo", True)
    if want_logo and not _LOGO_PATH.exists():
        logger.warning(f"Logotyp saknas ({_LOGO_PATH}) — stämplar stjärnor i stället")
        want_logo = False

    if want_logo:
        # Emblemet till vänster, text bredvid
        c.drawImage(
            str(_LOGO_PATH), _MARGIN, y0 + 0.5 * mm,
            width=_LOGO_SIZE, height=_LOGO_SIZE,
            preserveAspectRatio=True, mask="auto", anchor="sw",
        )
        tx = _MARGIN + _LOGO_SIZE + 3.5 * mm
        title_x, title_y = tx, y0 + qr - 12
    else:
        # ★★★★★ till vänster om rubriken, brödtext från vänsterkanten
        for i in range(5):
            _draw_star(c, _MARGIN + 4.6 + i * 12.4, y0 + qr - 9, 5.0)
        tx = _MARGIN
        title_x, title_y = _MARGIN + 24 * mm, y0 + qr - 13

    c.setFont("Helvetica-Bold", 10)
    c.drawString(title_x, title_y, cfg.get("title", _DEFAULT_TITLE))
    c.setFont("Helvetica", 8)
    c.drawString(tx, y0 + qr - 27, cfg.get("line1", _DEFAULT_LINE1))
    c.drawString(tx, y0 + qr - 37, cfg.get("line2", _DEFAULT_LINE2))
    renderPDF.draw(_qr_drawing(url, qr), c, page_w - _MARGIN - qr, y0)
    c.save()
    buf.seek(0)
    return buf.getvalue()


def stamp_review_footer(label_pdf: bytes, config: dict) -> bytes:
    """Stämplar tack-rad + recensions-QR på varje sida i etikett-PDF:en.

    config är hela app-konfigurationen. Styrs av label_stamp-sektionen;
    recensionslänken tas från label_stamp.review_url med fallback till
    smtp.google_review_url (samma länk som i kundmailen).

    Returnerar originalbytes oförändrade om stämpling är avstängd,
    länk saknas eller något går fel — utskriften får aldrig stoppas.
    """
    cfg = (config or {}).get("label_stamp") or {}
    if not cfg.get("enabled", False):
        return label_pdf

    url = (cfg.get("review_url") or "").strip() or (
        (config.get("smtp") or {}).get("google_review_url") or ""
    ).strip()
    if not url:
        logger.warning(
            "label_stamp aktiv men ingen recensionslänk "
            "(label_stamp.review_url / smtp.google_review_url) — hoppar över"
        )
        return label_pdf

    try:
        from pypdf import PdfReader, PdfWriter

        writer = PdfWriter(clone_from=io.BytesIO(label_pdf))
        for page in writer.pages:
            w = float(page.mediabox.width)
            h = float(page.mediabox.height)
            overlay = PdfReader(io.BytesIO(_build_overlay(w, h, cfg, url)))
            page.merge_page(overlay.pages[0])
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception as e:
        logger.warning(f"Kunde inte stämpla tack-rad på etikett: {e} — skriver ut original")
        return label_pdf
