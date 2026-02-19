"""GARP Shipping Connector — Entrypoint.

Kan köras som:
1. Tray-app (default): python -m src.main
2. Konsolprogram: python -m src.main --console
3. Windows-tjänst: GarpShippingConnector.exe install/start/stop/remove
"""

import sys
import platform


def main():
    args = sys.argv[1:]

    # Windows-tjänstkommandon: install, start, stop, remove
    if platform.system() == "Windows" and args and args[0] in (
        "install", "start", "stop", "remove", "restart", "update", "debug",
    ):
        from .service import GarpShippingService
        import win32serviceutil
        win32serviceutil.HandleCommandLine(GarpShippingService)
        return

    # Konsolläge (för utveckling/felsökning)
    if args and args[0] in ("--console", "-c", "console"):
        from .service import run_console
        run_console()
        return

    # Default: tray-app
    try:
        from .tray.app import TrayApp
        app = TrayApp()
        app.run()
    except ImportError as e:
        print(f"Kan inte starta tray-läge: {e}")
        print("Installera: pip install pystray Pillow")
        print("Startar konsolläge istället...")
        from .service import run_console
        run_console()


if __name__ == "__main__":
    main()
