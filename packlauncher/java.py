"""Localiza ou baixa (Eclipse Temurin/Adoptium) o Java exigido por cada versão."""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Callable

from . import net, paths, rules, settings

ADOPTIUM_API = "https://api.adoptium.net/v3"


def required_major(version: dict) -> int:
    return int(version.get("javaVersion", {}).get("majorVersion", 8))


def _exe() -> str:
    return "java.exe" if sys.platform == "win32" else "java"


def no_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def probe(java: str) -> int | None:
    """Retorna a versão principal do Java (8, 17, 21...) ou None se inválido."""
    try:
        res = subprocess.run([java, "-version"], capture_output=True, text=True,
                             timeout=20, creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'version "(\d+)(?:\.(\d+))?', res.stderr + res.stdout)
    if not m:
        return None
    major = int(m.group(1))
    return int(m.group(2) or 0) if major == 1 else major


def _find_in(root: Path) -> Path | None:
    for pattern in (f"bin/{_exe()}", f"*/bin/{_exe()}", f"*/Contents/Home/bin/{_exe()}"):
        hits = sorted(root.glob(pattern))
        if hits:
            return hits[0]
    return None


def candidates() -> list[str]:
    found: list[str] = []
    if os.environ.get("JAVA_HOME"):
        found.append(str(Path(os.environ["JAVA_HOME"]) / "bin" / _exe()))
    which = shutil.which("java")
    if which:
        found.append(which)
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            for vendor in ("Java", "Eclipse Adoptium", "Microsoft", "Zulu", "BellSoft"):
                found += glob.glob(os.path.join(base, vendor, "*", "bin", "java.exe"))
    elif sys.platform == "darwin":
        found += glob.glob("/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java")
    else:
        found += glob.glob("/usr/lib/jvm/*/bin/java")
    seen, out = set(), []
    for c in found:
        if c not in seen and os.path.isfile(c):
            seen.add(c)
            out.append(c)
    return out


def find_java(major: int, log: Callable[[str], None] = print, override: str | None = None) -> str:
    if override:
        return override
    configured = settings.get("java_paths").get(str(major))
    if configured and os.path.isfile(configured):
        return configured
    managed = _find_in(paths.java_dir() / str(major))
    if managed:
        return str(managed)
    for c in candidates():
        if probe(c) == major:
            return c
    if not settings.get("auto_download_java"):
        raise RuntimeError(f"Java {major} não encontrado. Configure em settings.json (java_paths).")
    return str(download_java(major, log))


def download_java(major: int, log: Callable[[str], None] = print) -> Path:
    feature = 17 if major == 16 else major  # Temurin 16 não tem JRE; 17 roda 1.17
    os_map = {"windows": "windows", "osx": "mac", "linux": "linux"}
    arch = {"x86_64": "x64", "arm64": "aarch64", "x86": "x86"}.get(rules.machine(), "x64")
    if arch == "x86" and rules.os_name() != "windows":
        arch = "x64"
    query = (f"{ADOPTIUM_API}/assets/latest/{feature}/hotspot?architecture={arch}"
             f"&image_type=jre&os={os_map[rules.os_name()]}&vendor=eclipse")
    assets = net.get_json(query)
    if not assets and arch == "aarch64" and rules.os_name() == "osx":
        assets = net.get_json(query.replace("aarch64", "x64"))  # Java 8 roda via Rosetta
    if not assets:
        raise RuntimeError(f"Nenhum Java {feature} disponível para este sistema")
    package = assets[0]["binary"]["package"]
    log(f"Baixando Java {feature} ({package['name']})...")
    archive = paths.cache_dir() / package["name"]
    net.download(net.Download(package["link"], archive, size=package.get("size")))
    if package.get("checksum") and net.hash_file(archive, "sha256") != package["checksum"]:
        archive.unlink()
        raise RuntimeError("Checksum do Java não confere")
    target = paths.java_dir() / str(major)
    tmp = target.with_name(target.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(tmp)
    else:
        with tarfile.open(archive) as tf:
            if hasattr(tarfile, "data_filter"):
                tf.extractall(tmp, filter="data")
            else:
                tf.extractall(tmp)
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
    archive.unlink(missing_ok=True)
    java = _find_in(target)
    if not java:
        raise RuntimeError("Java baixado, mas o executável não foi encontrado")
    if sys.platform != "win32":
        java.chmod(0o755)
    return java
