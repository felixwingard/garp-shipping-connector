"""Sändningslogg — sparar alla sändningar till Excel för enkel spårning.

En Excel-fil (sandningslogg.xlsx) i programmets rotmapp som uppdateras
vid varje lyckad bokning. Kan öppnas direkt i Excel för sökning.
"""

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import get_base_dir

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()

_HEADERS = [
    "Datum",
    "Ordernr",
    "Spårningsnummer",
    "Transportör",
    "Produkt",
    "Mottagare",
    "Adress",
    "Postnummer",
    "Stad",
    "Land",
    "Vikt (kg)",
    "Kolli",
    "E-post",
    "Telefon",
    "Pris",
]

_COL_WIDTHS = {
    "A": 18, "B": 18, "C": 26, "D": 12, "E": 10,
    "F": 24, "G": 28, "H": 12, "I": 16, "J": 8,
    "K": 10, "L": 8, "M": 24, "N": 16, "O": 12,
}


def _log_path() -> Path:
    return get_base_dir() / "sandningslogg.xlsx"


def append_shipment(
    order_no: str,
    tracking: str,
    carrier: str,
    product_code: str,
    receiver_name: str = "",
    receiver_address: str = "",
    receiver_zipcode: str = "",
    receiver_city: str = "",
    receiver_country: str = "",
    receiver_email: str = "",
    receiver_phone: str = "",
    weight_kg: float = 0,
    copies: int = 1,
    estimated_price: str = "",
) -> None:
    """Lägger till en sändning i sändningsloggen (Excel)."""
    try:
        from openpyxl import Workbook, load_workbook
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        logger.warning("openpyxl saknas — kör 'pip install openpyxl' för sändningslogg")
        return

    with _LOCK:
        path = _log_path()
        datestr = datetime.now().strftime("%Y-%m-%d %H:%M")
        row_data = [
            datestr,
            order_no,
            tracking,
            carrier,
            product_code,
            receiver_name,
            receiver_address,
            receiver_zipcode,
            receiver_city,
            receiver_country,
            weight_kg if weight_kg else "",
            copies if copies else "",
            receiver_email,
            receiver_phone,
            estimated_price,
        ]

        try:
            if path.exists():
                wb = load_workbook(path, read_only=False)
                ws = wb.active
                ws.append(row_data)
            else:
                wb = Workbook()
                ws = wb.active
                ws.title = "Sändningar"
                header_font = Font(bold=True, size=11)
                header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
                header_text = Font(bold=True, size=11, color="FFFFFF")
                for col, h in enumerate(_HEADERS, 1):
                    cell = ws.cell(row=1, column=col, value=h)
                    cell.font = header_text
                    cell.fill = header_fill
                    cell.alignment = Alignment(horizontal="center")
                for letter, width in _COL_WIDTHS.items():
                    ws.column_dimensions[letter].width = width
                ws.auto_filter.ref = f"A1:O1"
                ws.freeze_panes = "A2"
                ws.append(row_data)

            wb.save(path)
            wb.close()
        except Exception as e:
            logger.warning(f"Kunde inte skriva sändningslogg: {e}")
