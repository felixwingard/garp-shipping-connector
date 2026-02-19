"""Statusfönster — visar senaste sändningar.

tkinter Toplevel-fönster med:
- Tabell med senaste 50 sändningar
- Kolumner: Tid | Order | Tracking | Status
- Auto-uppdatering via refresh()
- Knapp: Öppna loggmapp
"""

import logging
import platform
import subprocess
import tkinter as tk
from tkinter import ttk
from typing import Optional

logger = logging.getLogger(__name__)


class StatusWindow(tk.Toplevel):
    """Statusfönster med historik över bearbetade sändningar."""

    def __init__(self, parent: tk.Tk, history: list[dict]):
        super().__init__(parent)

        self.title("GARP Shipping Connector — Status")
        self.geometry("650x400")
        self.minsize(500, 300)

        # Centrera
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (650 // 2)
        y = (self.winfo_screenheight() // 2) - (400 // 2)
        self.geometry(f"+{x}+{y}")

        self._build_ui()
        self.refresh(history)

        self.focus_force()

    def _build_ui(self):
        """Bygger UI."""
        # Rubrik
        header = ttk.Frame(self)
        header.pack(fill="x", padx=10, pady=(10, 5))

        ttk.Label(
            header,
            text="Senaste sändningar",
            font=("", 12, "bold"),
        ).pack(side="left")

        self._status_label = ttk.Label(header, text="", foreground="gray")
        self._status_label.pack(side="right")

        # Tabell
        columns = ("time", "order", "tracking", "carrier", "status")
        self.tree = ttk.Treeview(
            self,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        self.tree.heading("time", text="Tid")
        self.tree.heading("order", text="Order")
        self.tree.heading("tracking", text="Spårningsnummer")
        self.tree.heading("carrier", text="Transportör")
        self.tree.heading("status", text="Status")

        self.tree.column("time", width=70, minwidth=60)
        self.tree.column("order", width=140, minwidth=100)
        self.tree.column("tracking", width=200, minwidth=150)
        self.tree.column("carrier", width=80, minwidth=60)
        self.tree.column("status", width=80, minwidth=60)

        # Scrollbar
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(fill="both", expand=True, padx=(10, 0), pady=5)
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=5)

        # Knappar
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=10, pady=(5, 10))

        ttk.Button(
            btn_frame, text="Öppna loggmapp",
            command=self._open_log_folder,
        ).pack(side="left")

        ttk.Button(
            btn_frame, text="Stäng",
            command=self.destroy,
        ).pack(side="right")

        # Tags för statusfärgning
        self.tree.tag_configure("ok", foreground="#27ae60")
        self.tree.tag_configure("error", foreground="#e74c3c")
        self.tree.tag_configure("info", foreground="#2980b9")

    def refresh(self, history: list[dict]):
        """Uppdaterar tabellen med ny historik."""
        # Rensa
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Fyll på
        for entry in history:
            event = entry.get("event", "")
            time_str = entry.get("time", "")

            if event == "shipment_ok":
                values = (
                    time_str,
                    entry.get("order_no", ""),
                    entry.get("tracking", ""),
                    entry.get("carrier", ""),
                    "OK",
                )
                tag = "ok"
            elif event == "shipment_error":
                values = (
                    time_str,
                    entry.get("order_no", ""),
                    "",
                    "",
                    "FEL",
                )
                tag = "error"
            elif event == "file_done":
                values = (
                    time_str,
                    entry.get("filename", ""),
                    "",
                    "",
                    "Fil klar",
                )
                tag = "info"
            elif event == "file_error":
                values = (
                    time_str,
                    entry.get("filename", ""),
                    "",
                    "",
                    "Filfel",
                )
                tag = "error"
            else:
                values = (time_str, str(entry), "", "", "")
                tag = "info"

            self.tree.insert("", "end", values=values, tags=(tag,))

        # Statusrad
        ok_count = sum(1 for e in history if e.get("event") == "shipment_ok")
        err_count = sum(1 for e in history if e.get("event") == "shipment_error")
        self._status_label.config(
            text=f"Totalt: {len(history)} | OK: {ok_count} | Fel: {err_count}"
        )

    def _open_log_folder(self):
        """Öppnar loggmappen i filhanteraren."""
        try:
            # Hitta loggmapp från TrayApp
            app = self.master
            log_dir = getattr(app, '_log_dir', None)

            if not log_dir:
                # Fallback: leta i config
                import sys
                from pathlib import Path
                if getattr(sys, 'frozen', False):
                    base = Path(sys.executable).parent
                else:
                    base = Path(__file__).parent.parent.parent
                log_dir = base / "logs"

            log_dir_str = str(log_dir)

            if platform.system() == "Windows":
                subprocess.Popen(["explorer", log_dir_str])
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", log_dir_str])
            else:
                subprocess.Popen(["xdg-open", log_dir_str])

        except Exception as e:
            logger.error(f"Kunde inte öppna loggmapp: {e}")
