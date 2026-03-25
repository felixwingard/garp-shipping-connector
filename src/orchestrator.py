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

import json
import shutil
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, List, Set, Tuple

from .parsers.xml_parser import GarpXMLParser
from .parsers.models import Shipment, CarrierType, DangerousGoodsInfo
from .carriers.dhl import DHLClient
from .carriers.bring import BringClient
from .printing.printer import LabelPrinter
from .notifications.email_sender import EmailSender

logger = logging.getLogger(__name__)


class ShipmentOrchestrator:
    """Koordinerar hela flödet: XML → API → Utskrift → Mail → Flytt."""

    def __init__(
        self,
        config: dict,
        on_event: Optional[Callable] = None,
        get_dangerous_goods: Optional[Callable[["Shipment", Path], Optional[DangerousGoodsInfo]]] = None,
    ):
        """Initierar orchestrator.

        Args:
            config: Konfigurationsdict (från config.yaml).
            on_event: Callback-funktion för event-notifieringar till tray UI.
                      Signatur: on_event(event_type: str, data: dict)
            get_dangerous_goods: Callback för att hämta DG-data via UI-dialog när
                                sidecar saknas (endast DHL full ADR).
                                Signatur: (shipment, filepath) -> DangerousGoodsInfo | None
        """
        self.config = config
        self.on_event = on_event
        self.get_dangerous_goods = get_dangerous_goods
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

    def _extract_error_message(self, e: Exception) -> str:
        """Extraherar läsbart felmeddelande från API-svar (t.ex. DHL validationErrors)."""
        msg = str(e)
        resp = getattr(e, "response", None)
        if resp is not None:
            try:
                body = resp.json()
                vals = body.get("validationErrors", [])
                if vals and isinstance(vals, list):
                    first = vals[0]
                    if isinstance(first, dict):
                        m = first.get("message", msg)
                        if m:
                            return m
                m = body.get("UserMessage") or body.get("Message")
                if m:
                    return m
            except Exception:
                pass
        return msg

    def _has_dg_addon(self, shipment: Shipment) -> bool:
        """Kontrollerar om sändningen har farligt gods-addon (DG, LQ, DANGER)."""
        addon = (shipment.service.addon or "").strip().upper().replace(",", ":")
        parts = {p.strip() for p in addon.split(":") if p.strip()}
        return bool(parts & {"DG", "LQ", "DANGER"})

    def _load_dangerous_goods_sidecar(self, xml_filepath: Path) -> Optional[DangerousGoodsInfo]:
        """Laddar DG-data från sidecar-fil {xml_stem}_dg.json om den finns."""
        stem = xml_filepath.stem
        dg_path = xml_filepath.parent / f"{stem}_dg.json"
        if not dg_path.exists():
            return None
        try:
            data = json.loads(dg_path.read_text(encoding="utf-8"))
            return DangerousGoodsInfo(
                un_number=str(data.get("unNumber", "")).strip(),
                adr_class=str(data.get("adrClass", "")).strip(),
                packing_group=str(data.get("packingGroup", "")).strip().upper(),
                proper_shipping_name=str(data.get("properShippingName", "")).strip(),
                technical_name=str(data.get("technicalName", "")).strip(),
                flash_point=str(data.get("flashPoint", "")).strip(),
                tunnel_code=str(data.get("tunnelCode", "")).strip(),
                quantity=str(data.get("quantity", "")).strip(),
            )
        except Exception as e:
            logger.warning(f"Kunde inte ladda {dg_path.name}: {e}")
            return None

    def process_file(self, filepath: Path) -> bool:
        """Bearbetar en XML-fil från GARP.

        Returns:
            True om alla sändningar behandlades utan fel.
        """
        logger.info(f"{'='*60}")
        logger.info(f"Bearbetar: {filepath.name}")
        logger.info(f"{'='*60}")
        try:
            raw_preview = filepath.read_text(encoding="iso-8859-1", errors="replace")[:500]
            logger.debug(f"Filinnehåll (preview): {raw_preview}")
        except Exception:
            pass

        # Kontrollera lockfil
        if not self._acquire_lock(filepath):
            logger.warning(f"Filen {filepath.name} bearbetas redan (lockfil finns)")
            return False

        all_ok = True
        try:
            shipments = self.parser.parse_file(filepath)
            logger.info(f"Parsade {len(shipments)} sändning(ar)")

            if not shipments:
                logger.warning(
                    f"Inga sändningar hittades i {filepath.name}. "
                    "Kontrollera att XML:en innehåller <shipment>-element."
                )
                self._notify("file_error", {
                    "filename": filepath.name,
                    "error": "Inga sändningar i filen",
                })

            # Avsändare är alltid från config (Ernst P AB) — ignorerar XML:s "from"
            config_sender = self.config.get("sender", {}).get("name", "")
            if config_sender:
                for s in shipments:
                    s.sender_name = config_sender

            for shipment in shipments:
                # Farligt gods: Bring = endast LQ (0003)
                # DHL Paket (102, 103) stöder inte farligt gods — enligt DHL Produktmanual v5.23
                if self._has_dg_addon(shipment) and shipment.service and shipment.service.carrier == CarrierType.DHL:
                    pc = shipment.service.product_code or ""
                    if pc in ("102", "103"):
                        raise ValueError(
                            f"Order {shipment.order_no}: DHL Paket (102/103) stöder inte farligt gods. "
                            "Farligt gods kräver pall-/frakttjänst (t.ex. DHL Euroconnect). Kontakta DHL."
                        )
                    dg_info = self._load_dangerous_goods_sidecar(filepath)
                    if dg_info and dg_info.un_number:
                        shipment.dangerous_goods = dg_info
                        logger.info(f"  Farligt gods: UN {dg_info.un_number}, klass {dg_info.adr_class}")
                    elif self.get_dangerous_goods:
                        dg_info = self.get_dangerous_goods(shipment, filepath)
                        if dg_info and dg_info.un_number:
                            shipment.dangerous_goods = dg_info
                            logger.info(f"  Farligt gods (dialog): UN {dg_info.un_number}")
                        else:
                            raise ValueError(
                                f"Order {shipment.order_no}: Farligt gods kräver UN-nummer. "
                                "Ange i dialog eller skapa sidecar-fil (_dg.json)."
                            )
                    else:
                        raise ValueError(
                            f"Order {shipment.order_no}: Farligt gods kräver sidecar-fil (_dg.json) "
                            "med UN-nummer och ADR-data. Se docs/DANGEROUS_GOODS.md."
                        )

            for shipment in shipments:
                try:
                    self._process_single(shipment, xml_filepath=filepath)
                except Exception as e:
                    logger.error(
                        f"Fel vid bearbetning av order {shipment.order_no}: {e}",
                        exc_info=True,
                    )
                    error_msg = self._extract_error_message(e)
                    self._notify("shipment_error", {
                        "order_no": shipment.order_no,
                        "error": error_msg,
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

            # Räkna kolli + totalvikt för bulk (0332/0342) — lägg till vid lyckad bokning
            prod = shipment.service.product_code.upper() if shipment.service else ""
            if prod in ("0332", "0342", "BUSINESS_PARCEL_BULK", "PICKUP_PARCEL_BULK"):
                kolli = sum(c.copies for c in shipment.containers) if shipment.containers else 1
                weight_kg = sum(c.weight or 0 for c in shipment.containers) if shipment.containers else 0
                bulk_id = (self.config.get("bring") or {}).get("consolidated_shipment_id", "").strip()
                try:
                    from .utils.config import increment_bring_bulk_count, increment_bring_bulk_weight
                    increment_bring_bulk_count(self.config, kolli)
                    if weight_kg > 0:
                        increment_bring_bulk_weight(self.config, weight_kg)
                    if bulk_id:
                        from .utils.bulk_export import append_bring_bulk_order
                        rec = shipment.receiver
                        append_bring_bulk_order(
                            bulk_id,
                            shipment.order_no,
                            tracking,
                            weight_kg,
                            kolli,
                            receiver_name=rec.name if rec else "",
                            receiver_address=((rec.address1 or "") + (" " + rec.address2 if rec and rec.address2 else "")).strip() if rec else "",
                            receiver_zipcode=rec.zipcode if rec else "",
                            receiver_city=rec.city if rec else "",
                            receiver_country=rec.country if rec else "",
                        )
                except Exception as e:
                    logger.warning(f"Kunde inte uppdatera bulk räknare: {e}")

        else:
            raise ValueError(
                f"Transportör '{carrier.value}' stöds inte ännu. "
                f"Stödda: DHL, Bring"
            )

        # 3. Spara alla dokument till label_cache (för omskrivning)
        try:
            cache_path = self.label_cache / f"{shipment.order_no}_etikett.pdf"
            cache_path.write_bytes(label_data)
        except Exception as e:
            logger.debug(f"  Kunde inte spara etikett till cache: {e}")

        # 3b. Skriv ut etikett (→ Zebra)
        printed = self.printer.print_label(label_data, "pdf", shipment.order_no)
        print_failed = False
        if not printed:
            print_failed = True
            logger.warning(f"  Etikett-utskrift misslyckades för {shipment.order_no}")

        # 4. Skriv ut fraktlista/CMR (→ A4) om den finns + produkt kräver utskrift (t.ex. pall)
        # print_document_for_products: [202, 210, 205] = endast pall etc. [] = aldrig. Saknas = alltid.
        if shipment_list:
            try:
                (self.label_cache / f"{shipment.order_no}_fraktlista.pdf").write_bytes(shipment_list)
            except Exception:
                pass
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

        # 4b. ADR-godsdeklaration för farligt gods (DHL freight 210/211/202/205)
        dg = getattr(shipment, "dangerous_goods", None)
        if (
            dg
            and dg.un_number
            and carrier == CarrierType.DHL
            and shipment.service
            and str(shipment.service.product_code) in ("210", "211", "202", "205")
        ):
            print_dg = self.config.get("printers", {}).get("print_dg_declaration", True)
            if print_dg:
                try:
                    from .printing.dg_declaration import generate_adr_declaration

                    dg_pdf = generate_adr_declaration(
                        shipment, dg, self.config["sender"]
                    )
                    try:
                        (self.label_cache / f"{shipment.order_no}_ADR.pdf").write_bytes(dg_pdf)
                    except Exception:
                        pass
                    dg_printed = self.printer.print_document(
                        dg_pdf, "pdf", f"{shipment.order_no}_ADR"
                    )
                    if dg_printed:
                        logger.info(f"  ADR-deklaration utskriven för order {shipment.order_no}")
                    else:
                        logger.warning(f"  ADR-deklaration utskrift misslyckades för {shipment.order_no}")
                except Exception as e:
                    logger.warning(f"  Kunde inte generera ADR-deklaration: {e}")

        # 5. Estimerat leveransdatum (DHL TimeTable API)
        estimated_delivery = ""
        estimated_price = ""
        if carrier == CarrierType.DHL:
            try:
                estimated_delivery = (
                    self.dhl.get_estimated_delivery_date(shipment) or ""
                )
            except Exception as e:
                logger.debug(f"  Kunde inte hämta leveransdatum: {e}")

            # 5b. Uppskattat pris via PriceQuote (exkl. moms — TotalPrice)
            if self.config.get("dhl", {}).get("fetch_price_after_shipment", True):
                try:
                    quote = self.dhl.get_price_quote(shipment, use_gross=False)
                    items = quote.get("priceQuoteResult", [])
                    if isinstance(items, list):
                        total = next((r for r in items if r.get("id") == "TotalPrice"), {})
                        val = total.get("value", "")
                        unit = total.get("unit", "SEK")
                        if val:
                            estimated_price = f"{val} {unit}"
                            logger.info(f"  Uppskattat pris (exkl. moms): {estimated_price}")
                except Exception as e:
                    logger.debug(f"  Kunde inte hämta pris: {e}")
        elif carrier == CarrierType.BRING and self.bring:
            if self.config.get("bring", {}).get("fetch_price_after_shipment", True):
                try:
                    quote = self.bring.get_price_quote(shipment)
                    amt = quote.get("amountWithoutVAT")
                    curr = quote.get("currency", "SEK")
                    if amt:
                        estimated_price = f"{amt} {curr}"
                        logger.info(f"  Uppskattat pris (exkl. moms): {estimated_price}")
                except Exception as e:
                    logger.debug(f"  Kunde inte hämta Bring-pris: {e}")

        # 5c. Sök GARP-följesedel (för utskrift och/eller bifogande i mail)
        has_enot = any(n.opt_id == "enot" for n in shipment.notifications)
        sending_email = not self.skip_email and shipment.receiver and shipment.receiver.email and has_enot
        waybill_data = self._find_waybill(shipment, xml_filepath) if xml_filepath else None
        if waybill_data:
            waybill_printed = self.printer.print_document(
                waybill_data, "pdf", f"{shipment.order_no}_följesedel"
            )
            if waybill_printed:
                logger.info(f"  Följesedel utskriven för order {shipment.order_no}")
            else:
                logger.warning(f"  Följesedel utskrift misslyckades för {shipment.order_no}")

        # 6. Skicka kundmail (om e-post finns och enot-notifiering är aktiv)
        if sending_email:
            # Bilagor: DHL fraktlista + GARP följesedel (båda måste bifogas)
            attachments: List[Tuple[str, bytes]] = []
            if shipment_list:
                attachments.append((f"Fraktlista_{shipment.order_no}.pdf", shipment_list))
            if waybill_data:
                attachments.append((f"Följesedel_{shipment.order_no}.pdf", waybill_data))
                logger.info(f"  Följesedel bifogas till kundmail för {shipment.order_no}")
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

        # Sändningslogg (Excel)
        try:
            from .utils.shipment_log import append_shipment
            rec = shipment.receiver
            container = shipment.containers[0] if shipment.containers else None
            append_shipment(
                order_no=shipment.order_no,
                tracking=tracking,
                carrier=carrier.value,
                product_code=shipment.service.product_code if shipment.service else "",
                receiver_name=rec.name if rec else "",
                receiver_address=((rec.address1 or "") + (" " + rec.address2 if rec and rec.address2 else "")).strip() if rec else "",
                receiver_zipcode=rec.zipcode if rec else "",
                receiver_city=rec.city if rec else "",
                receiver_country=rec.country if rec else "",
                receiver_email=rec.email if rec else "",
                receiver_phone=rec.phone if rec else "",
                weight_kg=sum(c.weight or 0 for c in shipment.containers) if shipment.containers else 0,
                copies=sum(c.copies for c in shipment.containers) if shipment.containers else 1,
                estimated_price=estimated_price,
            )
        except Exception as e:
            logger.debug(f"Sändningslogg: {e}")

        # Notifiera tray UI
        event_data = {
            "order_no": shipment.order_no,
            "tracking": tracking,
            "carrier": carrier.value,
        }
        if estimated_price:
            event_data["estimated_price"] = estimated_price
        if print_failed:
            event_data["print_failed"] = True
        self._notify("shipment_ok", event_data)

    def _find_waybill(self, shipment: "Shipment", xml_filepath: Optional[Path]) -> Optional[bytes]:
        """Hittar GARP-följesedel i samma mapp som XML. Returnerar bytes eller None."""
        if not xml_filepath:
            return None
        parent = xml_filepath.parent
        order_base = shipment.order_no.split("-")[0] if shipment.order_no else ""
        candidates = [
            parent / f"{shipment.order_no}.pdf",
            parent / f"{shipment.order_no}.PDF",
            parent / f"{shipment.order_no}.fil",
            parent / shipment.order_no,
            parent / f"{order_base}.pdf",
            parent / f"{order_base}.PDF",
            parent / f"{order_base}.fil",
            parent / order_base,
            parent / f"{xml_filepath.stem}.pdf",
            parent / f"{xml_filepath.stem}.fil",
            parent / xml_filepath.stem,
        ]

        def _try_find() -> Optional[bytes]:
            for c in candidates:
                if c.exists() and c.is_file():
                    data = c.read_bytes()
                    is_pdf = data[:4] == b"%PDF"
                    is_fil = c.suffix.lower() == ".fil"
                    is_ext = c.suffix == "" and c.stem in (shipment.order_no, order_base, xml_filepath.stem)
                    if is_pdf or is_fil or is_ext:
                        return data
            for f in parent.iterdir():
                if not f.is_file() or f.suffix.lower() in (".xml", ".txt"):
                    continue
                if f.suffix.lower() not in ("", ".pdf", ".fil"):
                    continue
                stem = f.stem
                if (shipment.order_no in stem or stem in shipment.order_no or
                        order_base in stem or xml_filepath.stem in stem or stem in xml_filepath.stem):
                    data = f.read_bytes()
                    if data[:4] == b"%PDF" or f.suffix.lower() == ".fil" or f.suffix == "":
                        return data
            return None

        data = _try_find()
        if data:
            return data
        time.sleep(3)
        return _try_find()

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

        # Ta bort följesedlar (bifogade mailet) — även .fil (GARP sparar inte alltid som PDF)
        pdfs_to_remove: Set[Path] = set()
        def _is_waybill(p: Path) -> bool:
            if not p.exists() or not p.is_file():
                return False
            data = p.read_bytes()
            # PDF, .fil, eller extensionless (t.ex. "133349" utan ändelse)
            return data[:4] == b"%PDF" or p.suffix.lower() == ".fil" or p.suffix == ""
        for s in shipments:
            order_base = s.order_no.split("-")[0] if s.order_no else ""
            for c in [
                parent / f"{s.order_no}.pdf", parent / f"{s.order_no}.PDF",
                parent / f"{s.order_no}.fil", parent / s.order_no,
                parent / f"{order_base}.pdf", parent / f"{order_base}.fil", parent / order_base,
            ]:
                if _is_waybill(c):
                    pdfs_to_remove.add(c)
                    break
        for c in [parent / f"{xml_stem}.pdf", parent / f"{xml_stem}.fil", parent / xml_stem]:
            if _is_waybill(c):
                pdfs_to_remove.add(c)
                break
        # Fallback: ta bort .fil/.pdf som innehåller order_no, order_base eller xml_stem i filnamnet
        for s in shipments:
            ob = s.order_no.split("-")[0] if s.order_no else ""
            for f in parent.iterdir():
                if not f.is_file():
                    continue
                if f.suffix.lower() in (".xml", ".txt"):
                    continue
                if f.suffix.lower() not in ("", ".pdf", ".fil"):
                    continue
                stem = f.stem
                if s.order_no in stem or stem in s.order_no or ob in stem or xml_stem in stem or stem in xml_stem:
                    if _is_waybill(f):
                        pdfs_to_remove.add(f)
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

        # Sök följesedlar — även .fil (GARP sparar inte alltid som PDF)
        def _is_waybill(p: Path) -> bool:
            if not p.exists() or not p.is_file():
                return False
            data = p.read_bytes()
            return data[:4] == b"%PDF" or p.suffix.lower() == ".fil" or p.suffix == ""
        pdfs_to_move: Set[Path] = set()
        for s in shipments:
            order_base = s.order_no.split("-")[0] if s.order_no else ""
            for c in [
                parent / f"{s.order_no}.pdf", parent / f"{s.order_no}.PDF",
                parent / f"{s.order_no}.fil", parent / s.order_no,
                parent / f"{order_base}.pdf", parent / f"{order_base}.fil", parent / order_base,
            ]:
                if _is_waybill(c):
                    pdfs_to_move.add(c)
                    break
        for c in [parent / f"{xml_stem}.pdf", parent / f"{xml_stem}.fil", parent / xml_stem]:
            if _is_waybill(c):
                pdfs_to_move.add(c)
                break
        # Fallback: flytta .fil/.pdf som innehåller order_no, order_base eller xml_stem i filnamnet
        for s in shipments:
            ob = s.order_no.split("-")[0] if s.order_no else ""
            for f in parent.iterdir():
                if not f.is_file():
                    continue
                if f.suffix.lower() in (".xml", ".txt"):
                    continue
                if f.suffix.lower() not in ("", ".pdf", ".fil"):
                    continue
                stem = f.stem
                if s.order_no in stem or stem in s.order_no or ob in stem or xml_stem in stem or stem in xml_stem:
                    if _is_waybill(f):
                        pdfs_to_move.add(f)

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
