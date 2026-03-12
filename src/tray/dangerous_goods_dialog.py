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

PAD = 20

ADR_CLASSES = [
    "",
    "1 — Explosiva ämnen",
    "2 — Gaser",
    "3 — Brandfarliga vätskor",
    "4.1 — Brandfarliga fasta ämnen",
    "4.2 — Självantändande ämnen",
    "4.3 — Ämnen som avger brandfarlig gas vid kontakt med vatten",
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
    """Extracts the class code from display string like '3 — Brandfarliga vätskor'."""
    return display.split("—")[0].strip() if display else ""


class DangerousGoodsDialog(tk.Toplevel):
    """Dialog för att ange farligt gods (UN-nummer, ADR-klass, etc.).

    Visas när DHL-sändning har DG-addon men saknar sidecar-fil.
    Vid bekräftelse: returnerar DangerousGoodsInfo. Kan spara till sidecar.
    """

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
        self.geometry("520x560")
        self.resizable(False, False)
        self.configure(bg="#fafafa")

        self._center()
        self._build_ui()

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.focus_force()
        self.grab_set()

    def _center(self):
        self.update_idletasks()
        w, h = 520, 560
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        main = tk.Frame(self, bg="#fafafa", padx=PAD, pady=PAD)
        main.pack(fill="both", expand=True)

        # Header
        header = tk.Frame(main, bg="#fef2f2", highlightbackground="#fca5a5", highlightthickness=1)
        header.pack(fill="x", pady=(0, 16))
        tk.Label(
            header,
            text=f"⚠  Order {self.order_no} — farligt gods",
            font=(_font(), 11, "bold"),
            fg="#991b1b",
            bg="#fef2f2",
            padx=12,
            pady=10,
        ).pack(anchor="w")
        tk.Label(
            header,
            text="Fyll i uppgifterna nedan. De används för bokning och ADR-godsdeklaration.",
            font=(_font(), 9),
            fg="#7f1d1d",
            bg="#fef2f2",
            padx=12,
            pady=(0, 10),
        ).pack(anchor="w")

        # Form card
        card = tk.Frame(main, bg="white", highlightbackground="#e5e7eb", highlightthickness=1)
        card.pack(fill="x", pady=(0, 16))
        form = tk.Frame(card, bg="white", padx=16, pady=12)
        form.pack(fill="x")

        # UN-nummer
        self.un_number_var = tk.StringVar()
        self._field(form, "UN-nummer *", self.un_number_var, width=14, placeholder="t.ex. 1987")

        # Officiell transportbenämning
        self.proper_name_var = tk.StringVar()
        self._field(form, "Officiell transportbenämning *", self.proper_name_var, width=36,
                    placeholder="t.ex. ALCOHOLS, N.O.S.")

        # ADR-klass
        self.adr_class_var = tk.StringVar()
        f = tk.Frame(form, bg="white")
        f.pack(fill="x", pady=(0, 8))
        tk.Label(f, text="ADR-klass *", font=(_font(), 9, "bold"), fg="#334155", bg="white").pack(anchor="w")
        adr_combo = ttk.Combobox(
            f,
            textvariable=self.adr_class_var,
            values=ADR_CLASSES,
            width=44,
            state="readonly",
        )
        adr_combo.pack(anchor="w", pady=(2, 0))

        # Packningsgrupp
        self.packing_group_var = tk.StringVar()
        f2 = tk.Frame(form, bg="white")
        f2.pack(fill="x", pady=(0, 8))
        tk.Label(f2, text="Förpackningsgrupp", font=(_font(), 9, "bold"), fg="#334155", bg="white").pack(anchor="w")
        pg_combo = ttk.Combobox(
            f2,
            textvariable=self.packing_group_var,
            values=["", "I — Hög fara", "II — Medel fara", "III — Låg fara"],
            width=24,
            state="readonly",
        )
        pg_combo.pack(anchor="w", pady=(2, 0))

        # Teknisk benämning
        self.technical_name_var = tk.StringVar()
        self._field(form, "Teknisk benämning (n.o.s.)", self.technical_name_var, width=36,
                    placeholder="t.ex. Etanol")

        # Mängd / antal
        self.quantity_var = tk.StringVar()
        self._field(form, "Nettomängd", self.quantity_var, width=20,
                    placeholder="t.ex. 200 liter")

        # Flashpunkt
        self.flash_point_var = tk.StringVar()
        self._field(form, "Flampunkt (°C)", self.flash_point_var, width=14,
                    placeholder="t.ex. 23")

        # Sidecar checkbox
        self.save_sidecar_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            main,
            text="Spara för framtida sändningar med samma order",
            variable=self.save_sidecar_var,
        ).pack(anchor="w", pady=(0, 16))

        # Buttons
        btn_f = tk.Frame(main, bg="#fafafa")
        btn_f.pack(fill="x")

        cancel_btn = tk.Button(
            btn_f,
            text="Avbryt",
            font=(_font(), 10),
            fg="#374151",
            bg="#f3f4f6",
            activebackground="#e5e7eb",
            relief="flat",
            padx=20,
            pady=8,
            cursor="hand2",
            command=self._on_cancel,
        )
        cancel_btn.pack(side="left")

        ok_btn = tk.Button(
            btn_f,
            text="Bekräfta och boka",
            font=(_font(), 10, "bold"),
            fg="white",
            bg="#1d4ed8",
            activebackground="#1e40af",
            relief="flat",
            padx=24,
            pady=8,
            cursor="hand2",
            command=self._on_ok,
        )
        ok_btn.pack(side="right")

    def _field(self, parent, label: str, var: tk.StringVar, width: int = 30, placeholder: str = ""):
        f = tk.Frame(parent, bg="white")
        f.pack(fill="x", pady=(0, 8))
        required = "*" in label
        tk.Label(
            f, text=label, font=(_font(), 9, "bold" if required else ""),
            fg="#334155", bg="white",
        ).pack(anchor="w")
        entry = ttk.Entry(f, textvariable=var, width=width)
        entry.pack(anchor="w", pady=(2, 0))
        if placeholder:
            tk.Label(
                f, text=placeholder, font=(_font(), 8),
                fg="#94a3b8", bg="white",
            ).pack(anchor="w")

    def _on_ok(self):
        un = self.un_number_var.get().strip()
        if not un:
            messagebox.showwarning("UN-nummer krävs", "Ange UN-nummer för farligt gods.", parent=self)
            return

        proper = self.proper_name_var.get().strip()
        if not proper:
            messagebox.showwarning("Transportbenämning krävs",
                                   "Ange officiell transportbenämning (t.ex. ALCOHOLS, N.O.S.).", parent=self)
            return

        adr = _adr_class_value(self.adr_class_var.get())
        if not adr:
            messagebox.showwarning("ADR-klass krävs", "Välj ADR-klass.", parent=self)
            return

        pg_raw = self.packing_group_var.get().strip()
        pg = pg_raw.split("—")[0].strip().upper() if pg_raw else ""
        if pg and pg not in ("I", "II", "III"):
            pg = ""
        tech = self.technical_name_var.get().strip()
        flash = self.flash_point_var.get().strip()
        qty = self.quantity_var.get().strip()

        self._result = DangerousGoodsInfo(
            un_number=un,
            adr_class=adr,
            packing_group=pg,
            proper_shipping_name=proper,
            technical_name=tech,
            flash_point=flash,
            quantity=qty,
        )

        if self.save_sidecar_var.get() and self.xml_filepath.exists():
            self._save_sidecar()

        if self.on_confirm:
            self.on_confirm(self._result, self.save_sidecar_var.get())
        self.destroy()

    def _save_sidecar(self):
        """Sparar DG-data till {xml_stem}_dg.json."""
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
        """Returnerar angivet DangerousGoodsInfo eller None vid avbryt."""
        return self._result
