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
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

if TYPE_CHECKING:
    from ..parsers.models import DangerousGoodsInfo, Shipment

logger = logging.getLogger(__name__)


def _safe(s: str) -> str:
    """Säkerställ läsbar sträng för PDF."""
    return (s or "").strip()


def _sender_address(sender: dict) -> str:
    """Bygger avsändaradress från config."""
    parts = [
        _safe(sender.get("name", "")),
        _safe(sender.get("address1", "")),
        _safe(sender.get("address2", "")),
        f"{_safe(sender.get('zipcode', ''))} {_safe(sender.get('city', ''))}".strip(),
        _safe(sender.get("country", "")),
    ]
    return "\n".join(p for p in parts if p)


def _receiver_address(receiver) -> str:
    """Bygger mottagaradress från Receiver."""
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


def _total_quantity(shipment: "Shipment") -> str:
    """Beräknar total mängd från containers (vikt)."""
    if not shipment.containers:
        return "—"
    total = sum(c.weight * c.copies for c in shipment.containers)
    count = sum(c.copies for c in shipment.containers)
    if total > 0:
        return f"{total:.1f} kg ({count} kolli)"
    return f"{count} kolli"


def _container_description(shipment: "Shipment") -> str:
    """Antal kollin och beskrivning (punkt e)."""
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
        dg: Farligt gods-info (UN-nummer, klass, packningsgrupp, teknisk beteckning)
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
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=10,
        leading=12,
    )
    title_style = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontSize=14,
        spaceAfter=6,
    )

    elements = []

    elements.append(Paragraph("Godsdeklaration – farligt gods (ADR)", title_style))
    elements.append(Spacer(1, 4 * mm))

    elements.append(Paragraph(f"Order: {_safe(shipment.order_no)}", body_style))
    elements.append(Spacer(1, 6 * mm))

    # Tabell med obligatoriska uppgifter a–k
    quantity = _total_quantity(shipment)
    container_desc = _container_description(shipment)
    sender_addr = _sender_address(sender_config)
    receiver_addr = _receiver_address(shipment.receiver)

    flash = f" Flashpunkt: {dg.flash_point} °C" if dg.flash_point else ""

    data = [
        ["a. UN-nummer + transportbenämning", f"UN {dg.un_number} {_safe(dg.technical_name)}{flash}"],
        ["b. Officiell transportbenämning", _safe(dg.technical_name) or "—"],
        ["c. Etikettnummer / ADR-klass", _safe(dg.adr_class) or "—"],
        ["d. Förpackningsgrupp", f"PG {dg.packing_group}" if dg.packing_group else "—"],
        ["e. Antal kollin och beskrivning", container_desc],
        ["f. Total mängd", quantity],
        ["g. Avsändare", Paragraph((sender_addr or "—").replace("\n", "<br/>"), body_style)],
        ["h. Mottagare", Paragraph((receiver_addr or "—").replace("\n", "<br/>"), body_style)],
    ]

    t = Table(data, colWidths=[70 * mm, 100 * mm])
    t.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.5, (0.5, 0.5, 0.5)),
                ("BACKGROUND", (0, 0), (0, -1), (0.95, 0.95, 0.95)),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    elements.append(t)
    elements.append(Spacer(1, 10 * mm))

    elements.append(
        Paragraph(
            "Avsändaren bekräftar att ovanstående uppgifter är korrekta.",
            body_style,
        )
    )
    elements.append(Spacer(1, 4 * mm))
    elements.append(
        Paragraph(
            f"Datum: _______________  Namnteckning: _______________",
            body_style,
        )
    )
    elements.append(Spacer(1, 2 * mm))
    elements.append(
        Paragraph(
            f"Genererad: {date.today().isoformat()}",
            ParagraphStyle("Small", parent=body_style, fontSize=8, textColor=(0.5, 0.5, 0.5)),
        )
    )

    doc.build(elements)
    return buffer.getvalue()
