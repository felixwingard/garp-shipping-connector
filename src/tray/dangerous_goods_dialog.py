"""Dialog för att ange farligt gods (ADR) — används när sidecar-fil saknas.

UN-nummer slås upp automatiskt via GitHub (tantalor/un) för att fylla i
transportbenämning och ADR-klass.
"""

import json
import logging
import platform
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Optional, Callable

from ..parsers.models import DangerousGoodsInfo

logger = logging.getLogger(__name__)

UN_LOOKUP_URL = "https://raw.githubusercontent.com/tantalor/un/master/data/{un}.json"

ADR_CLASSES = [
    "",
    "1 — Explosiva",
    "2 — Gaser",
    "3 — Brandfarliga vätskor",
    "4.1 — Brandfarliga fasta",
    "4.2 — Självantändande",
    "4.3 — Brandfarlig gas vid vatten",
    "5.1 — Oxiderande",
    "5.2 — Organiska peroxider",
    "6.1 — Giftiga",
    "6.2 — Smittförande",
    "7 — Radioaktiva",
    "8 — Frätande",
    "9 — Övriga farliga",
]

TUNNEL_CODES = ["", "(B)", "(B/D)", "(B/E)", "(C)", "(C/D)", "(C/E)", "(D)", "(D/E)", "(E)", "(-)"]

_ADR_CLASS_INDEX = {}
for _i, _item in enumerate(ADR_CLASSES):
    _code = _item.split("—")[0].strip()
    if _code:
        _ADR_CLASS_INDEX[_code] = _i


def _font():
    return "Segoe UI" if platform.system() == "Windows" else "Helvetica Neue"


def _adr_class_value(display: str) -> str:
    return display.split("—")[0].strip() if display else ""


def _lookup_un_number(un: str) -> Optional[dict]:
    import urllib.request
    try:
        url = UN_LOOKUP_URL.format(un=un.strip().lstrip("0") or un.strip())
        resp = urllib.request.urlopen(url, timeout=5)
        return json.loads(resp.read())
    except Exception:
        pass
    try:
        url = UN_LOOKUP_URL.format(un=un.strip().zfill(4))
        resp = urllib.request.urlopen(url, timeout=5)
        return json.loads(resp.read())
    except Exception:
        return None


class DangerousGoodsDialog(tk.Toplevel):
    """Dialog för att ange farligt gods (UN-nummer, ADR-klass, etc.)."""

    def __init__(
        self,
        parent: tk.Tk,
        order_no: str,
        xml_filepath: str,
        on_confirm: Optional[Callable[[DangerousGoodsInfo, bool], None]] = None,
    ):
        super().__init__(parent)
        self.order_no = order_no
        self.xml_filepath = Path(xml_filepath)
        self.on_confirm = on_confirm
        self._result: Optional[DangerousGoodsInfo] = None
        self._lookup_after_id = None

        self.title(f"Farligt gods — order {order_no}")
        self.configure(bg="#fafafa")
        self.resizable(True, True)

        self._build_ui()

        self.update_idletasks()
        w = max(self.winfo_reqwidth() + 40, 500)
        h = max(self.winfo_reqheight() + 20, 500)
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.focus_force()
        self.grab_set()

    def _build_ui(self):
        main = tk.Frame(self, bg="#fafafa")
        main.pack(fill="both", expand=True, padx=20, pady=16)

        # --- Header ---
        tk.Label(
            main,
            text=f"Order {self.order_no} — farligt gods",
            font=(_font(), 12, "bold"),
            fg="#991b1b",
            bg="#fafafa",
        ).pack(anchor="w")
        tk.Label(
            main,
            text="Fyll i ADR-uppgifterna. De används för bokning och godsdeklaration.",
            font=(_font(), 9),
            fg="#64748b",
            bg="#fafafa",
        ).pack(anchor="w", pady=(2, 12))

        # --- UN-nummer ---
        tk.Label(main, text="UN-nummer *", font=(_font(), 9, "bold"),
                 fg="#334155", bg="#fafafa").pack(anchor="w")
        un_row = tk.Frame(main, bg="#fafafa")
        un_row.pack(fill="x", pady=(2, 0))
        self.un_number_var = tk.StringVar()
        self.un_number_var.trace_add("write", self._on_un_changed)
        ttk.Entry(un_row, textvariable=self.un_number_var, width=10).pack(side="left")
        self.un_status_label = tk.Label(un_row, text="  4 siffror → auto-ifyllning",
                                        font=(_font(), 8), fg="#94a3b8", bg="#fafafa")
        self.un_status_label.pack(side="left", padx=(8, 0))

        self._sep(main)

        # --- Officiell transportbenämning ---
        self.proper_name_var = tk.StringVar()
        self._labeled_entry(main, "Officiell transportbenämning *", self.proper_name_var, 44, bold=True)

        # --- ADR-klass ---
        tk.Label(main, text="ADR-klass *", font=(_font(), 9, "bold"),
                 fg="#334155", bg="#fafafa").pack(anchor="w", pady=(6, 0))
        self.adr_class_var = tk.StringVar()
        self.adr_combo = ttk.Combobox(main, textvariable=self.adr_class_var,
                                       values=ADR_CLASSES, width=36, state="readonly")
        self.adr_combo.pack(anchor="w", pady=(2, 0))

        # --- Förpackningsgrupp ---
        tk.Label(main, text="Förpackningsgrupp", font=(_font(), 9),
                 fg="#334155", bg="#fafafa").pack(anchor="w", pady=(6, 0))
        self.packing_group_var = tk.StringVar()
        ttk.Combobox(main, textvariable=self.packing_group_var,
                     values=["", "I — Hög fara", "II — Medel fara", "III — Låg fara"],
                     width=22, state="readonly").pack(anchor="w", pady=(2, 0))

        # --- Teknisk benämning ---
        self.technical_name_var = tk.StringVar()
        self._labeled_entry(main, "Teknisk benämning (n.o.s.)", self.technical_name_var, 40)

        # --- Tunnelkod ---
        tk.Label(main, text="Tunnelkod", font=(_font(), 9),
                 fg="#334155", bg="#fafafa").pack(anchor="w", pady=(6, 0))
        self.tunnel_code_var = tk.StringVar()
        ttk.Combobox(main, textvariable=self.tunnel_code_var,
                     values=TUNNEL_CODES, width=10, state="readonly").pack(anchor="w", pady=(2, 0))

        # --- Nettomängd ---
        self.quantity_var = tk.StringVar()
        self._labeled_entry(main, "Nettomängd", self.quantity_var, 22)

        # --- Flampunkt ---
        self.flash_point_var = tk.StringVar()
        self._labeled_entry(main, "Flampunkt (°C)", self.flash_point_var, 12)

        self._sep(main)

        # --- Sidecar ---
        self.save_sidecar_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(main, text="Spara för framtida sändningar",
                        variable=self.save_sidecar_var).pack(anchor="w", pady=(4, 8))

        # --- Buttons ---
        btn_f = tk.Frame(main, bg="#fafafa")
        btn_f.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_f, text="Avbryt", command=self._on_cancel).pack(side="left")
        ttk.Button(btn_f, text="Bekräfta och boka", command=self._on_ok).pack(side="right")

    def _labeled_entry(self, parent, label: str, var: tk.StringVar, width: int, bold: bool = False):
        is_req = "*" in label
        font = (_font(), 9, "bold") if (is_req or bold) else (_font(), 9)
        tk.Label(parent, text=label, font=font, fg="#334155", bg="#fafafa").pack(anchor="w", pady=(6, 0))
        ttk.Entry(parent, textvariable=var, width=width).pack(anchor="w", pady=(2, 0))

    def _sep(self, parent):
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(10, 6))

    def _on_un_changed(self, *_args):
        if self._lookup_after_id:
            self.after_cancel(self._lookup_after_id)
        un = self.un_number_var.get().strip()
        if len(un) >= 4 and un.isdigit():
            self.un_status_label.config(text="  Söker...", fg="#3b82f6")
            self._lookup_after_id = self.after(300, lambda: self._do_lookup(un))
        else:
            self.un_status_label.config(text="  4 siffror → auto-ifyllning", fg="#94a3b8")

    def _do_lookup(self, un: str):
        def _bg():
            result = _lookup_un_number(un)
            if not self.winfo_exists():
                return
            self.after(0, lambda: self._apply_lookup(result, un))
        threading.Thread(target=_bg, daemon=True).start()

    def _apply_lookup(self, result: Optional[dict], un: str):
        if not self.winfo_exists():
            return
        if self.un_number_var.get().strip() != un:
            return
        if result:
            desc = result.get("description", "")
            cls = result.get("class", "")
            if desc and not self.proper_name_var.get().strip():
                self.proper_name_var.set(desc.upper())
            if cls:
                idx = _ADR_CLASS_INDEX.get(cls)
                if idx is not None and not _adr_class_value(self.adr_class_var.get()):
                    self.adr_combo.current(idx)
            self.un_status_label.config(text=f"  UN {un}: {desc}", fg="#16a34a")
        else:
            self.un_status_label.config(text=f"  UN {un} ej funnen — fyll i manuellt", fg="#d97706")

    def _on_ok(self):
        un = self.un_number_var.get().strip()
        if not un:
            messagebox.showwarning("UN-nummer krävs", "Ange UN-nummer.", parent=self)
            return
        proper = self.proper_name_var.get().strip()
        if not proper:
            messagebox.showwarning("Benämning krävs", "Ange officiell transportbenämning.", parent=self)
            return
        adr = _adr_class_value(self.adr_class_var.get())
        if not adr:
            messagebox.showwarning("ADR-klass krävs", "Välj ADR-klass.", parent=self)
            return

        pg_raw = self.packing_group_var.get().strip()
        pg = pg_raw.split("—")[0].strip().upper() if pg_raw else ""
        if pg and pg not in ("I", "II", "III"):
            pg = ""

        self._result = DangerousGoodsInfo(
            un_number=un,
            adr_class=adr,
            packing_group=pg,
            proper_shipping_name=proper,
            technical_name=self.technical_name_var.get().strip(),
            flash_point=self.flash_point_var.get().strip(),
            tunnel_code=self.tunnel_code_var.get().strip(),
            quantity=self.quantity_var.get().strip(),
        )

        if self.save_sidecar_var.get() and self.xml_filepath.exists():
            self._save_sidecar()

        if self.on_confirm:
            self.on_confirm(self._result, self.save_sidecar_var.get())
        self.destroy()

    def _save_sidecar(self):
        try:
            stem = self.xml_filepath.stem
            dg_path = self.xml_filepath.parent / f"{stem}_dg.json"
            data = {
                "unNumber": self._result.un_number,
                "adrClass": self._result.adr_class,
                "packingGroup": self._result.packing_group,
                "properShippingName": self._result.proper_shipping_name,
                "technicalName": self._result.technical_name,
                "flashPoint": self._result.flash_point,
                "tunnelCode": self._result.tunnel_code,
                "quantity": self._result.quantity,
            }
            dg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"Sparade DG-sidecar: {dg_path.name}")
        except Exception as e:
            logger.warning(f"Kunde inte spara sidecar: {e}")

    def _on_cancel(self):
        self._result = None
        if self.on_confirm:
            self.on_confirm(None, False)
        self.destroy()

    def get_result(self) -> Optional[DangerousGoodsInfo]:
        return self._result
