"""Mappbevakning — bevakar en mapp för nya XML-filer från GARP.

GARP skriver filer med .txt-suffix (innehåll är XML). Accepterar både .xml och .txt.
Använder watchdog för filsystemhändelser + stabilitetskontroll.
"""

import time
import logging
import shutil
import tempfile
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logger = logging.getLogger(__name__)

# GARP skriver .txt men innehållet är XML-format
WATCH_EXTENSIONS = {".xml", ".txt"}


class XMLFileHandler(FileSystemEventHandler):
    """Reagerar på nya/ändrade XML-filer (.xml eller .txt) i bevakad mapp."""

    def __init__(self, orchestrator, stability_seconds: int = 2):
        self.orchestrator = orchestrator
        self.stability_seconds = stability_seconds
        self._processing: set[str] = set()

    def on_created(self, event):
        self._handle(event)

    def on_modified(self, event):
        self._handle(event)

    def on_moved(self, event):
        if event.is_directory:
            return
        dest = Path(event.dest_path)
        if dest.suffix.lower() in WATCH_EXTENSIONS:
            if dest.name not in self._processing:
                self._process(dest)

    def _handle(self, event):
        if event.is_directory:
            return
        filepath = Path(event.src_path)
        if filepath.suffix.lower() not in WATCH_EXTENSIONS:
            return
        if filepath.name in self._processing:
            return
        self._process(filepath)

    def _process(self, filepath: Path):
        self._processing.add(filepath.name)
        try:
            ready_path = self._ensure_file_ready(filepath)
            if ready_path:
                logger.info(f"Ny fil: {filepath.name}")
                self.orchestrator.process_file(ready_path)
        except Exception as e:
            logger.error(f"Ohanterat fel för {filepath.name}: {e}", exc_info=True)
        finally:
            self._processing.discard(filepath.name)

    def _ensure_file_ready(self, filepath: Path) -> Path | None:
        """Säkerställer att filen är redo för bearbetning.

        Strategi:
        1. Försök läsa filen omedelbart (snabbt — innan den försvinner)
        2. Om filen finns: kör stabilitetskontroll (vänta tills GARP skrivit klart)
        3. Om filen redan försvunnit: returnera None
        """
        # Försök 1: läs direkt (ingen sleep)
        content = self._try_read(filepath)
        if content is not None and len(content) > 0:
            # Filen finns och har innehåll — kör snabb stabilitetskontroll
            time.sleep(min(self.stability_seconds, 1))
            if filepath.exists():
                return filepath
            # Filen försvann efter att vi läste den — spara till temp och bearbeta därifrån
            logger.info(
                f"Fil {filepath.name} lästes ({len(content)} bytes) "
                f"men försvann — bearbetar från kopia"
            )
            return self._save_to_temp(filepath.name, content)

        # Försök 2: vänta och retry (filen kanske inte är skriven ännu)
        for attempt in range(5):
            time.sleep(self.stability_seconds)
            content = self._try_read(filepath)
            if content is not None and len(content) > 0:
                # Kolla stabilitet (storlek ändras inte)
                time.sleep(min(self.stability_seconds, 1))
                content2 = self._try_read(filepath)
                if content2 is not None:
                    if filepath.exists():
                        return filepath
                    logger.info(
                        f"Fil {filepath.name} lästes ({len(content2)} bytes) "
                        f"men försvann — bearbetar från kopia"
                    )
                    return self._save_to_temp(filepath.name, content2)
            elif content is None:
                logger.info(
                    f"Fil ej tillgänglig ({filepath.name}), "
                    f"väntar {self.stability_seconds}s ({4 - attempt} försök kvar)"
                )

        logger.warning(f"Filen försvann innan bearbetning: {filepath.name}")
        return None

    @staticmethod
    def _try_read(filepath: Path) -> bytes | None:
        """Försöker läsa filens innehåll. Returnerar None om filen inte finns/ej läsbar."""
        try:
            if filepath.exists():
                return filepath.read_bytes()
        except (OSError, PermissionError):
            pass
        return None

    @staticmethod
    def _save_to_temp(filename: str, content: bytes) -> Path:
        """Sparar filinnehåll till en temporär fil för bearbetning."""
        suffix = Path(filename).suffix or ".txt"
        tmp = tempfile.NamedTemporaryFile(
            suffix=suffix, prefix=f"garp_{Path(filename).stem}_",
            delete=False
        )
        tmp.write(content)
        tmp.close()
        logger.info(f"Temporär kopia sparad: {tmp.name}")
        return Path(tmp.name)


class FolderWatcher:
    """Bevakar en mapp för nya XML-filer."""

    def __init__(self, watch_dir: str, orchestrator,
                 stability_seconds: int = 2):
        self.watch_dir = Path(watch_dir)
        self.orchestrator = orchestrator
        self.handler = XMLFileHandler(orchestrator, stability_seconds)
        self.observer = Observer()

    def start(self):
        """Startar bevakning."""
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        self.observer.schedule(self.handler, str(self.watch_dir), recursive=False)
        self.observer.start()
        logger.info(f"Bevakar mapp: {self.watch_dir}")

    def stop(self):
        """Stoppar bevakning."""
        self.observer.stop()
        self.observer.join(timeout=10)
        logger.info("Mappbevakning stoppad")

    def process_existing_files(self):
        """Bearbetar XML-filer (.xml/.txt) som redan finns i mappen.

        Körs vid uppstart för att hantera filer som kommit
        medan tjänsten var nere.
        """
        existing = sorted(
            p for p in self.watch_dir.iterdir()
            if p.is_file() and p.suffix.lower() in WATCH_EXTENSIONS
        )
        if not existing:
            return

        logger.info(f"Hittade {len(existing)} befintliga filer vid uppstart")
        for filepath in existing:
            try:
                self.orchestrator.process_file(filepath)
            except Exception as e:
                logger.error(
                    f"Fel vid bearbetning av befintlig fil {filepath.name}: {e}",
                    exc_info=True,
                )
