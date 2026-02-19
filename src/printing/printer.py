"""Utskriftshantering — etiketter (Zebra) och dokument (A4).

Stödjer:
- ZPL: Skickas direkt som RAW-data till skrivaren via win32print
- PDF: Skrivs ut via SumatraPDF (tyst utskrift) eller system-utskrift

Två separata skrivarköer:
- label_printer_name: Zebra-skrivare för fraktetiketter
- document_printer_name: A4-skrivare för följesedlar/fraktlistor

På macOS/Linux (utveckling): Sparar till fil istället.
"""

import logging
import platform
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class LabelPrinter:
    """Hanterar utskrift av fraktetiketter och dokument.

    Stöder två skrivare:
    - Etikettskrivare (Zebra) för fraktetiketter
    - Dokumentskrivare (A4/laser) för följesedlar, fraktlistor etc.

    Konfiguration (config dict):
        label_printer_name: str   — Windows-skrivarnamn för etiketter
        label_format: str         — "pdf" eller "zpl" (default: "pdf")
        document_printer_name: str — Windows-skrivarnamn för dokument
        document_format: str      — "pdf" (default: "pdf")

    Bakåtkompatibelt med gamla config-nycklar:
        windows_printer_name → label_printer_name
        type → label_format
    """

    def __init__(self, config: dict):
        # Stöd för både nytt och gammalt config-format
        self.label_printer = (
            config.get("label_printer_name")
            or config.get("windows_printer_name", "")
        )
        self.label_format = (
            config.get("label_format")
            or config.get("type", "pdf")
        )
        self.document_printer = config.get("document_printer_name", "")
        self.document_format = config.get("document_format", "pdf")
        self.dpi = config.get("dpi", 203)
        self.is_windows = platform.system() == "Windows"

    def print_label(self, label_data: bytes, label_format: str,
                    order_no: str) -> bool:
        """Skriver ut en etikett till etikettskrivaren (Zebra).

        Args:
            label_data: Etikettdata (PDF eller ZPL bytes).
            label_format: "pdf" eller "zpl".
            order_no: Ordernummer för loggning.

        Returns:
            True om utskriften lyckades.
        """
        if not self.label_printer:
            logger.warning(f"Ingen etikettskrivare konfigurerad, sparar till fil")
            return self._save_to_file(label_data, label_format, order_no, "label")
        return self._print(self.label_printer, label_data, label_format, order_no, "etikett")

    def print_document(self, doc_data: bytes, doc_format: str,
                       order_no: str) -> bool:
        """Skriver ut ett dokument till dokumentskrivaren (A4).

        Args:
            doc_data: Dokumentdata (PDF bytes).
            doc_format: "pdf".
            order_no: Ordernummer för loggning.

        Returns:
            True om utskriften lyckades.
        """
        if not self.document_printer:
            logger.info(f"Ingen dokumentskrivare konfigurerad, hoppar över dokument för {order_no}")
            return False
        return self._print(self.document_printer, doc_data, doc_format, order_no, "dokument")

    def _print(self, printer_name: str, data: bytes, fmt: str,
               order_no: str, doc_type: str) -> bool:
        """Generell utskriftsmetod.

        Args:
            printer_name: Windows-skrivarnamn.
            data: Data att skriva ut.
            fmt: Format ("pdf" eller "zpl").
            order_no: Ordernummer.
            doc_type: Typ för loggning ("etikett" eller "dokument").

        Returns:
            True om utskriften lyckades.
        """
        try:
            if not self.is_windows:
                return self._save_to_file(data, fmt, order_no, doc_type)

            if fmt.lower() == "zpl":
                return self._print_zpl_windows(printer_name, data, order_no, doc_type)
            elif fmt.lower() == "pdf":
                return self._print_pdf_windows(printer_name, data, order_no, doc_type)
            else:
                logger.error(f"Okänt format: {fmt}")
                return False

        except Exception as e:
            logger.error(f"Utskrift misslyckades ({doc_type}) för order {order_no}: {e}")
            return False

    def _print_zpl_windows(self, printer_name: str, zpl_data: bytes,
                           order_no: str, doc_type: str) -> bool:
        """Skickar ZPL direkt till skrivare via Windows RAW print."""
        import win32print

        hprinter = win32print.OpenPrinter(printer_name)
        try:
            hjob = win32print.StartDocPrinter(
                hprinter, 1, (f"{doc_type.title()}-{order_no}", None, "RAW")
            )
            win32print.StartPagePrinter(hprinter)
            win32print.WritePrinter(hprinter, zpl_data)
            win32print.EndPagePrinter(hprinter)
            win32print.EndDocPrinter(hprinter)
            logger.info(
                f"ZPL-{doc_type} utskriven på '{printer_name}' "
                f"för order {order_no}"
            )
            return True
        finally:
            win32print.ClosePrinter(hprinter)

    def _print_pdf_windows(self, printer_name: str, pdf_data: bytes,
                           order_no: str, doc_type: str) -> bool:
        """Skriver ut PDF via SumatraPDF (tyst utskrift)."""
        with tempfile.NamedTemporaryFile(
            suffix=".pdf", delete=False, prefix=f"{doc_type}_{order_no}_"
        ) as f:
            f.write(pdf_data)
            temp_path = f.name

        try:
            result = subprocess.run(
                [
                    "SumatraPDF.exe",
                    "-print-to", printer_name,
                    "-silent",
                    "-print-settings", "noscale",
                    temp_path,
                ],
                timeout=30,
                capture_output=True,
            )
            if result.returncode == 0:
                logger.info(
                    f"PDF-{doc_type} utskriven på '{printer_name}' "
                    f"för order {order_no}"
                )
                return True

            # Fallback: Windows system-utskrift
            import win32api
            win32api.ShellExecute(0, "print", temp_path, None, ".", 0)
            logger.info(
                f"PDF-{doc_type} skickad till '{printer_name}' "
                f"för order {order_no} (fallback)"
            )
            return True

        finally:
            Path(temp_path).unlink(missing_ok=True)

    def _save_to_file(self, data: bytes, fmt: str, order_no: str,
                      doc_type: str) -> bool:
        """Sparar utskrift till fil (utvecklingsläge på macOS/Linux)."""
        output_dir = Path(tempfile.gettempdir()) / "garp-labels"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / f"{order_no}_{doc_type}.{fmt}"
        output_path.write_bytes(data)
        logger.info(
            f"[DEV] {doc_type.title()} sparad till {output_path} "
            f"(ej utskriven — ej Windows)"
        )
        return True


def list_windows_printers() -> list[str]:
    """Hämtar lista på alla installerade Windows-skrivare.

    Returns:
        Lista med skrivarnamn. Tom lista på macOS/Linux.
    """
    if platform.system() != "Windows":
        return []

    try:
        import win32print
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        printers = win32print.EnumPrinters(flags, None, 2)
        return sorted(p["pPrinterName"] for p in printers)
    except ImportError:
        return []
    except Exception as e:
        logger.error(f"Kunde inte lista skrivare: {e}")
        return []
