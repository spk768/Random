"""Instalação de mod loaders: Fabric, Quilt, Forge e NeoForge."""
from __future__ import annotations

import json
import subprocess
import zipfile
from typing import Callable

from . import java, minecraft, net, paths

FABRIC_META = "https://meta.fabricmc.net/v2"
QUILT_META = "https://meta.quiltmc.org/v3"
FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"
FORGE_META = "https://files.minecraftforge.net/net/minecraftforge/forge/maven-metadata.json"
NEOFORGE_MAVEN = "https://maven.neoforged.net/releases/net/neoforged"
NEOFORGE_VERSIONS = "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"

LOADERS = ("vanilla", "fabric", "quilt", "forge", "neoforge")

LogFn = Callable[[str], None]


def neoforge_mc_version(version: str) -> str:
    """21.1.77 -> 1.21.1, 21.0.3 -> 1.21, 26.1.0.5 -> 26.1"""
    parts = version.split("-")[0].split(".")
    major, minor = int(parts[0]), int(parts[1])
    if major >= 25:  # novo esquema de versões do Minecraft (ano.drop)
        return f"{major}.{minor}" if minor else str(major)
    return f"1.{major}" if minor == 0 else f"1.{major}.{minor}"


def list_versions(loader: str, mc: str) -> list[str]:
    """Versões do loader para a versão do Minecraft, da mais nova para a mais antiga."""
    if loader == "fabric":
        return [e["loader"]["version"] for e in net.get_json(f"{FABRIC_META}/versions/loader/{mc}")]
    if loader == "quilt":
        return [e["loader"]["version"] for e in net.get_json(f"{QUILT_META}/versions/loader/{mc}")]
    if loader == "forge":
        meta = net.get_json(FORGE_META)
        return [v.split("-", 1)[1] for v in reversed(meta.get(mc, []))]
    if loader == "neoforge":
        if mc == "1.20.1":  # NeoForge 1.20.1 publicava como "forge"
            versions = net.get_json(NEOFORGE_VERSIONS.rsplit("/", 1)[0] + "/forge")["versions"]
            return [v.split("-", 1)[1] for v in reversed(versions) if v.startswith("1.20.1-")]
        versions = net.get_json(NEOFORGE_VERSIONS)["versions"]
        return [v for v in reversed(versions) if neoforge_mc_version(v) == mc]
    return []


def install(loader: str, mc: str, loader_version: str, log: LogFn = print,
            java_override: str | None = None) -> str:
    """Instala o loader e retorna o id da versão resultante (pasta versions/)."""
    if loader == "vanilla":
        minecraft.fetch_version(mc)
        return mc
    if loader in ("fabric", "quilt"):
        return _install_profile(loader, mc, loader_version, log)
    if loader in ("forge", "neoforge"):
        return _install_forge_like(loader, mc, loader_version, log, java_override)
    raise ValueError(f"Loader desconhecido: {loader}")


def _install_profile(loader: str, mc: str, ver: str, log: LogFn) -> str:
    base = FABRIC_META if loader == "fabric" else QUILT_META
    minecraft.fetch_version(mc)
    profile = net.get_json(f"{base}/versions/loader/{mc}/{ver}/profile/json")
    path = minecraft.version_json_path(profile["id"])
    if not path.exists():
        log(f"Instalando {loader} {ver} para Minecraft {mc}...")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(profile, indent=2), "utf-8")
    return profile["id"]


def _installer_url(loader: str, mc: str, ver: str) -> str:
    if loader == "forge":
        full = f"{mc}-{ver}"
        return f"{FORGE_MAVEN}/{full}/forge-{full}-installer.jar"
    if mc == "1.20.1":  # NeoForge 1.20.1 ainda usava o artefato "forge"
        full = f"1.20.1-{ver}"
        return f"{NEOFORGE_MAVEN}/forge/{full}/forge-{full}-installer.jar"
    return f"{NEOFORGE_MAVEN}/neoforge/{ver}/neoforge-{ver}-installer.jar"


def _install_forge_like(loader: str, mc: str, ver: str, log: LogFn,
                        java_override: str | None) -> str:
    url = _installer_url(loader, mc, ver)
    installer = paths.cache_dir() / "installers" / url.rsplit("/", 1)[1]
    net.download(net.Download(url, installer))
    with zipfile.ZipFile(installer) as zf:
        profile = json.loads(zf.read("install_profile.json"))
    version_id = profile.get("version") or profile.get("install", {}).get("target")
    if not version_id:
        raise RuntimeError("install_profile.json sem id de versão")
    if minecraft.version_json_path(version_id).exists():
        return version_id

    vanilla = minecraft.resolve_version(mc)
    java_bin = java.find_java(java.required_major(vanilla), log, java_override)
    root = paths.root()
    profiles = root / "launcher_profiles.json"  # exigido pelo instalador
    if not profiles.exists():
        profiles.write_text('{"profiles": {}}', "utf-8")
    log(f"Executando instalador do {loader} {ver} (pode demorar alguns minutos)...")
    for flag in ("--installClient", "--install-client"):
        proc = subprocess.run([java_bin, "-jar", str(installer), flag, str(root)],
                              cwd=str(installer.parent), capture_output=True, text=True,
                              creationflags=java.no_window_flags())
        if proc.returncode == 0 and minecraft.version_json_path(version_id).exists():
            return version_id
    tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-15:])
    raise RuntimeError(f"Instalador do {loader} falhou:\n{tail}")
