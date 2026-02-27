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
        self.geometry("520x620")
        self.minsize(420, 400)
        self.resizable(True, True)
        self.configure(bg="#fafafa")

        self._center()
        self._build_ui()
        self._load_terminals()

        self.focus_force()
        self.grab_set()

    def _center(self):
        self.update_idletasks()
        w, h = 520, 620
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
        # Scrollbar + canvas så att allt innehåll når även i litet fönster
        canvas = tk.Canvas(self, bg="#fafafa", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self)
        main = tk.Frame(canvas, bg="#fafafa", padx=16, pady=16)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.configure(command=canvas.yview)

        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_mousewheel(event):
            import platform
            if platform.system() == "Darwin":
                canvas.yview_scroll(int(-1 * event.delta), "units")
            else:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas_window = canvas.create_window((0, 0), window=main, anchor="nw")
        main.bind("<Configure>", _on_frame_configure)

        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)

        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.bind("<MouseWheel>", _on_mousewheel)

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
        tk.Label(row, text="(räknas automatiskt — kan överstyras)", font=(_font(), 8), fg="#94a3b8", bg="white").pack(side="left", padx=(4, 0))

        row2 = tk.Frame(inner2, bg="white")
        row2.pack(fill="x", pady=4)
        tk.Label(row2, text="Antal kolli (paket)", font=(_font(), 9), fg="#64748b", bg="white", width=14, anchor="w").pack(side="left")
        self.num_packages_var = tk.StringVar(value="")
        ttk.Entry(row2, textvariable=self.num_packages_var, width=10).pack(side="left")
        tk.Label(row2, text="(räknas automatiskt — kan överstyras)", font=(_font(), 8), fg="#94a3b8", bg="white").pack(side="left", padx=(4, 0))

        row3 = tk.Frame(inner2, bg="white")
        row3.pack(fill="x", pady=4)
        tk.Label(row3, text="Antal pall (Bulk)", font=(_font(), 9), fg="#64748b", bg="white", width=14, anchor="w").pack(side="left")
        self.num_pallets_var = tk.StringVar(value="1")
        ttk.Entry(row3, textvariable=self.num_pallets_var, width=10).pack(side="left")
        tk.Label(row3, text="(splittas på terminal)", font=(_font(), 8), fg="#94a3b8", bg="white").pack(side="left", padx=(4, 0))

        row4 = tk.Frame(inner2, bg="white")
        row4.pack(fill="x", pady=4)
        tk.Label(row4, text="Hel pall till kund", font=(_font(), 9), fg="#64748b", bg="white", width=14, anchor="w").pack(side="left")
        self.num_direct_pallets_var = tk.StringVar(value="0")
        self.direct_pallets_weight_var = tk.StringVar(value="")
        tk.Label(row4, text="Antal:", font=(_font(), 8), fg="#94a3b8", bg="white").pack(side="left", padx=(0, 4))
        ttk.Entry(row4, textvariable=self.num_direct_pallets_var, width=4).pack(side="left")
        tk.Label(row4, text="Vikt (kg):", font=(_font(), 8), fg="#94a3b8", bg="white").pack(side="left", padx=(8, 4))
        ttk.Entry(row4, textvariable=self.direct_pallets_weight_var, width=8).pack(side="left")
        tk.Label(row4, text="(Business Pallet, går direkt till mottagare)", font=(_font(), 8), fg="#94a3b8", bg="white").pack(side="left", padx=(4, 0))

        row5 = tk.Frame(inner2, bg="white")
        row5.pack(fill="x", pady=4)
        tk.Label(row5, text="Antal fakturakopior", font=(_font(), 9), fg="#64748b", bg="white", width=14, anchor="w").pack(side="left")
        self.num_invoices_var = tk.StringVar(value="3")
        ttk.Entry(row5, textvariable=self.num_invoices_var, width=6).pack(side="left")
        tk.Label(row5, text="(t.ex. 3 för SE→NO)", font=(_font(), 8), fg="#94a3b8", bg="white").pack(side="left", padx=(4, 0))

        self.register_btn = ttk.Button(
            inner2, text="Registrera pall → hämta CMR",
            command=self._do_register
        )
        self.register_btn.pack(anchor="w", pady=(12, 0))

        tk.Label(
            main, text="Alla paket med BRING:0332 använder bulk-ID ovan.",
            font=(_font(), 8), fg="#94a3b8", bg="#fafafa",
        ).pack(anchor="w", pady=(0, 8))

        self._update_bulk_id_display()
        self._schedule_parcel_refresh()

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
        """Uppdaterar antal kolli och totalvikt. Prioritet: 1) Excel (bulk_orders) 2) config.yaml."""
        if not hasattr(self, "num_packages_var") or not hasattr(self, "weight_var"):
            return
        bulk_id = self.config.get("bring", {}).get("consolidated_shipment_id", "").strip()
        count, weight = None, None
        # Läs från bulk-Excel först (källan för totalvikt och antal kolli)
        if bulk_id:
            try:
                from ..utils.bulk_export import get_bulk_totals
                totals = get_bulk_totals(bulk_id)
                if totals.get("num_packages") or totals.get("total_weight_kg"):
                    count = int(totals.get("num_packages", 0))
                    weight = float(totals.get("total_weight_kg", 0))
            except Exception:
                pass
        # Fallback till config om Excel saknar data
        if count is None or weight is None:
            try:
                from ..utils.config import get_config_path
                import yaml
                path = get_config_path()
                if path.exists():
                    with open(path, "r", encoding="utf-8") as f:
                        cfg = yaml.safe_load(f) or {}
                    bring = cfg.get("bring", {})
                    if count is None:
                        count = bring.get("bulk_parcel_count", 0)
                    if weight is None:
                        weight = float(bring.get("bulk_total_weight_kg", 0) or 0)
            except Exception:
                pass
        self.num_packages_var.set(str(count) if count else "")
        self.weight_var.set(str(int(weight)) if weight else "")

    def _schedule_parcel_refresh(self):
        """Startar periodisk uppdatering av kolli/vikt (var 3:e sekund)."""
        if not self.winfo_exists():
            return
        self._update_parcel_count_display()
        self.after(3000, self._schedule_parcel_refresh)

    def _do_clear_bulk(self):
        """Avslutar aktuellt bulk-ID — skapar Excel-backup och nollställer för nästa vecka."""
        bid = self.config.get("bring", {}).get("consolidated_shipment_id", "").strip()
        if not bid:
            messagebox.showinfo("Info", "Inget bulk-ID är reserverat.", parent=self)
            return
        if not messagebox.askyesno("Avsluta bulk", f"Avsluta bulk-ID {bid}?\nExcel-backup skapas i bulk_exports/. Nästa vecka kan du reservera nytt bulk.", parent=self):
            return
        # Skapa Excel-backup (en fil per bulk) innan avslut
        excel_path = None
        try:
            from ..utils.bulk_export import export_bulk_to_excel, get_bulk_orders, get_bulk_totals, clear_bulk_orders
            orders = get_bulk_orders(bid)
            totals = get_bulk_totals(bid)
            excel_path = export_bulk_to_excel(
                bulk_id=bid,
                total_weight_kg=int(totals.get("total_weight_kg", 0)),
                num_packages=int(totals.get("num_packages", 0)),
                num_pallets=1,
                num_direct_pallets=0,
                direct_pallets_weight_kg=0,
                num_invoices=3,
                waybill_url="",
                routing_url="",
                orders=orders,
                config=self.config,
            )
            if excel_path is None:
                messagebox.showwarning(
                    "Excel kunde inte skapas",
                    "openpyxl saknas eller kunde inte ladda. "
                    "Excel-backup skapas ej. Bygg om programmet (pyinstaller) för att inkludera openpyxl.",
                    parent=self,
                )
            clear_bulk_orders(bid)
        except Exception as e:
            logger.warning(f"Excel-backup vid avsluta bulk: {e}", exc_info=True)
            export_dir = self.config.get("paths", {}).get("bulk_exports_dir", "(standardmapp)")
            messagebox.showwarning(
                "Excel kunde inte sparas",
                f"Excel-backup kunde inte skapas:\n\n{type(e).__name__}: {e}\n\n"
                f"Mål-mapp (config): {export_dir}\n\n"
                "Kontrollera att mappen finns och är skrivbar. "
                "Se garp_shipping.log för mer information.",
                parent=self,
            )
        self._save_bulk_id("", reset_parcel_count=True)
        self._update_bulk_id_display()
        if self.on_bulk_id_reserved:
            self.on_bulk_id_reserved(self.config)
        msg = "Bulk avslutat. Reservera nytt bulk-ID när du ska skicka nästa gång."
        if excel_path:
            msg += f"\n\nExcel-backup sparad: {excel_path}"
        messagebox.showinfo("Klar", msg, parent=self)

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
            cfg["bring"]["bulk_total_weight_kg"] = 0
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        if "bring" not in self.config:
            self.config["bring"] = {}
        self.config["bring"]["consolidated_shipment_id"] = bulk_id
        if reset_parcel_count:
            self.config["bring"]["bulk_parcel_count"] = 0
            self.config["bring"]["bulk_total_weight_kg"] = 0

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
        num_direct_pre = 0
        direct_weight_pre = 0
        try:
            num_direct_pre = max(0, int(self.num_direct_pallets_var.get() or "0"))
            direct_weight_pre = max(0, int(self.direct_pallets_weight_var.get() or "0"))
        except ValueError:
            pass

        if weight < 1 and not (num_direct_pre > 0 and direct_weight_pre >= 1):
            messagebox.showerror("Fel", "Ange totalvikt (Bulk) eller hel pall till kund med vikt.", parent=self)
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
            try:
                from ..utils.bulk_export import get_bulk_totals
                totals = get_bulk_totals(bulk_id)
                num_packages = totals.get("num_packages", 0)
            except Exception:
                num_packages = self.config.get("bring", {}).get("bulk_parcel_count", 0)

        num_pallets = 1
        npal_str = (self.num_pallets_var.get() or "1").strip()
        if npal_str:
            try:
                num_pallets = int(npal_str)
                if num_pallets < 1:
                    num_pallets = 1
            except ValueError:
                num_pallets = 1

        bring = self.config.get("bring", {})
        if not bring:
            messagebox.showerror("Fel", "Bring är inte konfigurerad.", parent=self)
            return

        self.register_btn.config(state="disabled", text="Registrerar...")
        self.update()
        try:
            from ..carriers.bring_bulksplit import BringBulksplitClient

            client = BringBulksplitClient(bring, self.config.get("sender", {}))
            num_direct = 0
            direct_weight = 0
            npd_str = (self.num_direct_pallets_var.get() or "0").strip()
            if npd_str:
                try:
                    num_direct = max(0, int(npd_str))
                except ValueError:
                    pass
            dw_str = (self.direct_pallets_weight_var.get() or "0").strip()
            if dw_str:
                try:
                    direct_weight = max(0, int(dw_str))
                except ValueError:
                    pass

            num_invoices_val = 3
            ni_str = (self.num_invoices_var.get() or "3").strip()
            if ni_str:
                try:
                    num_invoices_val = max(0, int(ni_str))
                except ValueError:
                    pass

            result = client.register_bulk_shipment(
                bulk_shipment_id=bulk_id,
                total_weight_kg=weight,
                num_packages=num_packages,
                num_pallets=num_pallets,
                num_direct_pallets=num_direct,
                direct_pallets_weight_kg=direct_weight,
                num_invoices=num_invoices_val if num_invoices_val > 0 else None,
                bulk_service_code="0332",
                direct_service_code="0336",
            )
            waybill_url = result.get("waybillUrl", "")
            routing_url = result.get("routingLabelsUrl", "")

            total_p = num_pallets + num_direct
            pall_txt = f"{total_p} pallar" if total_p != 1 else "Pall"
            msg = f"{pall_txt} registrerad(e): {bulk_id}"
            if waybill_url or routing_url:
                msg += "\n\nÖppna CMR/routing i webbläsare?"
            messagebox.showinfo("Klar", msg, parent=self)

            if waybill_url or routing_url:
                if waybill_url and messagebox.askyesno("Öppna dokument", "Vill du öppna CMR-waybill?", parent=self):
                    _open_url(waybill_url)
                if routing_url and messagebox.askyesno("Öppna dokument", "Vill du öppna routing labels (fraksedlar)?", parent=self):
                    _open_url(routing_url)

            # Behåll bulk-ID tills användaren trycker "Avsluta bulk" (då skapas Excel-backup)
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
