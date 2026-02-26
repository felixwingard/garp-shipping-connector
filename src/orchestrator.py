"""Orchestrator — koordinerar hela flödet.

XML → Parsa → API-anrop → Utskrift → Mail → Flytta fil

Stöder: DHL (Sverige), Bring (Norge)

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
from typing import Optional, Callable, List, Set, Tuple

from .parsers.xml_parser import GarpXMLParser
from .parsers.models import Shipment, CarrierType
from .carriers.dhl import DHLClient
from .carriers.bring import BringClient
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
        self.skip_email = config.get("skip_email", False)
        self.parser = GarpXMLParser()

        sender = config["sender"]
        self.dhl = DHLClient(config["dhl"], sender)
        bring_cfg = config.get("bring")
        self.bring = BringClient(bring_cfg, sender) if bring_cfg else None

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
                    self._process_single(shipment, xml_filepath=filepath)
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
                self._move_to_done(filepath, shipments)
                self._notify("file_done", {"filename": filepath.name})
            else:
                self._move_to_error(filepath, "Delvis misslyckad bearbetning", shipments)
                self._notify("file_error", {
                    "filename": filepath.name,
                    "error": "Delvis misslyckad bearbetning",
                })

        except Exception as e:
            logger.error(f"XML-parsningsfel för {filepath.name}: {e}", exc_info=True)
            self._move_to_error(filepath, str(e), [])
            self._notify("file_error", {
                "filename": filepath.name,
                "error": str(e),
            })
            all_ok = False

        finally:
            self._release_lock(filepath)

        return all_ok

    def _process_single(self, shipment: Shipment, xml_filepath: Optional[Path] = None):
        """Bearbetar en enskild sändning genom hela kedjan.

        xml_filepath: Sökväg till XML-filen — används för att hitta
                      GARP-följesedel PDF i samma mapp ({order_no}.pdf).
        """
        if not shipment.receiver:
            raise ValueError(
                f"Order {shipment.order_no} saknar mottagarinfo. "
                "Lägg till receiver i XML."
            )
        if not shipment.service:
            raise ValueError(
                f"Order {shipment.order_no} saknar service/srvid. "
                "Ange t.ex. DHL:102 i XML."
            )
        carrier = shipment.service.carrier
        logger.info(
            f"Order {shipment.order_no}: "
            f"{carrier.value}:{shipment.service.product_code}"
        )

        # 1. Skapa sändning hos transportör
        shipment_id = ""
        if carrier == CarrierType.DHL:
            if shipment.service.product_code == "104":
                raise ValueError(
                    "DHL:104 (ServicePoint C2B retur) stöds inte. "
                    "Använd DHL:102 eller DHL:103."
                )
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
                    pickup_instruction = shipment.delivery_instruction or ""
                    self.dhl.request_pickup(
                        shipment_id,
                        pickup_date,
                        pickup_instruction=pickup_instruction,
                    )
                    logger.info(f"  Upphämtning bokad: {pickup_date}")

        elif carrier == CarrierType.BRING:
            if not self.bring:
                raise ValueError(
                    "Bring är vald men ingen bring-konfiguration finns i config.yaml"
                )
            result = self.bring.create_shipment(shipment)
            tracking = result["tracking_number"]
            label_data = result["label_data"]
            shipment_list = None

        else:
            raise ValueError(
                f"Transportör '{carrier.value}' stöds inte ännu. "
                f"Stödda: DHL, Bring"
            )

        # 3. Skriv ut etikett (→ Zebra)
        printed = self.printer.print_label(label_data, "pdf", shipment.order_no)
        if not printed:
            logger.warning(f"  Etikett-utskrift misslyckades för {shipment.order_no}")

        # 4. Skriv ut fraktlista/CMR (→ A4) om den finns + produkt kräver utskrift (t.ex. pall)
        # print_document_for_products: [202, 210, 205] = endast pall etc. [] = aldrig. Saknas = alltid.
        if shipment_list:
            prod_codes = self.config.get("printers", {}).get("print_document_for_products")
            if prod_codes is None:
                do_print = True  # Nyckel saknas = bakåtkompatibelt
            elif isinstance(prod_codes, list):
                do_print = (
                    bool(prod_codes)
                    and shipment.service
                    and str(shipment.service.product_code) in [str(p) for p in prod_codes]
                )
            else:
                do_print = True
            if do_print:
                doc_printed = self.printer.print_document(shipment_list, "pdf", shipment.order_no)
                if doc_printed:
                    logger.info(f"  Fraktlista/CMR utskriven för order {shipment.order_no}")
                else:
                    logger.warning(f"  Fraktlista utskrift misslyckades för {shipment.order_no}")
            else:
                pc = getattr(shipment.service, "product_code", "") if shipment.service else ""
                logger.debug(f"  Dokument utskrivs ej för produkt {pc} (endast mail)")

        # 5. Estimerat leveransdatum (DHL TimeTable API)
        estimated_delivery = ""
        if carrier == CarrierType.DHL:
            try:
                estimated_delivery = (
                    self.dhl.get_estimated_delivery_date(shipment) or ""
                )
            except Exception as e:
                logger.debug(f"  Kunde inte hämta leveransdatum: {e}")

        # 6. Skicka kundmail (om e-post finns och enot-notifiering är aktiv)
        has_enot = any(n.opt_id == "enot" for n in shipment.notifications)
        if not self.skip_email and shipment.receiver and shipment.receiver.email and has_enot:
            # Bilagor: DHL fraktlista + GARP följesedel (om PDF finns i samma mapp som XML)
            attachments: List[Tuple[str, bytes]] = []
            if shipment_list:
                attachments.append((f"Fraktlista_{shipment.order_no}.pdf", shipment_list))
            if xml_filepath:
                # GARP kan exportera följesedel som {order_no}.pdf eller {xml-namn}.pdf
                for candidate in [
                    xml_filepath.parent / f"{shipment.order_no}.pdf",
                    xml_filepath.parent / f"{xml_filepath.stem}.pdf",
                ]:
                    if candidate.exists():
                        attachments.append(
                            (f"Följesedel_{shipment.order_no}.pdf", candidate.read_bytes())
                        )
                        logger.info(f"  GARP-följesedel bifogas: {candidate.name}")
                        break
            self.emailer.send_tracking_email(
                to_email=shipment.receiver.email,
                order_no=shipment.order_no,
                tracking_number=tracking,
                carrier=carrier,
                product_code=shipment.service.product_code if shipment.service else "",
                dhl_hamta_id=shipment_id if carrier == CarrierType.DHL else "",
                custom_message="",
                attachments=attachments if attachments else None,
                receiver_country=(shipment.receiver.country or "").strip().upper(),
                estimated_delivery_date=estimated_delivery,
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
                    try:
                        lock_path.open("x").close()
                        logger.warning(f"Tog bort gammal lockfil för {filepath.name}")
                        return True
                    except FileExistsError:
                        # Annan process tog locken — ge upp
                        return False
            return False

    def _release_lock(self, filepath: Path):
        lock_path = filepath.with_suffix(".lock")
        lock_path.unlink(missing_ok=True)

    def _move_to_done(self, filepath: Path, shipments: list):
        """Tar bort XML + följesedlar — allt utskrivet/klart, behövs ej längre."""
        parent = filepath.parent
        xml_stem = filepath.stem

        # Ta bort följesedlar (bifogade mailet)
        pdfs_to_remove: Set[Path] = set()
        for s in shipments:
            candidate = parent / f"{s.order_no}.pdf"
            if candidate.exists():
                pdfs_to_remove.add(candidate)
        stem_pdf = parent / f"{xml_stem}.pdf"
        if stem_pdf.exists():
            pdfs_to_remove.add(stem_pdf)
        for pdf_path in pdfs_to_remove:
            pdf_path.unlink(missing_ok=True)
            logger.info(f"  Följesedel borttagen: {pdf_path.name}")

        # Ta bort XML
        filepath.unlink(missing_ok=True)
        logger.info(f"  XML borttagen: {filepath.name}")

    def _move_to_error(self, filepath: Path, reason: str, shipments: list):
        """Flyttar XML + tillhörande följesedel-PDF:er till error_dir."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        parent = filepath.parent
        xml_stem = filepath.stem

        # Sök följesedlar
        pdfs_to_move: Set[Path] = set()
        for s in shipments:
            candidate = parent / f"{s.order_no}.pdf"
            if candidate.exists():
                pdfs_to_move.add(candidate)
        stem_pdf = parent / f"{xml_stem}.pdf"
        if stem_pdf.exists():
            pdfs_to_move.add(stem_pdf)

        # Flytta XML
        dest = self.error_dir / f"{ts}_{filepath.name}"
        shutil.move(str(filepath), str(dest))

        error_log = dest.with_suffix(".error.txt")
        error_log.write_text(
            f"Tid: {ts}\nFil: {filepath.name}\nFel: {reason}\n",
            encoding="utf-8",
        )
        logger.error(f"  Flyttad till Error: {dest.name} — {reason}")

        # Flytta följesedlar
        for pdf_path in pdfs_to_move:
            dest_pdf = self.error_dir / f"{ts}_{pdf_path.name}"
            shutil.move(str(pdf_path), str(dest_pdf))
            logger.info(f"  Följesedel flyttad till Error: {dest_pdf.name}")
