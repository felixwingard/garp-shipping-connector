"""Inställningsfönster — skrivarval + mappval.

tkinter Toplevel-fönster med:
- Etikettskrivare: Dropdown med alla Windows-skrivare
- Dokumentskrivare: Dropdown med alla Windows-skrivare
- XML-mapp (watch_dir): Folder picker
- Done-mapp: Folder picker
- Error-mapp: Folder picker
- Spara-knapp → skriver till config.yaml
"""

import logging
import platform
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class SettingsWindow(tk.Toplevel):
    """Inställningsfönster för GARP Shipping Connector."""

    def __init__(self, parent: tk.Tk, config: dict,
                 on_save: Optional[Callable] = None):
        super().__init__(parent)
        self.config = config
        self.on_save = on_save

        self.title("GARP Shipping Connector — Inställningar")
        self.geometry("550x500")
        self.resizable(False, False)

        # Centrera fönstret
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (550 // 2)
        y = (self.winfo_screenheight() // 2) - (500 // 2)
        self.geometry(f"+{x}+{y}")

        self._build_ui()
        self._load_current_values()

        # Fokus
        self.focus_force()
        self.grab_set()

    def _build_ui(self):
        """Bygger hela fönstrets UI."""
        # Padding
        pad = {"padx": 10, "pady": 5}

        # === Skrivare ===
        printer_frame = ttk.LabelFrame(self, text="Skrivare", padding=10)
        printer_frame.pack(fill="x", **pad)

        # Hämta skrivarlista
        printers = self._get_printers()

        # Etikettskrivare
        ttk.Label(printer_frame, text="Etikettskrivare (Zebra):").grid(
            row=0, column=0, sticky="w", pady=2
        )
        self.label_printer_var = tk.StringVar()
        self.label_printer_combo = ttk.Combobox(
            printer_frame,
            textvariable=self.label_printer_var,
            values=printers,
            width=40,
            state="readonly" if printers else "normal",
        )
        self.label_printer_combo.grid(row=0, column=1, sticky="ew", pady=2, padx=(5, 0))

        # Etikettformat
        ttk.Label(printer_frame, text="Etikettformat:").grid(
            row=1, column=0, sticky="w", pady=2
        )
        self.label_format_var = tk.StringVar(value="pdf")
        format_frame = ttk.Frame(printer_frame)
        format_frame.grid(row=1, column=1, sticky="w", pady=2, padx=(5, 0))
        ttk.Radiobutton(format_frame, text="PDF", variable=self.label_format_var, value="pdf").pack(side="left")
        ttk.Radiobutton(format_frame, text="ZPL", variable=self.label_format_var, value="zpl").pack(side="left", padx=(10, 0))

        # Dokumentskrivare
        ttk.Label(printer_frame, text="Dokumentskrivare (A4):").grid(
            row=2, column=0, sticky="w", pady=2
        )
        self.doc_printer_var = tk.StringVar()
        self.doc_printer_combo = ttk.Combobox(
            printer_frame,
            textvariable=self.doc_printer_var,
            values=["(ingen)"] + printers,
            width=40,
            state="readonly" if printers else "normal",
        )
        self.doc_printer_combo.grid(row=2, column=1, sticky="ew", pady=2, padx=(5, 0))

        printer_frame.columnconfigure(1, weight=1)

        # === Mappar ===
        folder_frame = ttk.LabelFrame(self, text="Mappar", padding=10)
        folder_frame.pack(fill="x", **pad)

        self.watch_dir_var = tk.StringVar()
        self.done_dir_var = tk.StringVar()
        self.error_dir_var = tk.StringVar()

        folders = [
            ("XML-mapp (inkommande):", self.watch_dir_var),
            ("Done-mapp (klara):", self.done_dir_var),
            ("Error-mapp (fel):", self.error_dir_var),
        ]

        for i, (label_text, var) in enumerate(folders):
            ttk.Label(folder_frame, text=label_text).grid(
                row=i, column=0, sticky="w", pady=2
            )
            entry = ttk.Entry(folder_frame, textvariable=var, width=35)
            entry.grid(row=i, column=1, sticky="ew", pady=2, padx=(5, 5))
            btn = ttk.Button(
                folder_frame, text="Bläddra...",
                command=lambda v=var: self._browse_folder(v),
                width=10,
            )
            btn.grid(row=i, column=2, pady=2)

        folder_frame.columnconfigure(1, weight=1)

        # === DHL-status ===
        dhl_frame = ttk.LabelFrame(self, text="DHL API", padding=10)
        dhl_frame.pack(fill="x", **pad)

        dhl_config = self.config.get("dhl", {})
        env_label = "Sandbox" if "test-api" in dhl_config.get("base_url", "") else "Produktion"
        customer = self.config.get("sender", {}).get("customer_number_dhl", "")

        ttk.Label(dhl_frame, text=f"Miljö: {env_label}").pack(anchor="w")
        ttk.Label(dhl_frame, text=f"Kundnummer: {customer}").pack(anchor="w")
        ttk.Label(
            dhl_frame,
            text="(Ändra API-inställningar i config.yaml)",
            foreground="gray",
        ).pack(anchor="w")

        # === Knappar ===
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", **pad, pady=(10, 10))

        ttk.Button(btn_frame, text="Spara", command=self._save).pack(
            side="right", padx=5
        )
        ttk.Button(btn_frame, text="Avbryt", command=self.destroy).pack(
            side="right"
        )

    def _load_current_values(self):
        """Laddar nuvarande config-värden till UI."""
        # Skrivare (stöd nytt + gammalt format)
        printers_cfg = self.config.get("printers", self.config.get("printer", {}))
        label_printer = (
            printers_cfg.get("label_printer_name")
            or printers_cfg.get("windows_printer_name", "")
        )
        label_format = (
            printers_cfg.get("label_format")
            or printers_cfg.get("type", "pdf")
        )
        doc_printer = printers_cfg.get("document_printer_name", "")

        self.label_printer_var.set(label_printer)
        self.label_format_var.set(label_format)
        self.doc_printer_var.set(doc_printer if doc_printer else "(ingen)")

        # Mappar
        paths = self.config.get("paths", {})
        self.watch_dir_var.set(paths.get("watch_dir", ""))
        self.done_dir_var.set(paths.get("done_dir", ""))
        self.error_dir_var.set(paths.get("error_dir", ""))

    def _get_printers(self) -> list:
        """Hämtar Windows-skrivarlista."""
        if platform.system() != "Windows":
            return []

        try:
            from ..printing.printer import list_windows_printers
            return list_windows_printers()
        except Exception as e:
            logger.warning(f"Kunde inte hämta skrivarlista: {e}")
            return []

    def _browse_folder(self, var: tk.StringVar):
        """Öppnar mappväljare."""
        current = var.get()
        folder = filedialog.askdirectory(
            initialdir=current if current else None,
            title="Välj mapp",
        )
        if folder:
            var.set(folder)

    def _save(self):
        """Sparar inställningar till config.yaml."""
        import yaml

        # Uppdatera config-dict
        doc_printer = self.doc_printer_var.get()
        if doc_printer == "(ingen)":
            doc_printer = ""

        # Ny printer-sektion
        self.config["printers"] = {
            "label_printer_name": self.label_printer_var.get(),
            "label_format": self.label_format_var.get(),
            "document_printer_name": doc_printer,
            "document_format": "pdf",
        }

        # Ta bort gamla printer-nyckeln om den finns
        self.config.pop("printer", None)

        # Mappar
        self.config["paths"]["watch_dir"] = self.watch_dir_var.get()
        self.config["paths"]["done_dir"] = self.done_dir_var.get()
        self.config["paths"]["error_dir"] = self.error_dir_var.get()

        # Skriv till config.yaml
        try:
            # Hitta config-sökväg
            import sys
            if getattr(sys, 'frozen', False):
                config_dir = Path(sys.executable).parent / "config"
            else:
                config_dir = Path(__file__).parent.parent.parent / "config"

            config_path = config_dir / "config.yaml"

            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    self.config, f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )

            logger.info(f"Inställningar sparade till {config_path}")

            # Callback
            if self.on_save:
                self.on_save(self.config)

            messagebox.showinfo(
                "Sparat",
                "Inställningar sparade!\n\n"
                "Skrivarändringarna gäller direkt.\n"
                "Mappändringar kräver omstart.",
                parent=self,
            )
            self.destroy()

        except Exception as e:
            logger.error(f"Kunde inte spara config: {e}")
            messagebox.showerror(
                "Fel",
                f"Kunde inte spara inställningar:\n{e}",
                parent=self,
            )
