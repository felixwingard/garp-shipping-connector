"""Skriv ut igen — dialog för att skriva om etiketter och dokument.

Listar alla cachade dokument i label_cache_dir och låter användaren
skriva ut dem på nytt utan att boka om.
"""

import logging
import platform
import threading
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import ttk, messagebox

logger = logging.getLogger(__name__)


def _font():
    return "Segoe UI" if platform.system() == "Windows" else "Helvetica Neue"


_DOC_SUFFIXES = {
    "_etikett.pdf": "Etikett",
    "_fraktlista.pdf": "Fraktlista",
    "_ADR.pdf": "ADR-deklaration",
}


def _scan_orders(cache_dir: Path) -> dict[str, dict[str, Path]]:
    """Skannar label_cache_dir och returnerar {order_no: {doc_type: path}}."""
    orders: dict[str, dict[str, Path]] = {}
    if not cache_dir.is_dir():
        return orders
    for f in cache_dir.iterdir():
        if not f.is_file() or not f.name.endswith(".pdf"):
            continue
        for suffix, label in _DOC_SUFFIXES.items():
            if f.name.endswith(suffix):
                order_no = f.name[: -len(suffix)]
                orders.setdefault(order_no, {})[label] = f
                break
    return orders


class ReprintDialog(tk.Toplevel):
    """Dialog för att skriva ut cachade etiketter och dokument på nytt."""

    def __init__(self, parent: tk.Tk, config: dict):
        super().__init__(parent)
        self.config = config
        self.cache_dir = Path(config["paths"]["label_cache_dir"])

        from ..printing.printer import LabelPrinter
        self.printer = LabelPrinter(config.get("printers", {}))

        self.title("Skriv ut igen")
        self.geometry("640x500")
        self.minsize(500, 350)
        self.resizable(True, True)
        self.configure(bg="#fafafa")

        self._orders: dict[str, dict[str, Path]] = {}
        self._filtered: list[str] = []

        self._center()
        self._build_ui()
        self._refresh_orders()

        self.focus_force()
        self.grab_set()

    def _center(self):
        self.update_idletasks()
        w, h = 640, 500
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        font = _font()

        header = tk.Frame(self, bg="#2c3e50", padx=16, pady=10)
        header.pack(fill="x")
        tk.Label(
            header, text="Skriv ut igen", font=(font, 14, "bold"),
            bg="#2c3e50", fg="white",
        ).pack(anchor="w")
        tk.Label(
            header, text="Välj en order och skriv ut etikett eller dokument på nytt.",
            font=(font, 9), bg="#2c3e50", fg="#bdc3c7",
        ).pack(anchor="w")

        search_frame = tk.Frame(self, bg="#fafafa", padx=16, pady=8)
        search_frame.pack(fill="x")
        tk.Label(
            search_frame, text="Sök ordernr:", font=(font, 10),
            bg="#fafafa",
        ).pack(side="left")
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_filter())
        search_entry = tk.Entry(
            search_frame, textvariable=self._search_var,
            font=(font, 10), width=20,
        )
        search_entry.pack(side="left", padx=(6, 0))

        refresh_btn = tk.Button(
            search_frame, text="↻ Uppdatera", font=(font, 9),
            command=self._refresh_orders, relief="flat", bg="#ecf0f1",
        )
        refresh_btn.pack(side="right")

        list_frame = tk.Frame(self, bg="#fafafa", padx=16)
        list_frame.pack(fill="both", expand=True, pady=(0, 4))

        cols = ("order", "docs")
        self._tree = ttk.Treeview(
            list_frame, columns=cols, show="headings", selectmode="browse",
        )
        self._tree.heading("order", text="Ordernummer")
        self._tree.heading("docs", text="Tillgängliga dokument")
        self._tree.column("order", width=160, anchor="w")
        self._tree.column("docs", width=380, anchor="w")

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        btn_frame = tk.Frame(self, bg="#fafafa", padx=16, pady=10)
        btn_frame.pack(fill="x")

        self._btn_label = tk.Button(
            btn_frame, text="🖨  Skriv ut etikett (Zebra)",
            font=(font, 10, "bold"), bg="#27ae60", fg="white",
            activebackground="#219a52", relief="flat", padx=14, pady=6,
            command=lambda: self._print_doc("Etikett"),
        )
        self._btn_label.pack(side="left", padx=(0, 8))

        self._btn_doc = tk.Button(
            btn_frame, text="🖨  Skriv ut dokument (A4)",
            font=(font, 10, "bold"), bg="#2980b9", fg="white",
            activebackground="#2471a3", relief="flat", padx=14, pady=6,
            command=self._print_all_docs,
        )
        self._btn_doc.pack(side="left")

        self._status_label = tk.Label(
            btn_frame, text="", font=(font, 9), bg="#fafafa", fg="#7f8c8d",
        )
        self._status_label.pack(side="right")

    def _refresh_orders(self):
        self._orders = _scan_orders(self.cache_dir)
        self._apply_filter()

    def _apply_filter(self):
        query = self._search_var.get().strip().lower()
        if query:
            self._filtered = sorted(
                [o for o in self._orders if query in o.lower()],
                key=lambda o: self._order_mtime(o),
                reverse=True,
            )
        else:
            self._filtered = sorted(
                self._orders.keys(),
                key=lambda o: self._order_mtime(o),
                reverse=True,
            )
        self._populate_tree()

    def _order_mtime(self, order_no: str) -> float:
        docs = self._orders.get(order_no, {})
        if not docs:
            return 0.0
        return max(p.stat().st_mtime for p in docs.values())

    def _populate_tree(self):
        self._tree.delete(*self._tree.get_children())
        for order_no in self._filtered:
            docs = self._orders[order_no]
            doc_names = ", ".join(sorted(docs.keys()))
            self._tree.insert("", "end", iid=order_no, values=(order_no, doc_names))

    def _selected_order(self) -> Optional[str]:
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning("Välj order", "Markera en order i listan.", parent=self)
            return None
        return sel[0]

    def _print_doc(self, doc_type: str):
        order_no = self._selected_order()
        if not order_no:
            return
        docs = self._orders.get(order_no, {})
        path = docs.get(doc_type)
        if not path or not path.is_file():
            messagebox.showinfo(
                "Saknas",
                f"Ingen {doc_type.lower()} hittades för order {order_no}.",
                parent=self,
            )
            return
        self._status_label.config(text=f"Skriver ut {doc_type.lower()}...")
        self.update_idletasks()

        def _do():
            data = path.read_bytes()
            if doc_type == "Etikett":
                ok = self.printer.print_label(data, "pdf", order_no)
            else:
                ok = self.printer.print_document(data, "pdf", order_no)
            self.after(0, lambda: self._print_done(doc_type, order_no, ok))

        threading.Thread(target=_do, daemon=True).start()

    def _print_all_docs(self):
        """Skriver ut fraktlista + ADR (alla icke-etikett-dokument) till A4."""
        order_no = self._selected_order()
        if not order_no:
            return
        docs = self._orders.get(order_no, {})
        to_print = {k: v for k, v in docs.items() if k != "Etikett"}
        if not to_print:
            messagebox.showinfo(
                "Saknas",
                f"Inga dokument (fraktlista/ADR) hittades för order {order_no}.",
                parent=self,
            )
            return
        self._status_label.config(text="Skriver ut dokument...")
        self.update_idletasks()

        def _do():
            results = []
            for doc_type, path in to_print.items():
                data = path.read_bytes()
                ok = self.printer.print_document(data, "pdf", f"{order_no}_{doc_type}")
                results.append((doc_type, ok))
            ok_all = all(ok for _, ok in results)
            summary = ", ".join(dt for dt, _ in results)
            self.after(0, lambda: self._print_done(summary, order_no, ok_all))

        threading.Thread(target=_do, daemon=True).start()

    def _print_done(self, doc_type: str, order_no: str, ok: bool):
        if ok:
            self._status_label.config(
                text=f"✓ {doc_type} utskriven för {order_no}", fg="#27ae60",
            )
        else:
            self._status_label.config(
                text=f"✗ Utskrift misslyckades för {order_no}", fg="#e74c3c",
            )
