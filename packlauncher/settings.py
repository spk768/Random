"""Configurações globais do launcher (settings.json)."""
from __future__ import annotations

import json
import os

from . import paths

DEFAULTS = {
    # Client ID de um app Azure com permissão para a API do Minecraft.
    # Necessário apenas para login com conta Microsoft.
    "msa_client_id": "",
    "default_memory_mb": 4096,
    "download_workers": 8,
    # Caminhos de Java por versão principal, ex.: {"17": "/usr/bin/java"}
    "java_paths": {},
    "auto_download_java": True,
}


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        data.update(json.loads(paths.settings_file().read_text("utf-8")))
    except (OSError, ValueError):
        pass
    if os.environ.get("PACKLAUNCHER_MSA_CLIENT_ID"):
        data["msa_client_id"] = os.environ["PACKLAUNCHER_MSA_CLIENT_ID"]
    return data


def save(data: dict) -> None:
    paths.settings_file().write_text(json.dumps(data, indent=2), "utf-8")


def get(key: str):
    return load().get(key, DEFAULTS.get(key))


def set(key: str, value) -> None:  # noqa: A001 - API simples
    data = load()
    data[key] = value
    save(data)
