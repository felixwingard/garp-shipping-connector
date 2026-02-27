"""Bring bulk — spårning av ordrar och Excel-export som backup."""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .config import get_base_dir

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()

_ORDERS_FILE = "bulk_orders.json"
_EXPORTS_DIR = "bulk_exports"


def _orders_path() -> Path:
    return get_base_dir() / _ORDERS_FILE


def _exports_dir() -> Path:
    d = get_base_dir() / _EXPORTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def append_bring_bulk_order(
    bulk_id: str,
    order_no: str,
    tracking: str,
    weight_kg: float,
    kolli: int,
) -> None:
    """Lägger till en order i bulk-ordersfilen (anropas vid varje lyckad Bring bulk-bokning)."""
    if not bulk_id or not bulk_id.strip():
        return
    bulk_id = bulk_id.strip()
    with _LOCK:
        path = _orders_path()
        data: dict[str, list[dict[str, Any]]] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Kunde inte ladda bulk_orders: {e}")
        if bulk_id not in data:
            data[bulk_id] = []
        data[bulk_id].append({
            "order_no": order_no,
            "tracking": tracking,
            "weight_kg": weight_kg,
            "kolli": kolli,
        })
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")


def get_bulk_orders(bulk_id: str) -> list[dict[str, Any]]:
    """Returnerar ordrar sparade för bulk_id."""
    bulk_id = (bulk_id or "").strip()
    if not bulk_id:
        return []
    with _LOCK:
        path = _orders_path()
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return list(data.get(bulk_id, []))
        except Exception as e:
            logger.warning(f"Kunde inte ladda bulk_orders: {e}")
            return []


def clear_bulk_orders(bulk_id: str) -> None:
    """Tar bort ordrar för bulk_id från filen (efter export)."""
    bulk_id = (bulk_id or "").strip()
    if not bulk_id:
        return
    with _LOCK:
        path = _orders_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.pop(bulk_id, None)
            if data:
                path.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
            else:
                path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Kunde inte rensa bulk_orders: {e}")


def export_bulk_to_excel(
    bulk_id: str,
    total_weight_kg: int,
    num_packages: int,
    num_pallets: int,
    num_direct_pallets: int = 0,
    direct_pallets_weight_kg: int = 0,
    num_invoices: int = 3,
    waybill_url: str = "",
    routing_url: str = "",
    orders: Optional[list[dict[str, Any]]] = None,
) -> Optional[Path]:
    """Skapar Excel-backup av bulk-sändningen. Returnerar sökväg till filen eller None vid fel."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
    except ImportError:
        logger.warning("openpyxl ej installerad — Excel-export hoppas över")
        return None

    orders = orders or []
    safe_bulk = bulk_id.replace("/", "-").replace("\\", "-").strip()
    datestr = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"Bring_Bulk_{safe_bulk}_{datestr}.xlsx"
    filepath = _exports_dir() / filename

    wb = Workbook()

    # --- Blad 1: Sammanfattning ---
    ws = wb.active
    ws.title = "Sammanfattning"
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 28

    row = 1
    ws.cell(row=row, column=1, value="Bring Bulk — Backup").font = Font(bold=True, size=14)
    row += 2
    rows_data = [
        ("Bulk-ID", bulk_id),
        ("Datum", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Totalvikt (kg)", total_weight_kg),
        ("Antal kolli (paket)", num_packages),
        ("Antal pall (Bulk)", num_pallets),
        ("Hel pall till kund (antal)", num_direct_pallets),
        ("Hel pall till kund (vikt kg)", direct_pallets_weight_kg),
        ("Antal fakturakopior", num_invoices),
    ]
    for label, val in rows_data:
        ws.cell(row=row, column=1, value=label).font = Font(bold=True)
        ws.cell(row=row, column=2, value=val)
        row += 1
    if waybill_url:
        ws.cell(row=row, column=1, value="CMR-waybill").font = Font(bold=True)
        ws.cell(row=row, column=2, value=waybill_url)
        row += 1
    if routing_url:
        ws.cell(row=row, column=1, value="Routing labels").font = Font(bold=True)
        ws.cell(row=row, column=2, value=routing_url)

    # --- Blad 2: Ordrar ---
    ws2 = wb.create_sheet("Ordrar", 1)
    headers = ["Ordernr", "Spårningsnummer", "Vikt (kg)", "Kolli"]
    for col, h in enumerate(headers, 1):
        ws2.cell(row=1, column=col, value=h).font = Font(bold=True)
    for i, o in enumerate(orders, 2):
        ws2.cell(row=i, column=1, value=o.get("order_no", ""))
        ws2.cell(row=i, column=2, value=o.get("tracking", ""))
        ws2.cell(row=i, column=3, value=o.get("weight_kg"))
        ws2.cell(row=i, column=4, value=o.get("kolli", 1))
    if orders:
        ws2.column_dimensions["A"].width = 18
        ws2.column_dimensions["B"].width = 24

    wb.save(filepath)
    logger.info(f"Bulk Excel-backup sparad: {filepath}")
    return filepath
