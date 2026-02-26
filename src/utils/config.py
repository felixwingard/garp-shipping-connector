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


def _deep_merge_defaults(defaults: dict, user: dict) -> dict:
    """Fyll i saknade nycklar från defaults. Användarens värden vinner alltid."""
    result = dict(defaults)
    for k, v in user.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge_defaults(result[k], v)
        else:
            result[k] = v
    return result


def save_config(config: dict) -> None:
    """Sparar config till config.yaml (överskriver filen)."""
    path = get_config_path()
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def increment_bring_bulk_count(config: dict, delta: int) -> int:
    """Ökar bring.bulk_parcel_count med delta, sparar till config.yaml, returnerar nytt värde."""
    path = get_config_path()
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    bring = cfg.get("bring") or {}
    current = int(bring.get("bulk_parcel_count", 0))
    new_val = max(0, current + delta)
    bring["bulk_parcel_count"] = new_val
    cfg["bring"] = bring
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    if "bring" not in config:
        config["bring"] = {}
    config["bring"]["bulk_parcel_count"] = new_val
    return new_val


def load_config() -> dict:
    """Laddar config.yaml med miljövariabelersättning.
    Nya nycklar från config.example.yaml mergas in automatiskt — slipper manuell kopiering vid git pull.
    """
    config_path = get_config_path()
    example_path = get_example_config_path()

    if not config_path.exists():
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
    user_config = yaml.safe_load(resolved) or {}

    # Merga in defaults för saknade nycklar (t.ex. print_document_for_products vid ny git pull)
    if example_path.exists():
        try:
            with open(example_path, "r", encoding="utf-8") as ef:
                example_raw = re.sub(r"\$\{(\w+)\}", replace_env, ef.read())
            defaults = yaml.safe_load(example_raw) or {}
            return _deep_merge_defaults(defaults, user_config)
        except Exception:
            pass  # Vid fel, använd bara user_config
    return user_config
