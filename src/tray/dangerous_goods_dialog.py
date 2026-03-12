"""Dialog för att ange farligt gods (ADR) — används när sidecar-fil saknas."""

import json
import logging
import platform
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Optional, Callable

from ..parsers.models import DangerousGoodsInfo

logger = logging.getLogger(__name__)

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


def _font():
    return "Segoe UI" if platform.system() == "Windows" else "Helvetica Neue"


def _adr_class_value(display: str) -> str:
    return display.split("—")[0].strip() if display else ""


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
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        w = max(w, 500)
        h = max(h, 580)
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        # Scrollable canvas for Windows DPI scaling
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

        self.un_number_var = tk.StringVar()
        self._field(card, "UN-nummer *", self.un_number_var, 16, "t.ex. 1987")

        self.proper_name_var = tk.StringVar()
        self._field(card, "Officiell transportbenämning *", self.proper_name_var, 40,
                    "t.ex. ALCOHOLS, N.O.S.")

        # ADR-klass dropdown
        f_adr = tk.Frame(card, bg="white")
        f_adr.pack(fill="x", pady=(0, 6))
        tk.Label(f_adr, text="ADR-klass *", font=(_font(), 9, "bold"),
                 fg="#334155", bg="white").pack(anchor="w")
        self.adr_class_var = tk.StringVar()
        ttk.Combobox(
            f_adr, textvariable=self.adr_class_var,
            values=ADR_CLASSES, width=42, state="readonly",
        ).pack(anchor="w", pady=(2, 0))

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

        # --- Sidecar ---
        self.save_sidecar_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            main, text="Spara för framtida sändningar med samma order",
            variable=self.save_sidecar_var,
        ).pack(anchor="w", pady=(4, 12))

        # --- Buttons ---
        btn_f = tk.Frame(main, bg="#fafafa")
        btn_f.pack(fill="x", pady=(0, 8))

        cancel_btn = ttk.Button(btn_f, text="Avbryt", command=self._on_cancel)
        cancel_btn.pack(side="left", padx=(0, 12))

        ok_btn = ttk.Button(btn_f, text="  Bekräfta och boka  ", command=self._on_ok)
        ok_btn.pack(side="right")

        # Gör OK-knappen grön/framträdande via style
        style = ttk.Style()
        style.configure("Accent.TButton", font=(_font(), 10, "bold"))
        ok_btn.configure(style="Accent.TButton")

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

    def _on_ok(self):
        un = self.un_number_var.get().strip()
        if not un:
            messagebox.showwarning("UN-nummer krävs", "Ange UN-nummer för farligt gods.", parent=self)
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
