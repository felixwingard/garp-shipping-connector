"""TrayApp — system tray-app med pystray + tkinter.

Arkitektur med 3 trådar:
1. Huvudtråd: tkinter mainloop (hanterar alla fönster)
2. Daemon-tråd 1: pystray (tray-ikon + högerklicksmeny)
3. Daemon-tråd 2: service (watcher + orchestrator)

Kommunikation: pystray → queue → tkinter (trådsäkert)
"""

import sys
import time
import queue
import logging
import threading
import tkinter as tk
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

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
        self.status = STATUS_IDLE

        # Queue för trådsäker kommunikation: pystray/service → tkinter
        self._queue: queue.Queue = queue.Queue()

        # Tray-ikonen
        self._icon = None
        self._icon_images = {}

        # Fönster-instanser (skapas vid behov)
        self._settings_window = None
        self._status_window = None

        # Shipment-historik för statusfönstret
        self.shipment_history: list[dict] = []
        self.max_history = 50

    def run(self):
        """Startar appen — blockerar tills avslut.

        1. Laddar config
        2. Sätter upp logging
        3. Skapar tkinter root (withdrawn)
        4. Startar pystray i daemon-tråd
        5. Startar service i daemon-tråd
        6. Kör tkinter mainloop
        """
        # 1. Ladda config + logging
        self._load_config()
        self._setup_logging()

        logger.info("GARP Shipping Connector startar (tray-läge)")

        # 2. Skapa tkinter root (dold — aldrig synlig)
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("GARP Shipping Connector")

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

        # Stoppa tray-ikon
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

        # Stäng tkinter
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass

        logger.info("Avslutad")

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
        elif action == "quit":
            self.quit()
        elif action == "shipment_event":
            self._on_shipment_event(msg.get("event_type"), msg.get("data", {}))

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
                "Inställningar...",
                lambda icon, item: self._queue.put({"action": "show_settings"}),
            ),
            pystray.MenuItem(
                "Status / Historik",
                lambda icon, item: self._queue.put({"action": "show_status"}),
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
        import os
        import re
        import yaml

        if getattr(sys, 'frozen', False):
            exe_dir = Path(sys.executable).parent
        else:
            exe_dir = Path(__file__).parent.parent.parent

        config_path = exe_dir / "config" / "config.yaml"

        if not config_path.exists():
            # Prova exempelfilen
            example = config_path.with_name("config.example.yaml")
            if example.exists():
                import shutil
                shutil.copy(str(example), str(config_path))
                logger.info(f"Skapade config.yaml från exempelfil")
            else:
                raise FileNotFoundError(
                    f"Konfigurationsfil saknas: {config_path}\n"
                    f"Kopiera config.example.yaml till config.yaml"
                )

        with open(config_path, "r", encoding="utf-8") as f:
            raw = f.read()

        def replace_env(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))

        resolved = re.sub(r'\$\{(\w+)\}', replace_env, raw)
        self.config = yaml.safe_load(resolved)
        self._config_path = config_path

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
