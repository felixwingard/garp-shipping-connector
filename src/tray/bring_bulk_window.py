"""Bring Bulk-fönster — reservera bulk-nummer, slutför pall.

Öppnas från tray-menyn när Bring är konfigurerad.
"""

import logging
import subprocess
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox

logger = logging.getLogger(__name__)


def _font():
    import platform
    return "Segoe UI" if platform.system() == "Windows" else "Helvetica Neue"


class BringBulkWindow(tk.Toplevel):
    """Fönster för Bring bulk-operationer."""

    def __init__(self, parent: tk.Tk, config: dict, on_bulk_id_reserved=None):
        super().__init__(parent)
        self.config = config
        self.on_bulk_id_reserved = on_bulk_id_reserved  # Callback när ny bulk-ID sparas

        self.title("Bring Bulk — Norge")
        self.geometry("420x480")
        self.resizable(False, False)
        self.configure(bg="#fafafa")

        self._center()
        self._build_ui()
        self._load_terminals()

        self.focus_force()
        self.grab_set()

    def _center(self):
        self.update_idletasks()
        w, h = 420, 480
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _section(self, parent, title: str):
        f = tk.Frame(parent, bg="#fafafa")
        f.pack(fill="x", pady=(0, 12))
        tk.Label(
            f, text=title, font=(_font(), 10, "bold"),
            fg="#334155", bg="#fafafa",
        ).pack(anchor="w", pady=(0, 6))
        card = tk.Frame(f, bg="white", highlightbackground="#e5e7eb", highlightthickness=1)
        card.pack(fill="x")
        return card

    def _build_ui(self):
        main = tk.Frame(self, bg="#fafafa", padx=16, pady=16)
        main.pack(fill="both", expand=True)

        # Reservera bulk-nummer
        sec = self._section(main, "1. Reservera bulk-nummer")
        inner = tk.Frame(sec, bg="white", padx=16, pady=12)
        inner.pack(fill="x")

        tk.Label(inner, text="Terminal (Norge)", font=(_font(), 9), fg="#64748b", bg="white", width=14, anchor="w").pack(anchor="w")
        term_row = tk.Frame(inner, bg="white")
        term_row.pack(fill="x", pady=(0, 4))
        self.terminal_var = tk.StringVar()
        self.terminal_combo = ttk.Combobox(
            term_row, textvariable=self.terminal_var,
            width=30, state="readonly"
        )
        self.terminal_combo.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(term_row, text="Ladda om", width=8, command=self._load_terminals).pack(side="right")

        self.reserve_btn = ttk.Button(
            inner, text="Reservera nummer",
            command=self._do_reserve
        )
        self.reserve_btn.pack(anchor="w", pady=(0, 8))

        tk.Label(inner, text="Aktuellt bulk-ID:", font=(_font(), 9), fg="#64748b", bg="white").pack(anchor="w", pady=(8, 0))
        self.bulk_id_var = tk.StringVar()
        bulk_entry = ttk.Entry(inner, textvariable=self.bulk_id_var, width=30, state="readonly")
        bulk_entry.pack(fill="x", pady=(4, 0))
        self._update_bulk_id_display()

        ttk.Button(
            inner, text="Avsluta bulk (starta nytt nästa vecka)",
            command=self._do_clear_bulk
        ).pack(anchor="w", pady=(8, 0))

        # Slutför bulk
        sec2 = self._section(main, "2. Slutför bulk (när pallen är packad)")
        inner2 = tk.Frame(sec2, bg="white", padx=16, pady=12)
        inner2.pack(fill="x")

        row = tk.Frame(inner2, bg="white")
        row.pack(fill="x", pady=4)
        tk.Label(row, text="Totalvikt (kg)", font=(_font(), 9), fg="#64748b", bg="white", width=14, anchor="w").pack(side="left")
        self.weight_var = tk.StringVar(value="")
        ttk.Entry(row, textvariable=self.weight_var, width=10).pack(side="left")

        row2 = tk.Frame(inner2, bg="white")
        row2.pack(fill="x", pady=4)
        tk.Label(row2, text="Antal kolli", font=(_font(), 9), fg="#64748b", bg="white", width=14, anchor="w").pack(side="left")
        self.num_packages_var = tk.StringVar(value="")
        ttk.Entry(row2, textvariable=self.num_packages_var, width=10).pack(side="left")
        tk.Label(row2, text="(räknas automatiskt per vecka — kan överstyras)", font=(_font(), 8), fg="#94a3b8", bg="white").pack(side="left", padx=(4, 0))

        self.register_btn = ttk.Button(
            inner2, text="Registrera pall → hämta CMR",
            command=self._do_register
        )
        self.register_btn.pack(anchor="w", pady=(12, 0))

        tk.Label(
            main, text="Alla paket med BRING:0332 använder bulk-ID ovan.",
            font=(_font(), 8), fg="#94a3b8", bg="#fafafa",
        ).pack(anchor="w", pady=(0, 8))

    def _load_terminals(self):
        bring = self.config.get("bring", {})
        if not bring:
            self.terminal_combo["values"] = ["Bring saknas i config — lägg till api_uid, api_key, customer_number"]
            self._terminal_ids = []
            return
        if not bring.get("api_uid") or not bring.get("api_key"):
            self.terminal_combo["values"] = ["api_uid och api_key krävs i bring-config"]
            self._terminal_ids = []
            return
        try:
            from ..carriers.bring_bulksplit import BringBulksplitClient
            client = BringBulksplitClient(bring, self.config.get("sender", {}))
            terminals = client.list_terminals()
            # Visa Norge-terminaler först
            no_terms = [t for t in terminals if t.get("countryCode") == "NO"]
            other = [t for t in terminals if t.get("countryCode") != "NO"]
            items = [f"{t.get('id', '')} — {t.get('name', '')} ({t.get('city', '')})" for t in no_terms + other]
            ids = [t.get("id", "") for t in no_terms + other]
            self.terminal_combo["values"] = items if items else ["Inga terminaler — kontrollera nätverk och API-åtkomst"]
            self._terminal_ids = ids
            if ids:
                self.terminal_combo.current(0)
        except Exception as e:
            err_msg = str(e).replace("\n", " ")[:80]
            logger.warning(f"Kunde inte hämta Bring-terminaler: {e}")
            self.terminal_combo["values"] = [f"Fel: {err_msg}"]
            self._terminal_ids = []

    def _update_bulk_id_display(self):
        bid = self.config.get("bring", {}).get("consolidated_shipment_id", "")
        self.bulk_id_var.set(bid or "(ingen reserverad)")
        self._update_parcel_count_display()

    def _update_parcel_count_display(self):
        """Uppdaterar antal kolli från config (räknas vid varje bokning)."""
        count = self.config.get("bring", {}).get("bulk_parcel_count", 0)
        self.num_packages_var.set(str(count) if count else "")

    def _do_clear_bulk(self):
        """Avslutar aktuellt bulk-ID så att nästa vecka kan starta nytt."""
        bid = self.config.get("bring", {}).get("consolidated_shipment_id", "").strip()
        if not bid:
            messagebox.showinfo("Info", "Inget bulk-ID är reserverat.", parent=self)
            return
        if not messagebox.askyesno("Avsluta bulk", f"Avsluta bulk-ID {bid}?\nNästa vecka kan du reservera nytt bulk.", parent=self):
            return
        self._save_bulk_id("", reset_parcel_count=True)
        self._update_bulk_id_display()
        if self.on_bulk_id_reserved:
            self.on_bulk_id_reserved(self.config)
        messagebox.showinfo("Klar", "Bulk avslutat. Reservera nytt bulk-ID när du ska skicka nästa gång.", parent=self)

    def _save_bulk_id(self, bulk_id: str, reset_parcel_count: bool = False):
        """Sparar bulk-ID till config.yaml. Om reset_parcel_count: nollställ kolli-räknaren."""
        from ..utils.config import get_config_path
        import yaml
        path = get_config_path()
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        if "bring" not in cfg:
            cfg["bring"] = {}
        cfg["bring"]["consolidated_shipment_id"] = bulk_id
        if reset_parcel_count:
            cfg["bring"]["bulk_parcel_count"] = 0
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        if "bring" not in self.config:
            self.config["bring"] = {}
        self.config["bring"]["consolidated_shipment_id"] = bulk_id
        if reset_parcel_count:
            self.config["bring"]["bulk_parcel_count"] = 0

    def _do_reserve(self):
        bring = self.config.get("bring", {})
        if not bring:
            messagebox.showerror("Fel", "Bring är inte konfigurerad.", parent=self)
            return
        idx = self.terminal_combo.current()
        ids = getattr(self, "_terminal_ids", [])
        if idx < 0 or not ids:
            msg = "Inga terminaler tillgängliga. Kontrollera Bring-config (api_uid, api_key, customer_number) och nätverk." if not ids else "Välj en terminal."
            messagebox.showerror("Fel", msg, parent=self)
            return
        terminal_id = self._terminal_ids[idx]
        self.reserve_btn.config(state="disabled", text="Reserverar...")
        self.update()
        try:
            from ..carriers.bring_bulksplit import BringBulksplitClient
            from ..utils.config import get_config_path
            import yaml

            client = BringBulksplitClient(bring, self.config.get("sender", {}))
            bulk_id = client.reserve_bulk_id(terminal_id)

            self._save_bulk_id(bulk_id, reset_parcel_count=True)
            self._update_bulk_id_display()
            if self.on_bulk_id_reserved:
                self.on_bulk_id_reserved(self.config)
            messagebox.showinfo("Klar", f"Bulk-ID reserverat: {bulk_id}", parent=self)
        except Exception as e:
            logger.error(f"Bring reserve fel: {e}", exc_info=True)
            messagebox.showerror("Fel", str(e), parent=self)
        finally:
            self.reserve_btn.config(state="normal", text="Reservera nummer")

    def _do_register(self):
        bulk_id = self.config.get("bring", {}).get("consolidated_shipment_id", "").strip()
        if not bulk_id:
            messagebox.showerror("Fel", "Reservera bulk-nummer först.", parent=self)
            return
        try:
            weight = int(float(self.weight_var.get() or "0"))
        except ValueError:
            messagebox.showerror("Fel", "Ange totalvikt i kg (heltal).", parent=self)
            return
        if weight < 1:
            messagebox.showerror("Fel", "Totalvikt måste vara minst 1 kg.", parent=self)
            return

        num_packages = None
        np_str = (self.num_packages_var.get() or "").strip()
        if np_str:
            try:
                num_packages = int(np_str)
                if num_packages < 1:
                    num_packages = None
            except ValueError:
                pass
        if num_packages is None:
            num_packages = self.config.get("bring", {}).get("bulk_parcel_count")

        bring = self.config.get("bring", {})
        if not bring:
            messagebox.showerror("Fel", "Bring är inte konfigurerad.", parent=self)
            return

        self.register_btn.config(state="disabled", text="Registrerar...")
        self.update()
        try:
            from ..carriers.bring_bulksplit import BringBulksplitClient

            client = BringBulksplitClient(bring, self.config.get("sender", {}))
            result = client.register_bulk_shipment(
                bulk_shipment_id=bulk_id,
                total_weight_kg=weight,
                num_packages=num_packages,
                service_code="0332",
            )
            waybill_url = result.get("waybillUrl", "")
            routing_url = result.get("routingLabelsUrl", "")

            msg = f"Pall registrerad: {bulk_id}"
            if waybill_url or routing_url:
                msg += "\n\nÖppna CMR/routing i webbläsare?"
            messagebox.showinfo("Klar", msg, parent=self)

            if waybill_url or routing_url:
                if messagebox.askyesno("Öppna dokument", "Vill du öppna CMR-waybill?", parent=self):
                    _open_url(waybill_url or routing_url)
                elif routing_url and messagebox.askyesno("Öppna dokument", "Öppna routing-labels?", parent=self):
                    _open_url(routing_url)

            # Töm bulk-ID — nästa pall kräver ny reservation
            self.config["bring"]["consolidated_shipment_id"] = ""
            self._update_bulk_id_display()
            self._save_bulk_id("", reset_parcel_count=True)
        except Exception as e:
            logger.error(f"Bring register fel: {e}", exc_info=True)
            messagebox.showerror("Fel", str(e), parent=self)
        finally:
            self.register_btn.config(state="normal", text="Registrera pall → hämta CMR")


def _open_url(url: str):
    """Öppnar URL i webbläsare eller nedladdar PDF."""
    if not url:
        return
    try:
        webbrowser.open(url)
    except Exception:
        import sys
        if sys.platform == "win32":
            subprocess.Popen(["start", "", url], shell=True)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", url])
        else:
            subprocess.Popen(["xdg-open", url])
