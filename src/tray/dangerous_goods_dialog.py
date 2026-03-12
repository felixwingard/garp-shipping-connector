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
    "1 — Explosiva ämnen",
    "2 — Gaser",
    "3 — Brandfarliga vätskor",
    "4.1 — Brandfarliga fasta ämnen",
    "4.2 — Självantändande ämnen",
    "4.3 — Ämnen: brandfarlig gas vid vatten",
    "5.1 — Oxiderande ämnen",
    "5.2 — Organiska peroxider",
    "6.1 — Giftiga ämnen",
    "6.2 — Smittförande ämnen",
    "7 — Radioaktiva ämnen",
    "8 — Frätande ämnen",
    "9 — Övriga farliga ämnen",
]

_ADR_CLASS_INDEX = {}
for i, item in enumerate(ADR_CLASSES):
    code = item.split("—")[0].strip()
    if code:
        _ADR_CLASS_INDEX[code] = i


def _font():
    return "Segoe UI" if platform.system() == "Windows" else "Helvetica Neue"


def _adr_class_value(display: str) -> str:
    return display.split("—")[0].strip() if display else ""


def _lookup_un_number(un: str) -> Optional[dict]:
    """Slår upp UN-nummer online. Returnerar {'description', 'class', 'number'} eller None."""
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
        self.minsize(480, 400)
        self.configure(bg="#fafafa")

        self._build_ui()
        self._center()

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.focus_force()
        self.grab_set()

    def _center(self):
        self.update_idletasks()
        w = max(self.winfo_reqwidth(), 520)
        h = max(self.winfo_reqheight(), 620)
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        canvas = tk.Canvas(self, bg="#fafafa", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        main = tk.Frame(canvas, bg="#fafafa", padx=20, pady=16)
        canvas_window = canvas.create_window((0, 0), window=main, anchor="nw")

        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)

        def _on_mousewheel(event):
            if platform.system() == "Darwin":
                canvas.yview_scroll(int(-1 * event.delta), "units")
            else:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        main.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.bind("<MouseWheel>", _on_mousewheel)

        # --- Header ---
        hdr = tk.Frame(main, bg="#fef2f2", bd=1, relief="solid")
        hdr.pack(fill="x", pady=(0, 12))
        hdr_inner = tk.Frame(hdr, bg="#fef2f2", padx=12, pady=10)
        hdr_inner.pack(fill="x")
        tk.Label(
            hdr_inner,
            text=f"Order {self.order_no} — farligt gods",
            font=(_font(), 11, "bold"),
            fg="#991b1b",
            bg="#fef2f2",
        ).pack(anchor="w")
        tk.Label(
            hdr_inner,
            text="Fyll i uppgifterna nedan. De används för bokning och ADR-godsdeklaration.",
            font=(_font(), 9),
            fg="#7f1d1d",
            bg="#fef2f2",
            wraplength=440,
        ).pack(anchor="w", pady=(4, 0))

        # --- Form ---
        card = tk.LabelFrame(main, text="  ADR-uppgifter  ", font=(_font(), 9, "bold"),
                             bg="white", fg="#334155", padx=14, pady=10)
        card.pack(fill="x", pady=(0, 12))

        # UN-nummer med auto-lookup
        f_un = tk.Frame(card, bg="white")
        f_un.pack(fill="x", pady=(0, 6))
        tk.Label(f_un, text="UN-nummer *", font=(_font(), 9, "bold"),
                 fg="#334155", bg="white").pack(anchor="w")
        un_row = tk.Frame(f_un, bg="white")
        un_row.pack(fill="x", pady=(2, 0))
        self.un_number_var = tk.StringVar()
        self.un_number_var.trace_add("write", self._on_un_changed)
        ttk.Entry(un_row, textvariable=self.un_number_var, width=10).pack(side="left")
        self.un_status_label = tk.Label(un_row, text="", font=(_font(), 8),
                                        fg="#94a3b8", bg="white")
        self.un_status_label.pack(side="left", padx=(8, 0))
        tk.Label(f_un, text="Skriv 4 siffror — benämning och klass fylls i automatiskt",
                 font=(_font(), 8), fg="#94a3b8", bg="white").pack(anchor="w")

        self.proper_name_var = tk.StringVar()
        self._field(card, "Officiell transportbenämning *", self.proper_name_var, 44,
                    "t.ex. FLAMMABLE LIQUID, N.O.S.")

        # ADR-klass dropdown
        f_adr = tk.Frame(card, bg="white")
        f_adr.pack(fill="x", pady=(0, 6))
        tk.Label(f_adr, text="ADR-klass *", font=(_font(), 9, "bold"),
                 fg="#334155", bg="white").pack(anchor="w")
        self.adr_class_var = tk.StringVar()
        self.adr_combo = ttk.Combobox(
            f_adr, textvariable=self.adr_class_var,
            values=ADR_CLASSES, width=42, state="readonly",
        )
        self.adr_combo.pack(anchor="w", pady=(2, 0))

        # Förpackningsgrupp dropdown
        f_pg = tk.Frame(card, bg="white")
        f_pg.pack(fill="x", pady=(0, 6))
        tk.Label(f_pg, text="Förpackningsgrupp", font=(_font(), 9),
                 fg="#334155", bg="white").pack(anchor="w")
        self.packing_group_var = tk.StringVar()
        ttk.Combobox(
            f_pg, textvariable=self.packing_group_var,
            values=["", "I — Hög fara", "II — Medel fara", "III — Låg fara"],
            width=26, state="readonly",
        ).pack(anchor="w", pady=(2, 0))

        self.technical_name_var = tk.StringVar()
        self._field(card, "Teknisk benämning (n.o.s.)", self.technical_name_var, 40, "t.ex. Etanol")

        self.quantity_var = tk.StringVar()
        self._field(card, "Nettomängd", self.quantity_var, 22, "t.ex. 200 liter")

        self.flash_point_var = tk.StringVar()
        self._field(card, "Flampunkt (°C)", self.flash_point_var, 16, "t.ex. 23")

        f_tc = tk.Frame(card, bg="white")
        f_tc.pack(fill="x", pady=(0, 6))
        tk.Label(f_tc, text="Tunnelkod", font=(_font(), 9),
                 fg="#334155", bg="white").pack(anchor="w")
        self.tunnel_code_var = tk.StringVar()
        ttk.Combobox(
            f_tc, textvariable=self.tunnel_code_var,
            values=["", "(B)", "(B/D)", "(B/E)", "(C)", "(C/D)", "(C/E)", "(D)", "(D/E)", "(E)", "(-)"],
            width=12, state="readonly",
        ).pack(anchor="w", pady=(2, 0))
        tk.Label(f_tc, text="ADR-tunnelbegränsning — se kolumn 15 i tabell A",
                 font=(_font(), 8), fg="#94a3b8", bg="white").pack(anchor="w")

        # --- Sidecar ---
        self.save_sidecar_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            main, text="Spara för framtida sändningar med samma order",
            variable=self.save_sidecar_var,
        ).pack(anchor="w", pady=(4, 12))

        # --- Buttons ---
        btn_f = tk.Frame(main, bg="#fafafa")
        btn_f.pack(fill="x", pady=(0, 8))

        ttk.Button(btn_f, text="Avbryt", command=self._on_cancel).pack(side="left", padx=(0, 12))

        style = ttk.Style()
        style.configure("Accent.TButton", font=(_font(), 10, "bold"))
        ok_btn = ttk.Button(btn_f, text="  Bekräfta och boka  ", command=self._on_ok,
                            style="Accent.TButton")
        ok_btn.pack(side="right")

    def _field(self, parent, label: str, var: tk.StringVar, width: int = 30, hint: str = ""):
        f = tk.Frame(parent, bg="white")
        f.pack(fill="x", pady=(0, 6))
        is_required = "*" in label
        tk.Label(
            f, text=label,
            font=(_font(), 9, "bold") if is_required else (_font(), 9),
            fg="#334155", bg="white",
        ).pack(anchor="w")
        ttk.Entry(f, textvariable=var, width=width).pack(anchor="w", pady=(2, 0))
        if hint:
            tk.Label(f, text=hint, font=(_font(), 8), fg="#94a3b8", bg="white").pack(anchor="w")

    def _on_un_changed(self, *_args):
        if self._lookup_after_id:
            self.after_cancel(self._lookup_after_id)
        un = self.un_number_var.get().strip()
        if len(un) >= 4 and un.isdigit():
            self.un_status_label.config(text="Söker...", fg="#3b82f6")
            self._lookup_after_id = self.after(300, lambda: self._do_lookup(un))
        else:
            self.un_status_label.config(text="", fg="#94a3b8")

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

            self.un_status_label.config(text=f"UN {un}: {desc}", fg="#16a34a")
        else:
            self.un_status_label.config(text=f"UN {un} hittades inte — fyll i manuellt", fg="#d97706")

    def _on_ok(self):
        un = self.un_number_var.get().strip()
        if not un:
            messagebox.showwarning("UN-nummer krävs", "Ange UN-nummer.", parent=self)
            return

        proper = self.proper_name_var.get().strip()
        if not proper:
            messagebox.showwarning("Transportbenämning krävs",
                                   "Ange officiell transportbenämning.", parent=self)
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
