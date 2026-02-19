"""Windows-tjänst för GARP Shipping Connector.

Körs som en Windows Service via pywin32.
Kan också köras direkt från kommandoraden för felsökning.

Installation:
    GarpShippingConnector.exe install
    GarpShippingConnector.exe start

Avinstallation:
    GarpShippingConnector.exe stop
    GarpShippingConnector.exe remove
"""

import sys
import logging
import platform

logger = logging.getLogger(__name__)


def _load_config() -> dict:
    """Laddar YAML-konfiguration med miljövariabelersättning."""
    import os
    import re
    import yaml
    from pathlib import Path

    # Konfigurationsfilen ligger bredvid .exe eller i projektrot
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
    else:
        exe_dir = Path(__file__).parent.parent

    config_path = exe_dir / "config" / "config.yaml"

    with open(config_path, "r", encoding="utf-8") as f:
        raw = f.read()

    # Ersätt ${ENV_VAR} med miljövariabler
    def replace_env(match):
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))

    resolved = re.sub(r'\$\{(\w+)\}', replace_env, raw)
    return yaml.safe_load(resolved)


def _setup_logging(config: dict):
    """Konfigurerar loggning med roterande filer."""
    import logging.handlers
    from pathlib import Path

    log_config = config.get("logging", {})
    log_dir = Path(log_config.get("log_dir", config["paths"].get("log_dir", ".")))
    log_dir.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, log_config.get("level", "INFO").upper())
    max_bytes = log_config.get("max_file_size_mb", 10) * 1024 * 1024
    backup_count = log_config.get("backup_count", 30)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Roterande loggfil
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "garp_shipping.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    # Separat error-logg
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


def run_console():
    """Kör som vanligt konsolprogram (för utveckling/felsökning)."""
    from .orchestrator import ShipmentOrchestrator
    from .watcher import FolderWatcher

    config = _load_config()
    _setup_logging(config)

    logger.info("GARP Shipping Connector startar (konsolläge)")
    logger.info(f"Bevakar: {config['paths']['watch_dir']}")

    orchestrator = ShipmentOrchestrator(config)
    watcher = FolderWatcher(
        config["paths"]["watch_dir"],
        orchestrator,
        config["watcher"]["file_stability_seconds"],
    )

    watcher.process_existing_files()
    watcher.start()

    try:
        logger.info("Tryck Ctrl+C för att stoppa...")
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stoppar...")
        watcher.stop()
        logger.info("Stoppad")


if platform.system() == "Windows":
    try:
        import win32serviceutil
        import win32service
        import win32event
        import servicemanager

        class GarpShippingService(win32serviceutil.ServiceFramework):
            _svc_name_ = "GarpShippingConnector"
            _svc_display_name_ = "GARP Shipping Connector"
            _svc_description_ = (
                "Bevakar GARP XML-filer och skapar fraktsedlar "
                "via DHL och PostNord"
            )

            def __init__(self, args):
                win32serviceutil.ServiceFramework.__init__(self, args)
                self.stop_event = win32event.CreateEvent(None, 0, 0, None)
                self.watcher = None

            def SvcStop(self):
                self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
                logger.info("Stoppar tjänsten...")
                win32event.SetEvent(self.stop_event)
                if self.watcher:
                    self.watcher.stop()

            def SvcDoRun(self):
                try:
                    servicemanager.LogMsg(
                        servicemanager.EVENTLOG_INFORMATION_TYPE,
                        servicemanager.PYS_SERVICE_STARTED,
                        (self._svc_name_, ""),
                    )

                    from .orchestrator import ShipmentOrchestrator
                    from .watcher import FolderWatcher

                    config = _load_config()
                    _setup_logging(config)
                    logger.info("GARP Shipping Connector startar (Windows-tjänst)")

                    orchestrator = ShipmentOrchestrator(config)
                    self.watcher = FolderWatcher(
                        config["paths"]["watch_dir"],
                        orchestrator,
                        config["watcher"]["file_stability_seconds"],
                    )

                    self.watcher.process_existing_files()
                    self.watcher.start()

                    win32event.WaitForSingleObject(
                        self.stop_event, win32event.INFINITE
                    )

                except Exception as e:
                    logger.critical(f"Kritiskt fel: {e}", exc_info=True)
                    servicemanager.LogErrorMsg(
                        f"GarpShippingConnector: {e}"
                    )

    except ImportError:
        pass  # pywin32 inte installerat (utveckling på macOS/Linux)
