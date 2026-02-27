"""TrayApp — system tray-app med pystray + tkinter.

Arkitektur med 3 trådar:
1. Huvudtråd: tkinter mainloop (hanterar alla fönster)
2. Daemon-tråd 1: pystray (tray-ikon + högerklicksmeny)
3. Daemon-tråd 2: service (watcher + orchestrator)

Kommunikation: pystray → queue → tkinter (trådsäkert)
"""

import os
import queue
import socket
import sys
import time
import logging
import threading
import tkinter as tk
from pathlib import Path
from typing import Optional

from ..parsers.models import Shipment, DangerousGoodsInfo

logger = logging.getLogger(__name__)

# Port för single-instance lock (bara en instans får köra)
_SINGLE_INSTANCE_PORT = 38473

# Status-ikonfärger
STATUS_IDLE = "idle"         # Grön — väntar på filer
STATUS_PROCESSING = "busy"   # Gul — bearbetar sändning
STATUS_ERROR = "error"       # Röd — senaste bearbetning misslyckades


class TrayApp:
    """System tray-applikation för GARP Shipping Connector.

    Kör som system tray-ikon med högerklicksmeny:
    - Inställningar (skrivarval, mappval)
    - Status (senaste sändningar)
    - Avsluta
    """

    def __init__(self):
        self.config = None
        self.orchestrator = None
        self.watcher = None
        self.tray_icon = None
        self._instance_socket = None
        self.status = STATUS_IDLE

        # Queue för trådsäker kommunikation: pystray/service → tkinter
        self._queue: queue.Queue = queue.Queue()

        # Tray-ikonen
        self._icon = None
        self._icon_images = {}

        # Fönster-instanser (skapas vid behov)
        self._settings_window = None
        self._status_window = None
        self._bring_bulk_window = None

        # Shipment-historik för statusfönstret
        self.shipment_history: list[dict] = []
        self.max_history = 50

    def _acquire_single_instance(self) -> bool:
        """Försöker binda port för att förhindra flera instanser. Returnerar True om OK."""
        try:
            self._instance_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._instance_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._instance_socket.bind(("127.0.0.1", _SINGLE_INSTANCE_PORT))
            return True
        except OSError:
            logger.warning("En annan instans av GARP Shipping Connector kör redan")
            return False

    def run(self):
        """Startar appen — blockerar tills avslut.

        1. Kontrollera single instance
        2. Ladda config
        3. Sätt upp logging
        4. Skapa tkinter root (withdrawn)
        5. Starta pystray i daemon-tråd
        6. Starta service i daemon-tråd
        7. Kör tkinter mainloop
        """
        if not self._acquire_single_instance():
            try:
                _r = tk.Tk()
                _r.withdraw()
                from tkinter import messagebox
                messagebox.showinfo("GARP Shipping Connector", "En annan instans kör redan.")
            except Exception:
                pass
            return
        # 1. Ladda config + logging
        self._load_config()
        self._setup_logging()

        logger.info("GARP Shipping Connector startar (tray-läge)")

        # 2. Skapa tkinter root (dold — aldrig synlig)
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("GARP Shipping Connector")

        # Tema för clean UI
        try:
            from .theme import apply_theme
            apply_theme(self.root)
        except Exception as e:
            logger.debug(f"Tema kunde inte appliceras: {e}")

        # Gör så att stängning av root avslutar appen
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        # 3. Starta pystray i daemon-tråd
        tray_thread = threading.Thread(target=self._run_tray, daemon=True)
        tray_thread.start()

        # 4. Starta service i daemon-tråd
        service_thread = threading.Thread(target=self._run_service, daemon=True)
        service_thread.start()

        # 5. Starta queue-polling
        self.root.after(100, self._poll_queue)

        # 6. Kör tkinter mainloop (blockerar)
        logger.info("Tray-app igång — högerklicka på ikonen för meny")
        self.root.mainloop()

    def quit(self):
        """Avslutar appen."""
        logger.info("Avslutar GARP Shipping Connector...")

        # Stoppa watcher
        if self.watcher:
            try:
                self.watcher.stop()
            except Exception:
                pass

        # Stoppa tray-ikon (först så den försvinner från systemfältet)
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

        # Stäng instance-socket (frigör port för nästa start)
        if getattr(self, "_instance_socket", None):
            try:
                self._instance_socket.close()
            except Exception:
                pass

        # Stäng tkinter
        try:
            if self.root.winfo_exists():
                self.root.quit()
                self.root.destroy()
        except Exception:
            pass

        logger.info("Avslutad")
        os._exit(0)  # Tvinga processavslut — undvik kvarvarande zombier

    # ------------------------------------------------------------------
    # Queue-bro (pystray → tkinter)
    # ------------------------------------------------------------------

    def _poll_queue(self):
        """Kollar kön för meddelanden från andra trådar. Körs 10x/sek."""
        try:
            while True:
                msg = self._queue.get_nowait()
                self._handle_message(msg)
        except queue.Empty:
            pass

        # Schemalägg nästa poll (om root finns)
        try:
            self.root.after(100, self._poll_queue)
        except tk.TclError:
            pass

    def _handle_message(self, msg: dict):
        """Hanterar ett meddelande från kön."""
        action = msg.get("action")

        if action == "show_settings":
            self._show_settings()
        elif action == "show_status":
            self._show_status()
        elif action == "show_bring_bulk":
            self._show_bring_bulk()
        elif action == "quit":
            self.quit()
        elif action == "shipment_event":
            self._on_shipment_event(msg.get("event_type"), msg.get("data", {}))
        elif action == "request_dangerous_goods":
            self._show_dangerous_goods_dialog(
                msg.get("order_no", ""),
                msg.get("filepath", ""),
                msg.get("event"),
                msg.get("result"),
            )

    # ------------------------------------------------------------------
    # Tray-ikon (pystray)
    # ------------------------------------------------------------------

    def _run_tray(self):
        """Kör pystray i en daemon-tråd."""
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError as e:
            logger.error(
                f"Kan inte starta tray-ikon: {e}. "
                f"Installera: pip install pystray Pillow"
            )
            return

        # Skapa ikon-bilder
        self._icon_images = {
            STATUS_IDLE: self._create_icon_image(ImageDraw, Image, "#2ecc71"),     # Grön
            STATUS_PROCESSING: self._create_icon_image(ImageDraw, Image, "#f39c12"),  # Gul
            STATUS_ERROR: self._create_icon_image(ImageDraw, Image, "#e74c3c"),    # Röd
        }

        menu = pystray.Menu(
            pystray.MenuItem(
                "GARP Shipping Connector",
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Status",
                lambda icon, item: self._queue.put({"action": "show_status"}),
                default=True,
            ),
            pystray.MenuItem(
                "Inställningar",
                lambda icon, item: self._queue.put({"action": "show_settings"}),
            ),
            pystray.MenuItem(
                "Bring Bulk (Norge)",
                lambda icon, item: self._queue.put({"action": "show_bring_bulk"}),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Avsluta",
                lambda icon, item: self._queue.put({"action": "quit"}),
            ),
        )

        self._icon = pystray.Icon(
            name="garp-shipping",
            icon=self._icon_images[STATUS_IDLE],
            title="GARP Shipping Connector — Väntar...",
            menu=menu,
        )

        logger.info("Tray-ikon startad")
        self._icon.run()

    def _create_icon_image(self, ImageDraw, Image, color: str):
        """Skapar en enkel ikon-bild (64x64 med en cirkel)."""
        size = 64
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        # Bakgrundscirkel
        draw.ellipse([4, 4, size - 4, size - 4], fill=color)

        # "G" i mitten (för GARP)
        try:
            draw.text((size // 2, size // 2), "G", fill="white", anchor="mm")
        except Exception:
            # Om font inte stöder anchor, rita utan
            draw.text((22, 18), "G", fill="white")

        return image

    def _update_tray_status(self, status: str, tooltip: str = ""):
        """Uppdaterar tray-ikonens färg och tooltip."""
        self.status = status
        if self._icon and self._icon_images:
            try:
                self._icon.icon = self._icon_images.get(status, self._icon_images[STATUS_IDLE])
                if tooltip:
                    self._icon.title = f"GARP Shipping — {tooltip}"
            except Exception as e:
                logger.debug(f"Kunde inte uppdatera tray-ikon: {e}")

    # ------------------------------------------------------------------
    # Service (watcher + orchestrator)
    # ------------------------------------------------------------------

    def _run_service(self):
        """Kör fraktservice i en daemon-tråd."""
        try:
            from ..orchestrator import ShipmentOrchestrator
            from ..watcher import FolderWatcher

            self.orchestrator = ShipmentOrchestrator(
                self.config,
                on_event=self._on_service_event,
                get_dangerous_goods=self._get_dangerous_goods_callback,
            )

            watch_dir = self.config["paths"]["watch_dir"]
            stability = self.config["watcher"]["file_stability_seconds"]

            self.watcher = FolderWatcher(watch_dir, self.orchestrator, stability)
            self.watcher.process_existing_files()
            self.watcher.start()

            logger.info(f"Service startad — bevakar: {watch_dir}")

            # Håll tråden levande
            while True:
                time.sleep(1)

        except Exception as e:
            logger.critical(f"Service-fel: {e}", exc_info=True)
            self._update_tray_status(STATUS_ERROR, f"Fel: {e}")

    def _on_service_event(self, event_type: str, data: dict):
        """Callback från orchestrator — körs i service-tråden."""
        # Skicka till tkinter-tråden via kön
        self._queue.put({
            "action": "shipment_event",
            "event_type": event_type,
            "data": data,
        })

        # Uppdatera tray-ikon direkt (trådsäkert i pystray)
        if event_type == "shipment_ok":
            self._update_tray_status(
                STATUS_IDLE,
                f"Senaste: {data.get('order_no', '')} OK"
            )
        elif event_type == "shipment_error":
            self._update_tray_status(
                STATUS_ERROR,
                f"Fel: {data.get('order_no', '')}"
            )

    def _on_shipment_event(self, event_type: str, data: dict):
        """Hanterar shipment-event i tkinter-tråden."""
        from datetime import datetime

        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "event": event_type,
            **data,
        }

        self.shipment_history.insert(0, entry)
        if len(self.shipment_history) > self.max_history:
            self.shipment_history = self.shipment_history[:self.max_history]

        # Uppdatera statusfönstret om det är öppet
        if self._status_window and self._status_window.winfo_exists():
            self._status_window.refresh(self.shipment_history)

    # ------------------------------------------------------------------
    # Fönster
    # ------------------------------------------------------------------

    def _show_settings(self):
        """Visar inställningsfönstret."""
        if self._settings_window and self._settings_window.winfo_exists():
            self._settings_window.lift()
            self._settings_window.focus_force()
            return

        from .settings_window import SettingsWindow
        self._settings_window = SettingsWindow(
            self.root,
            self.config,
            on_save=self._on_settings_saved,
        )

    def _show_bring_bulk(self):
        """Visar Bring Bulk-fönstret (reservera nummer, slutför pall)."""
        if self._bring_bulk_window and self._bring_bulk_window.winfo_exists():
            self._bring_bulk_window.lift()
            self._bring_bulk_window.focus_force()
            return

        from .bring_bulk_window import BringBulkWindow
        self._bring_bulk_window = BringBulkWindow(
            self.root,
            self.config,
            on_bulk_id_reserved=self._on_bulk_id_reserved,
        )

    def _get_dangerous_goods_callback(self, shipment: Shipment, filepath: Path) -> Optional[DangerousGoodsInfo]:
        """Callback för orchestrator — blockerar tills användaren fyllt i DG-dialog."""
        event = threading.Event()
        result: list = [None]

        self._queue.put({
            "action": "request_dangerous_goods",
            "order_no": shipment.order_no,
            "filepath": str(filepath),
            "event": event,
            "result": result,
        })
        event.wait(timeout=600)
        return result[0]

    def _show_dangerous_goods_dialog(
        self,
        order_no: str,
        filepath: str,
        event: threading.Event,
        result: list,
    ):
        """Visar DG-dialog (körs i tkinter-tråden)."""

        def on_confirm(dg_info: Optional[DangerousGoodsInfo], save_sidecar: bool):
            result[0] = dg_info
            event.set()

        from .dangerous_goods_dialog import DangerousGoodsDialog

        dlg = DangerousGoodsDialog(
            self.root,
            order_no=order_no,
            xml_filepath=filepath,
            on_confirm=on_confirm,
        )
        dlg.wait_window()

    def _on_bulk_id_reserved(self, new_config: dict):
        """Callback när nytt bulk-ID reserverats."""
        self.config = new_config
        if self.orchestrator and self.orchestrator.bring:
            self.orchestrator.bring._consolidated_shipment_id = (
                new_config.get("bring", {}).get("consolidated_shipment_id", "")
            )
        logger.info("Bulk-ID uppdaterat — nya paket använder det")

    def _show_status(self):
        """Visar statusfönstret."""
        if self._status_window and self._status_window.winfo_exists():
            self._status_window.lift()
            self._status_window.focus_force()
            return

        from .status_window import StatusWindow
        self._status_window = StatusWindow(
            self.root,
            self.shipment_history,
            log_dir=getattr(self, "_log_dir", None),
        )

    def _on_settings_saved(self, new_config: dict):
        """Callback när inställningar sparats."""
        logger.info("Inställningar sparade — laddar om config")

        # Uppdatera printer i orchestrator
        if self.orchestrator:
            from ..printing.printer import LabelPrinter
            printer_config = new_config.get("printers", new_config.get("printer", {}))
            self.orchestrator.printer = LabelPrinter(printer_config)

        self.config = new_config

    # ------------------------------------------------------------------
    # Config + logging
    # ------------------------------------------------------------------

    def _load_config(self):
        """Laddar config.yaml."""
        from ..utils.config import load_config, get_config_path

        self.config = load_config()
        self._config_path = get_config_path()

    def _setup_logging(self):
        """Konfigurerar logging med roterande filer."""
        import logging.handlers

        log_config = self.config.get("logging", {})
        log_dir = Path(
            log_config.get("log_dir", self.config["paths"].get("log_dir", "."))
        )
        log_dir.mkdir(parents=True, exist_ok=True)

        level = getattr(logging, log_config.get("level", "INFO").upper())
        max_bytes = log_config.get("max_file_size_mb", 10) * 1024 * 1024
        backup_count = log_config.get("backup_count", 30)

        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "garp_shipping.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)

        error_handler = logging.handlers.RotatingFileHandler(
            log_dir / "garp_shipping_errors.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)

        root = logging.getLogger()
        root.setLevel(level)
        root.addHandler(file_handler)
        root.addHandler(error_handler)

        if log_config.get("console_output", True):
            console = logging.StreamHandler()
            console.setFormatter(formatter)
            root.addHandler(console)

        self._log_dir = log_dir
