"""Localização dos diretórios do launcher.

Bibliotecas, assets, versões e runtimes Java são compartilhados entre
instâncias; cada instância tem a própria pasta de jogo.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def root() -> Path:
    env = os.environ.get("PACKLAUNCHER_HOME")
    if env:
        base = Path(env)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home())) / "PackLauncher"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "PackLauncher"
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        base = Path(xdg) / "PackLauncher"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sub(name: str) -> Path:
    path = root() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def instances_dir() -> Path:
    return _sub("instances")


def versions_dir() -> Path:
    return _sub("versions")


def libraries_dir() -> Path:
    return _sub("libraries")


def assets_dir() -> Path:
    return _sub("assets")


def java_dir() -> Path:
    return _sub("java")


def cache_dir() -> Path:
    return _sub("cache")


def settings_file() -> Path:
    return root() / "settings.json"


def accounts_file() -> Path:
    return root() / "accounts.json"
