"""Gemensam config-laddning för tray, service och konsolläge."""

import os
import re
import sys
from pathlib import Path

import yaml


def get_base_dir() -> Path:
    """Returnerar basmapp (där exe eller projekt ligger)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent.parent


def get_config_path() -> Path:
    """Returnerar sökväg till config.yaml."""
    return get_base_dir() / "config" / "config.yaml"


def get_example_config_path() -> Path:
    """Returnerar sökväg till config.example.yaml (bundlad eller bredvid)."""
    base = get_base_dir()
    # Först: bredvid exe
    beside = base / "config" / "config.example.yaml"
    if beside.exists():
        return beside
    # Frozen: inuti PyInstaller-bundel
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundled = Path(sys._MEIPASS) / "config" / "config.example.yaml"
        if bundled.exists():
            return bundled
    return beside


def load_config() -> dict:
    """Laddar config.yaml med miljövariabelersättning."""
    config_path = get_config_path()

    if not config_path.exists():
        example_path = get_example_config_path()
        if example_path.exists():
            import shutil

            config_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(example_path), str(config_path))
            import logging

            logging.getLogger(__name__).info(
                "Skapade config.yaml från config.example.yaml — "
                "fyll i era uppgifter och miljövariabler"
            )
        else:
            raise FileNotFoundError(
                f"Konfigurationsfil saknas: {config_path}\n"
                "Kopiera config.example.yaml till config.yaml och fyll i uppgifter."
            )

    with open(config_path, "r", encoding="utf-8") as f:
        raw = f.read()

    def replace_env(match):
        return os.environ.get(match.group(1), match.group(0))

    resolved = re.sub(r"\$\{(\w+)\}", replace_env, raw)
    return yaml.safe_load(resolved)
