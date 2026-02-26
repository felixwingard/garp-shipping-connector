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
        self._sumatra_exe = (config.get("sumatra_exe") or "").strip()

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

    def _find_sumatra(self) -> str:
        """Hittar SumatraPDF.exe — config, projektmapp, subfoldrar, cwd, rekursiv sökning."""
        import os
        # 1. Explicit sökväg i config
        if self._sumatra_exe:
            p = Path(self._sumatra_exe)
            if p.is_file():
                return str(p)
        search_roots = []
        try:
            proj = Path(__file__).resolve().parent.parent.parent
            search_roots.append(proj)
        except Exception:
            pass
        cwd = Path(os.getcwd())
        if cwd not in search_roots:
            search_roots.append(cwd)
        for root in search_roots:
            # Direkt i root — olika namn: SumatraPDF.exe, SumatraPDF-3.5.2-64.exe
            for name in ("SumatraPDF.exe", "SumatraPDF-3.5.2-64.exe"):
                direct = root / name
                if direct.is_file():
                    return str(direct)
            # Glob: alla SumatraPDF*.exe i root
            for exe in root.glob("SumatraPDF*.exe"):
                if exe.is_file():
                    return str(exe)
            # Vanliga unpack-mappar
            for subname in ("SumatraPDF-3.5.2-64", "SumatraPDF-3.5.2", "SumatraPDF-*"):
                if "*" in subname:
                    for sub in root.glob(subname):
                        if sub.is_dir():
                            exe = sub / "SumatraPDF.exe"
                            if exe.is_file():
                                return str(exe)
                else:
                    exe = root / subname / "SumatraPDF.exe"
                    if exe.is_file():
                        return str(exe)
            # Rekursiv sökning (max 2 nivåer ned)
            for sub in root.iterdir():
                if sub.is_dir() and "SumatraPDF" in sub.name:
                    exe = sub / "SumatraPDF.exe"
                    if exe.is_file():
                        return str(exe)
        return "SumatraPDF.exe"  # Fallback till PATH

    def _print_pdf_windows(self, printer_name: str, pdf_data: bytes,
                           order_no: str, doc_type: str) -> bool:
        """Skriver ut PDF via SumatraPDF (tyst utskrift)."""
        with tempfile.NamedTemporaryFile(
            suffix=".pdf", delete=False, prefix=f"{doc_type}_{order_no}_"
        ) as f:
            f.write(pdf_data)
            temp_path = f.name

        sumatra = self._find_sumatra()
        logger.info(
            f"Utskrift: sumatra={sumatra!r} skrivare={printer_name!r}"
        )
        if sumatra == "SumatraPDF.exe":
            logger.warning(
                "SumatraPDF.exe hittades inte. Ladda ner från "
                "https://www.sumatrapdfreader.org och lägg i projektmappen."
            )
        try:
            result = subprocess.run(
                [
                    sumatra,
                    "-print-to", printer_name,
                    "-silent",
                    "-exit-when-done",
                    "-print-settings", "noscale",
                    temp_path,
                ],
                timeout=30,
                capture_output=True,
            )
            Path(temp_path).unlink(missing_ok=True)

            if result.returncode == 0:
                logger.info(
                    f"PDF-{doc_type} utskriven på '{printer_name}' "
                    f"för order {order_no}"
                )
                return True

            stderr_str = (result.stderr or b"").decode("utf-8", errors="replace")[:300]
            logger.warning(
                f"SumatraPDF returnerade {result.returncode}. stderr: {stderr_str}"
            )
            return False

        except FileNotFoundError:
            Path(temp_path).unlink(missing_ok=True)
            logger.error(
                f"SumatraPDF kunde inte köras (filen hittades inte). "
                f"Sökväg: {sumatra}"
            )
            raise
        except Exception as e:
            Path(temp_path).unlink(missing_ok=True)
            raise

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
