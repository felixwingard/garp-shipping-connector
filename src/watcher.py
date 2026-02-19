"""Mappbevakning — bevakar en mapp för nya XML-filer från GARP.

Använder watchdog för filsystemhändelser + stabilitetskontroll
(väntar tills filen slutat växa innan den bearbetas).
"""

import time
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logger = logging.getLogger(__name__)


class XMLFileHandler(FileSystemEventHandler):
    """Reagerar på nya XML-filer i bevakad mapp."""

    def __init__(self, orchestrator, stability_seconds: int = 2):
        self.orchestrator = orchestrator
        self.stability_seconds = stability_seconds
        self._processing: set[str] = set()

    def on_created(self, event):
        if event.is_directory:
            return

        filepath = Path(event.src_path)
        if filepath.suffix.lower() != ".xml":
            return

        if filepath.name in self._processing:
            return

        self._processing.add(filepath.name)
        try:
            self._wait_for_stability(filepath)
            logger.info(f"Ny XML-fil: {filepath.name}")
            self.orchestrator.process_file(filepath)
        except FileNotFoundError:
            logger.warning(f"Filen försvann innan bearbetning: {filepath.name}")
        except Exception as e:
            logger.error(f"Ohanterat fel för {filepath.name}: {e}", exc_info=True)
        finally:
            self._processing.discard(filepath.name)

    def _wait_for_stability(self, filepath: Path):
        """Väntar tills filstorleken slutar ändras (GARP skriver klart)."""
        prev_size = -1
        for _ in range(10):
            time.sleep(self.stability_seconds)
            if not filepath.exists():
                raise FileNotFoundError(f"Filen försvann: {filepath}")
            current_size = filepath.stat().st_size
            if current_size == prev_size and current_size > 0:
                return
            prev_size = current_size
        raise TimeoutError(f"Filen stabiliserades aldrig: {filepath}")


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
        """Bearbetar XML-filer som redan finns i mappen.

        Körs vid uppstart för att hantera filer som kommit
        medan tjänsten var nere.
        """
        existing = sorted(self.watch_dir.glob("*.xml"))
        if not existing:
            return

        logger.info(f"Hittade {len(existing)} befintliga XML-filer vid uppstart")
        for filepath in existing:
            try:
                self.orchestrator.process_file(filepath)
            except Exception as e:
                logger.error(
                    f"Fel vid bearbetning av befintlig fil {filepath.name}: {e}",
                    exc_info=True,
                )
