"""Inställningsfönster — clean UI för skrivare, mappar och Bring."""

import logging
import platform
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Callable, Optional

logger = logging.getLogger(__name__)

PAD = 16
SECTION_PAD = 12

def _font():
    import platform
    return "Segoe UI" if platform.system() == "Windows" else "Helvetica Neue"


class SettingsWindow(tk.Toplevel):
    """Inställningsfönster — minimalistisk layout."""

    def __init__(self, parent: tk.Tk, config: dict, on_save: Optional[Callable] = None):
        super().__init__(parent)
        self.config = config
        self.on_save = on_save

        self.title("Inställningar")
        self.geometry("480x620")
        self.resizable(False, False)
        self.configure(bg="#fafafa")

        self._center()
        self._build_ui()
        self._load_current_values()

        self.focus_force()
        self.grab_set()

    def _center(self):
        self.update_idletasks()
        w, h = 480, 620
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _section(self, parent, title: str):
        """Skapar en sektion med rubrik."""
        frame = tk.Frame(parent, bg="#fafafa")
        frame.pack(fill="x", pady=(0, SECTION_PAD))

        lbl = tk.Label(
            frame,
            text=title,
            font=(_font(), 10, "bold"),
            fg="#334155",
            bg="#fafafa",
        )
        lbl.pack(anchor="w", pady=(0, 8))

        card = tk.Frame(frame, bg="white", relief="flat")
        card.pack(fill="x", padx=0, pady=0)

        # Diskret ram
        inner = tk.Frame(card, bg="white", highlightbackground="#e5e7eb", highlightthickness=1)
        inner.pack(fill="x", padx=1, pady=1)

        return inner

    def _row(self, parent, label: str, widget, browse_btn=None):
        """En rad: etiket + widget."""
        f = tk.Frame(parent, bg="white")
        f.pack(fill="x", pady=6, padx=PAD)

        tk.Label(f, text=label, font=(_font(), 9), fg="#64748b", bg="white", width=18, anchor="w").pack(
            side="left", padx=(0, 12)
        )
        widget.pack(side="left", fill="x", expand=True, padx=(0, 8))
        if browse_btn:
            browse_btn.pack(side="right")

    def _build_ui(self):
        main = tk.Frame(self, bg="#fafafa", padx=PAD, pady=PAD)
        main.pack(fill="both", expand=True)

        # === Skrivare ===
        sec = self._section(main, "Skrivare")
        printers = self._get_printers()

        self.label_printer_var = tk.StringVar()
        self.label_printer_combo = ttk.Combobox(
            sec, textvariable=self.label_printer_var,
            values=printers, width=32,
            state="readonly" if printers else "normal",
        )
        self._row(sec, "Etikettskrivare", self.label_printer_combo)

        self.label_format_var = tk.StringVar(value="pdf")
        fmt_f = tk.Frame(sec, bg="white")
        fmt_f.pack(fill="x", pady=6, padx=PAD)
        tk.Label(fmt_f, text="Format", font=(_font(), 9), fg="#64748b", bg="white", width=18, anchor="w").pack(
            side="left", padx=(0, 12)
        )
        ttk.Radiobutton(fmt_f, text="PDF", variable=self.label_format_var, value="pdf").pack(side="left", padx=(0, 16))
        ttk.Radiobutton(fmt_f, text="ZPL", variable=self.label_format_var, value="zpl").pack(side="left")

        self.doc_printer_var = tk.StringVar()
        self.doc_printer_combo = ttk.Combobox(
            sec, textvariable=self.doc_printer_var,
            values=["(ingen)"] + printers, width=32,
            state="readonly" if printers else "normal",
        )
        self._row(sec, "Dokumentskrivare", self.doc_printer_combo)

        # === Mappar ===
        sec = self._section(main, "Mappar")
        self.watch_dir_var = tk.StringVar()
        self.done_dir_var = tk.StringVar()
        self.error_dir_var = tk.StringVar()

        for label, var in [
            ("Inkommande XML", self.watch_dir_var),
            ("Klara filer", self.done_dir_var),
            ("Fel", self.error_dir_var),
        ]:
            e = ttk.Entry(sec, textvariable=var, width=28)
            btn = ttk.Button(sec, text="…", width=3, command=lambda v=var: self._browse_folder(v))
            self._row(sec, label, e, btn)

        # === Bring Norge ===
        sec = self._section(main, "Bring Norge")
        hint = tk.Label(
            sec,
            text="Reservera bulk-ID via Bring Bulk (tray-menyn). Bulk-ID sparas automatiskt.",
            font=(_font(), 9),
            fg="#64748b",
            bg="white",
        )
        hint.pack(anchor="w", padx=PAD, pady=12)

        # === Knappar ===
        btn_f = tk.Frame(main, bg="#fafafa")
        btn_f.pack(fill="x", pady=(SECTION_PAD, 0))

        ttk.Button(btn_f, text="Avbryt", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btn_f, text="Spara", command=self._save).pack(side="right")

    def _load_current_values(self):
        printers_cfg = self.config.get("printers", self.config.get("printer", {}))
        self.label_printer_var.set(
            printers_cfg.get("label_printer_name") or printers_cfg.get("windows_printer_name", "")
        )
        self.label_format_var.set(printers_cfg.get("label_format") or printers_cfg.get("type", "pdf"))
        doc = printers_cfg.get("document_printer_name", "")
        self.doc_printer_var.set(doc if doc else "(ingen)")

        paths = self.config.get("paths", {})
        self.watch_dir_var.set(paths.get("watch_dir", ""))
        self.done_dir_var.set(paths.get("done_dir", ""))
        self.error_dir_var.set(paths.get("error_dir", ""))

    def _get_printers(self) -> list:
        if platform.system() != "Windows":
            return []
        try:
            from ..printing.printer import list_windows_printers
            return list_windows_printers()
        except Exception as e:
            logger.warning(f"Kunde inte hämta skrivarlista: {e}")
            return []

    def _browse_folder(self, var: tk.StringVar):
        folder = filedialog.askdirectory(
            initialdir=var.get() or None,
            title="Välj mapp",
        )
        if folder:
            var.set(folder)

    def _save(self):
        import yaml
        from ..utils.config import get_config_path

        doc_printer = self.doc_printer_var.get()
        if doc_printer == "(ingen)":
            doc_printer = ""

        # Uppdatera endast fälten som UI redigerar — bevara print_document_for_products, sumatra_exe m.fl.
        if "printers" not in self.config:
            self.config["printers"] = {}
        self.config["printers"]["label_printer_name"] = self.label_printer_var.get()
        self.config["printers"]["label_format"] = self.label_format_var.get()
        self.config["printers"]["document_printer_name"] = doc_printer
        self.config["printers"]["document_format"] = "pdf"
        self.config.pop("printer", None)

        self.config["paths"]["watch_dir"] = self.watch_dir_var.get()
        self.config["paths"]["done_dir"] = self.done_dir_var.get()
        self.config["paths"]["error_dir"] = self.error_dir_var.get()

        try:
            with open(get_config_path(), "w", encoding="utf-8") as f:
                yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

            logger.info("Inställningar sparade")
            if self.on_save:
                self.on_save(self.config)

            messagebox.showinfo("Sparat", "Inställningar sparade.", parent=self)
            self.destroy()
        except Exception as e:
            logger.error(f"Kunde inte spara: {e}")
            messagebox.showerror("Fel", f"Kunde inte spara:\n{e}", parent=self)
