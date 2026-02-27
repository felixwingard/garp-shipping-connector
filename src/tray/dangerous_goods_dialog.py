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

PAD = 16


def _font():
    return "Segoe UI" if platform.system() == "Windows" else "Helvetica Neue"


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

        self.title(f"Ange farligt gods — order {order_no}")
        self.geometry("420x340")
        self.resizable(False, False)
        self.configure(bg="#fafafa")

        self._center()
        self._build_ui()

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.focus_force()
        self.grab_set()

    def _center(self):
        self.update_idletasks()
        w, h = 420, 340
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        main = tk.Frame(self, bg="#fafafa", padx=PAD, pady=PAD)
        main.pack(fill="both", expand=True)

        tk.Label(
            main,
            text=f"Order {self.order_no} har farligt gods men saknar deklarationsdata.",
            font=(_font(), 9),
            fg="#64748b",
            bg="#fafafa",
            wraplength=380,
        ).pack(anchor="w", pady=(0, 12))

        inner = tk.Frame(main, bg="white", highlightbackground="#e5e7eb", highlightthickness=1)
        inner.pack(fill="x", pady=(0, 12))

        def row(parent, label: str, widget):
            f = tk.Frame(parent, bg="white")
            f.pack(fill="x", pady=6, padx=PAD)
            tk.Label(f, text=label, font=(_font(), 9), fg="#64748b", bg="white", width=14, anchor="w").pack(
                side="left", padx=(0, 12)
            )
            widget.pack(side="left", fill="x", expand=True)

        self.un_number_var = tk.StringVar()
        row(inner, "UN-nummer *", ttk.Entry(inner, textvariable=self.un_number_var, width=24))

        self.adr_class_var = tk.StringVar()
        row(inner, "ADR-klass (1–9)", ttk.Entry(inner, textvariable=self.adr_class_var, width=24))

        self.packing_group_var = tk.StringVar()
        packing_combo = ttk.Combobox(
            inner,
            textvariable=self.packing_group_var,
            values=["", "I", "II", "III"],
            width=22,
            state="readonly",
        )
        row(inner, "Packningsgrupp", packing_combo)

        self.technical_name_var = tk.StringVar()
        row(inner, "Teknisk beteckning", ttk.Entry(inner, textvariable=self.technical_name_var, width=24))

        self.flash_point_var = tk.StringVar()
        row(inner, "Flashpoint", ttk.Entry(inner, textvariable=self.flash_point_var, width=24))

        self.save_sidecar_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            main,
            text="Spara till sidecar-fil för framtida användning",
            variable=self.save_sidecar_var,
        ).pack(anchor="w", pady=(0, 12))

        btn_f = tk.Frame(main, bg="#fafafa")
        btn_f.pack(fill="x")
        ttk.Button(btn_f, text="Avbryt", command=self._on_cancel).pack(side="left", padx=(0, 8))
        ttk.Button(btn_f, text="Fortsätt", command=self._on_ok).pack(side="right")

    def _on_ok(self):
        un = self.un_number_var.get().strip()
        if not un:
            messagebox.showwarning(
                "UN-nummer krävs",
                "Ange UN-nummer för farligt gods.",
                parent=self,
            )
            return

        adr = self.adr_class_var.get().strip()
        pg = self.packing_group_var.get().strip().upper()
        if pg and pg not in ("I", "II", "III"):
            pg = ""
        tech = self.technical_name_var.get().strip()
        flash = self.flash_point_var.get().strip()

        self._result = DangerousGoodsInfo(
            un_number=un,
            adr_class=adr,
            packing_group=pg,
            technical_name=tech,
            flash_point=flash,
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
                "technicalName": self._result.technical_name,
                "flashPoint": self._result.flash_point,
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
