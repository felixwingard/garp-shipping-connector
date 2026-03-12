"""ADR-godsdeklaration — genererar PDF enligt MSB/ADR 5.4.1.

Godsdeklarationen upprättas av avsändaren. Uppgifterna behöver inte anges
på ett speciellt formulär utan brukar normalt lämnas på en vanlig fraktsedel.
Se: https://www.mcf.se/.../godsdeklaration-vid-transport-pa-vag/
"""

import io
import logging
from datetime import date
from typing import TYPE_CHECKING

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

if TYPE_CHECKING:
    from ..parsers.models import DangerousGoodsInfo, Shipment

logger = logging.getLogger(__name__)


def _safe(s: str) -> str:
    return (s or "").strip()


def _sender_address(sender: dict) -> str:
    parts = [
        _safe(sender.get("name", "")),
        _safe(sender.get("address1", "")),
        _safe(sender.get("address2", "")),
        f"{_safe(sender.get('zipcode', ''))} {_safe(sender.get('city', ''))}".strip(),
        _safe(sender.get("country", "")),
    ]
    return "\n".join(p for p in parts if p)


def _receiver_address(receiver) -> str:
    if not receiver:
        return ""
    parts = [
        _safe(receiver.name),
        _safe(receiver.address1),
        _safe(receiver.address2),
        f"{_safe(receiver.zipcode)} {_safe(receiver.city)}".strip(),
        _safe(receiver.country),
    ]
    return "\n".join(p for p in parts if p)


def _total_quantity(shipment: "Shipment", dg: "DangerousGoodsInfo") -> str:
    if dg.quantity:
        return dg.quantity
    if not shipment.containers:
        return "—"
    total = sum(c.weight or 0 for c in shipment.containers)
    count = sum(c.copies for c in shipment.containers)
    if total > 0:
        return f"{total:.1f} kg ({count} kolli)"
    return f"{count} kolli"


def _container_description(shipment: "Shipment") -> str:
    if not shipment.containers:
        return "—"
    parts = []
    for c in shipment.containers:
        n = c.copies
        desc = c.contents or c.measure or "kolli"
        if n > 1:
            parts.append(f"{n} × {desc}")
        else:
            parts.append(desc)
    return "; ".join(parts)


def generate_adr_declaration(
    shipment: "Shipment",
    dg: "DangerousGoodsInfo",
    sender_config: dict,
) -> bytes:
    """Genererar ADR-godsdeklaration som PDF.

    Följer MSB/ADR 5.4.1. Dokumentet kan skrivas ut och signeras manuellt.

    Args:
        shipment: Sändning med receiver, containers etc.
        dg: Farligt gods-info (UN-nummer, klass, packningsgrupp, benämning)
        sender_config: config["sender"] — namn, adress, zipcode, city, country

    Returns:
        PDF som bytes.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=13)
    body_small = ParagraphStyle("BodySmall", parent=body, fontSize=9, leading=11)
    label_style = ParagraphStyle("Label", parent=body, fontSize=8, leading=10, textColor=HexColor("#64748b"))
    title_style = ParagraphStyle("DGTitle", parent=styles["Heading1"], fontSize=16, spaceAfter=2)
    subtitle_style = ParagraphStyle("Subtitle", parent=body, fontSize=10, textColor=HexColor("#64748b"))

    elements = []

    # Title
    elements.append(Paragraph("Godsdeklaration — farligt gods (ADR)", title_style))
    elements.append(Paragraph(f"Order: {_safe(shipment.order_no)}", subtitle_style))
    elements.append(Spacer(1, 8 * mm))

    # Goods info
    quantity = _total_quantity(shipment, dg)
    container_desc = _container_description(shipment)
    sender_addr = _sender_address(sender_config)
    receiver_addr = _receiver_address(shipment.receiver)

    proper_name = _safe(dg.proper_shipping_name) or _safe(dg.technical_name) or "—"
    tech_name = _safe(dg.technical_name)
    flash = f"Flampunkt: {dg.flash_point} °C" if dg.flash_point else ""

    un_line = f"UN {dg.un_number}"
    if proper_name and proper_name != "—":
        un_line += f"  {proper_name}"
    if dg.adr_class:
        un_line += f",  {dg.adr_class}"
    if dg.packing_group:
        un_line += f",  PG {dg.packing_group}"

    data = [
        [Paragraph("UN-nummer, benämning, klass, PG", label_style),
         Paragraph(f"<b>{un_line}</b>", body)],
        [Paragraph("Officiell transportbenämning", label_style),
         Paragraph(proper_name, body)],
        [Paragraph("Teknisk benämning", label_style),
         Paragraph(tech_name or "—", body_small)],
        [Paragraph("ADR-klass / Etikettnummer", label_style),
         Paragraph(f"<b>{_safe(dg.adr_class) or '—'}</b>", body)],
        [Paragraph("Förpackningsgrupp", label_style),
         Paragraph(f"PG {dg.packing_group}" if dg.packing_group else "—", body)],
        [Paragraph("Flampunkt", label_style),
         Paragraph(flash or "—", body)],
        [Paragraph("Antal kollin och beskrivning", label_style),
         Paragraph(container_desc, body_small)],
        [Paragraph("Total mängd", label_style),
         Paragraph(f"<b>{quantity}</b>", body)],
    ]

    t = Table(data, colWidths=[55 * mm, 110 * mm])
    t.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cbd5e1")),
                ("BACKGROUND", (0, 0), (0, -1), HexColor("#f8fafc")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    elements.append(t)
    elements.append(Spacer(1, 8 * mm))

    # Parties
    party_data = [
        [Paragraph("Avsändare", label_style),
         Paragraph("Mottagare", label_style)],
        [Paragraph((sender_addr or "—").replace("\n", "<br/>"), body_small),
         Paragraph((receiver_addr or "—").replace("\n", "<br/>"), body_small)],
    ]
    pt = Table(party_data, colWidths=[82.5 * mm, 82.5 * mm])
    pt.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cbd5e1")),
                ("BACKGROUND", (0, 0), (-1, 0), HexColor("#f8fafc")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    elements.append(pt)
    elements.append(Spacer(1, 12 * mm))

    # Confirmation
    elements.append(
        Paragraph(
            "Härmed intygas att innehållet i denna sändning är fullständigt och korrekt beskrivet "
            "ovan med korrekt UN-nummer, officiell transportbenämning, klass och förpackningsgrupp, "
            "och att godset är korrekt klassificerat, förpackat, märkt och etiketterat "
            "samt i övrigt i godtagbart skick för transport i enlighet med tillämpliga bestämmelser.",
            ParagraphStyle("Confirm", parent=body, fontSize=9, leading=12, textColor=HexColor("#374151")),
        )
    )
    elements.append(Spacer(1, 10 * mm))

    sig_data = [
        [Paragraph("Datum", label_style), Paragraph("Namnförtydligande", label_style),
         Paragraph("Underskrift", label_style)],
        ["", "", ""],
    ]
    st = Table(sig_data, colWidths=[45 * mm, 60 * mm, 60 * mm], rowHeights=[None, 20 * mm])
    st.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cbd5e1")),
                ("BACKGROUND", (0, 0), (-1, 0), HexColor("#f8fafc")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    elements.append(st)
    elements.append(Spacer(1, 4 * mm))

    elements.append(
        Paragraph(
            f"Genererad: {date.today().isoformat()} — ADR 5.4.1",
            ParagraphStyle("Small", parent=body, fontSize=7, textColor=HexColor("#94a3b8")),
        )
    )

    doc.build(elements)
    return buffer.getvalue()
