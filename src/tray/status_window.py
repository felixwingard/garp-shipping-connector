"""Statusfönster — clean UI för sändningshistorik."""

import logging
import platform
import subprocess
import tkinter as tk
from tkinter import ttk
from typing import Optional

logger = logging.getLogger(__name__)


def _font():
    import platform
    return "Segoe UI" if platform.system() == "Windows" else "Helvetica Neue"


class StatusWindow(tk.Toplevel):
    """Statusfönster — senaste sändningar."""

    def __init__(self, parent: tk.Tk, history: list[dict], log_dir=None):
        super().__init__(parent)
        self._log_dir = log_dir

        self.title("Status")
        self.geometry("600x420")
        self.minsize(480, 320)
        self.configure(bg="#fafafa")

        self._center()
        self._build_ui()
        self.refresh(history)
        self.focus_force()

    def _center(self):
        self.update_idletasks()
        w, h = 600, 420
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        PAD = 16

        main = tk.Frame(self, bg="#fafafa", padx=PAD, pady=PAD)
        main.pack(fill="both", expand=True)

        # Header
        header = tk.Frame(main, bg="#fafafa")
        header.pack(fill="x", pady=(0, 12))

        tk.Label(
            header,
            text="Senaste sändningar",
            font=(_font(), 12, "bold"),
            fg="#1e293b",
            bg="#fafafa",
        ).pack(side="left")

        self._status_label = tk.Label(
            header,
            text="",
            font=(_font(), 9),
            fg="#64748b",
            bg="#fafafa",
        )
        self._status_label.pack(side="right")

        # Tabell — vit card
        card = tk.Frame(main, bg="white", highlightbackground="#e5e7eb", highlightthickness=1)
        card.pack(fill="both", expand=True)

        # Treeview
        columns = ("time", "order", "tracking", "carrier", "price", "status")
        self.tree = ttk.Treeview(
            card,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=12,
        )
        self.tree.heading("time", text="Tid")
        self.tree.heading("order", text="Order")
        self.tree.heading("tracking", text="Spårningsnr")
        self.tree.heading("carrier", text="Transportör")
        self.tree.heading("price", text="Pris")
        self.tree.heading("status", text="Status")

        self.tree.column("time", width=65, minwidth=50)
        self.tree.column("order", width=130, minwidth=90)
        self.tree.column("tracking", width=180, minwidth=120)
        self.tree.column("carrier", width=75, minwidth=60)
        self.tree.column("price", width=70, minwidth=50)
        self.tree.column("status", width=70, minwidth=50)

        scrollbar = ttk.Scrollbar(card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        scrollbar.pack(side="right", fill="y", padx=(0, 1), pady=1)

        self.tree.tag_configure("ok", foreground="#16a34a")
        self.tree.tag_configure("error", foreground="#dc2626")
        self.tree.tag_configure("info", foreground="#64748b")

        # Knappar
        btn_f = tk.Frame(main, bg="#fafafa")
        btn_f.pack(fill="x", pady=(12, 0))

        ttk.Button(btn_f, text="Öppna loggmapp", command=self._open_log_folder).pack(side="left")
        ttk.Button(btn_f, text="Kopiera fel till urklipp", command=self._copy_errors_to_clipboard).pack(side="left", padx=(12, 0))
        ttk.Button(btn_f, text="Stäng", command=self.destroy).pack(side="right")

    def refresh(self, history: list[dict]):
        for item in self.tree.get_children():
            self.tree.delete(item)

        for entry in history:
            event = entry.get("event", "")
            time_str = entry.get("time", "")

            if event == "shipment_ok":
                values = (
                    time_str,
                    entry.get("order_no", ""),
                    entry.get("tracking", ""),
                    entry.get("carrier", ""),
                    entry.get("estimated_price", ""),
                    "OK",
                )
                tag = "ok"
            elif event == "shipment_error":
                values = (time_str, entry.get("order_no", ""), "", "", "", "Fel")
                tag = "error"
            elif event == "file_done":
                values = (time_str, entry.get("filename", ""), "", "", "", "Klar")
                tag = "info"
            elif event == "file_error":
                values = (time_str, entry.get("filename", ""), "", "", "", "Fel")
                tag = "error"
            else:
                values = (time_str, str(entry), "", "", "", "")
                tag = "info"

            self.tree.insert("", "end", values=values, tags=(tag,))

        ok_count = sum(1 for e in history if e.get("event") == "shipment_ok")
        err_count = sum(1 for e in history if e.get("event") == "shipment_error")
        self._status_label.config(text=f"{len(history)} sändningar  ·  {ok_count} OK  ·  {err_count} fel")

    def _copy_errors_to_clipboard(self):
        """Kopierar senaste felen från loggfil till urklipp — för buggrapporter."""
        try:
            from pathlib import Path
            log_dir = self._log_dir
            if not log_dir:
                log_dir = Path("C:/GARP/Logs")
            err_log = Path(log_dir) / "garp_shipping_errors.log"
            if err_log.exists():
                text = err_log.read_text(encoding="utf-8", errors="replace")
                lines = text.strip().split("\n")
                clip = "\n".join(lines[-80:]) if len(lines) > 80 else text
                self.clipboard_clear()
                self.clipboard_append(clip)
                from tkinter import messagebox
                messagebox.showinfo("Kopierat", "Senaste felen kopierade till urklipp.\nKlistra in i e-post till support.", parent=self)
            else:
                from tkinter import messagebox
                messagebox.showinfo("Inga fel", "Ingen felogg finns ännu.", parent=self)
        except Exception as e:
            logger.error(f"Kunde inte kopiera fel: {e}")

    def _open_log_folder(self):
        try:
            log_dir = self._log_dir
            if not log_dir:
                import sys
                from pathlib import Path
                if getattr(sys, "frozen", False):
                    log_dir = Path(sys.executable).parent / "logs"
                else:
                    log_dir = Path(__file__).parent.parent.parent / "logs"

            log_dir_str = str(log_dir)
            if platform.system() == "Windows":
                subprocess.Popen(["explorer", log_dir_str])
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", log_dir_str])
            else:
                subprocess.Popen(["xdg-open", log_dir_str])
        except Exception as e:
            logger.error(f"Kunde inte öppna loggmapp: {e}")
