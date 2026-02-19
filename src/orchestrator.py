"""Orchestrator — koordinerar hela flödet.

XML → Parsa → API-anrop → Utskrift → Mail → Flytta fil

Stöder: DHL (alla produkter), Bring (Norge — planerat)

Event-callbacks:
    on_event(event_type, data) anropas vid:
    - "shipment_ok": {"order_no", "tracking", "carrier"}
    - "shipment_error": {"order_no", "error"}
    - "file_done": {"filename"}
    - "file_error": {"filename", "error"}
"""

import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable

from .parsers.xml_parser import GarpXMLParser
from .parsers.models import Shipment, CarrierType
from .carriers.dhl import DHLClient
from .printing.printer import LabelPrinter
from .notifications.email_sender import EmailSender

logger = logging.getLogger(__name__)


class ShipmentOrchestrator:
    """Koordinerar hela flödet: XML → API → Utskrift → Mail → Flytt."""

    def __init__(self, config: dict, on_event: Optional[Callable] = None):
        """Initierar orchestrator.

        Args:
            config: Konfigurationsdict (från config.yaml).
            on_event: Callback-funktion för event-notifieringar till tray UI.
                      Signatur: on_event(event_type: str, data: dict)
        """
        self.config = config
        self.on_event = on_event
        self.parser = GarpXMLParser()

        sender = config["sender"]
        self.dhl = DHLClient(config["dhl"], sender)

        # Printer-config: stöd för nytt format (printers) och gammalt (printer)
        printer_config = config.get("printers", config.get("printer", {}))
        self.printer = LabelPrinter(printer_config)

        self.emailer = EmailSender(config["smtp"])

        self.done_dir = Path(config["paths"]["done_dir"])
        self.error_dir = Path(config["paths"]["error_dir"])
        self.label_cache = Path(config["paths"]["label_cache_dir"])

        for d in [self.done_dir, self.error_dir, self.label_cache]:
            d.mkdir(parents=True, exist_ok=True)

    def _notify(self, event_type: str, data: dict):
        """Skickar event-notifiering till tray UI (om callback finns)."""
        if self.on_event:
            try:
                self.on_event(event_type, data)
            except Exception as e:
                logger.warning(f"Event-callback fel: {e}")

    def process_file(self, filepath: Path) -> bool:
        """Bearbetar en XML-fil från GARP.

        Returns:
            True om alla sändningar behandlades utan fel.
        """
        logger.info(f"{'='*60}")
        logger.info(f"Bearbetar: {filepath.name}")
        logger.info(f"{'='*60}")

        # Kontrollera lockfil
        if not self._acquire_lock(filepath):
            logger.warning(f"Filen {filepath.name} bearbetas redan (lockfil finns)")
            return False

        all_ok = True
        try:
            shipments = self.parser.parse_file(filepath)
            logger.info(f"Parsade {len(shipments)} sändning(ar)")

            for shipment in shipments:
                try:
                    self._process_single(shipment)
                except Exception as e:
                    logger.error(
                        f"Fel vid bearbetning av order {shipment.order_no}: {e}",
                        exc_info=True,
                    )
                    self._notify("shipment_error", {
                        "order_no": shipment.order_no,
                        "error": str(e),
                    })
                    all_ok = False

            if all_ok:
                self._move_to_done(filepath)
                self._notify("file_done", {"filename": filepath.name})
            else:
                self._move_to_error(filepath, "Delvis misslyckad bearbetning")
                self._notify("file_error", {
                    "filename": filepath.name,
                    "error": "Delvis misslyckad bearbetning",
                })

        except Exception as e:
            logger.error(f"XML-parsningsfel för {filepath.name}: {e}", exc_info=True)
            self._move_to_error(filepath, str(e))
            self._notify("file_error", {
                "filename": filepath.name,
                "error": str(e),
            })
            all_ok = False

        finally:
            self._release_lock(filepath)

        return all_ok

    def _process_single(self, shipment: Shipment):
        """Bearbetar en enskild sändning genom hela kedjan."""
        carrier = shipment.service.carrier
        logger.info(
            f"Order {shipment.order_no}: "
            f"{carrier.value}:{shipment.service.product_code}"
        )

        # 1. Skapa sändning hos transportör
        if carrier == CarrierType.DHL:
            result = self.dhl.create_shipment(shipment)
            tracking = result["tracking_number"]
            shipment_id = result["shipment_id"]

            # 2. Hämta alla dokument (etikett + ev. fraktlista)
            documents = self.dhl.get_all_documents(shipment_id)
            label_data = documents["label"]
            shipment_list = documents.get("shipment_list")

            # Boka upphämtning om begärt
            booking = shipment.service.booking
            if booking and booking.pickup_booking:
                pickup_date = booking.pickup_date
                if pickup_date:
                    self.dhl.request_pickup(shipment_id, pickup_date)
                    logger.info(f"  Upphämtning bokad: {pickup_date}")

        else:
            raise ValueError(
                f"Transportör '{carrier.value}' stöds inte ännu. "
                f"Stödda: DHL"
            )

        # 3. Spara etikett på disk (backup)
        label_path = self.label_cache / f"{shipment.order_no}.pdf"
        label_path.write_bytes(label_data)
        logger.info(f"  Etikett sparad: {label_path}")

        # 4. Skriv ut etikett (→ Zebra)
        printed = self.printer.print_label(label_data, "pdf", shipment.order_no)
        if not printed:
            logger.warning(f"  Etikett-utskrift misslyckades — etiketten finns sparad på disk")

        # 5. Skriv ut fraktlista (→ A4) om den finns
        if shipment_list:
            list_path = self.label_cache / f"{shipment.order_no}_shipmentlist.pdf"
            list_path.write_bytes(shipment_list)
            doc_printed = self.printer.print_document(shipment_list, "pdf", shipment.order_no)
            if doc_printed:
                logger.info(f"  Fraktlista utskriven för order {shipment.order_no}")
            else:
                logger.info(f"  Fraktlista sparad: {list_path} (ej utskriven)")

        # 6. Skicka kundmail (om e-post finns och enot-notifiering är aktiv)
        has_enot = any(n.opt_id == "enot" for n in shipment.notifications)
        if shipment.receiver and shipment.receiver.email and has_enot:
            custom_msg = next(
                (n.message for n in shipment.notifications if n.opt_id == "enot"),
                "",
            )
            self.emailer.send_tracking_email(
                to_email=shipment.receiver.email,
                order_no=shipment.order_no,
                tracking_number=tracking,
                carrier=carrier,
                custom_message=custom_msg,
            )

        logger.info(f"  KLAR: Order {shipment.order_no}, tracking: {tracking}")

        # Notifiera tray UI
        self._notify("shipment_ok", {
            "order_no": shipment.order_no,
            "tracking": tracking,
            "carrier": carrier.value,
        })

    def _acquire_lock(self, filepath: Path) -> bool:
        """Skapar lockfil för att förhindra dubbelbearbetning."""
        lock_path = filepath.with_suffix(".lock")
        try:
            lock_path.open("x").close()
            return True
        except FileExistsError:
            # Rensa gamla locks (äldre än 5 minuter)
            if lock_path.exists():
                age = datetime.now().timestamp() - lock_path.stat().st_mtime
                if age > 300:
                    lock_path.unlink()
                    lock_path.open("x").close()
                    logger.warning(f"Tog bort gammal lockfil för {filepath.name}")
                    return True
            return False

    def _release_lock(self, filepath: Path):
        lock_path = filepath.with_suffix(".lock")
        lock_path.unlink(missing_ok=True)

    def _move_to_done(self, filepath: Path):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = self.done_dir / f"{ts}_{filepath.name}"
        shutil.move(str(filepath), str(dest))
        logger.info(f"  Flyttad till Done: {dest.name}")

    def _move_to_error(self, filepath: Path, reason: str):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = self.error_dir / f"{ts}_{filepath.name}"
        shutil.move(str(filepath), str(dest))

        error_log = dest.with_suffix(".error.txt")
        error_log.write_text(
            f"Tid: {ts}\nFil: {filepath.name}\nFel: {reason}\n",
            encoding="utf-8",
        )
        logger.error(f"  Flyttad till Error: {dest.name} — {reason}")
