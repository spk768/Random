"""Instalação do Minecraft: manifest de versões, cliente, bibliotecas, assets
e montagem dos argumentos de inicialização."""
from __future__ import annotations

import json
import re
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import net, paths, rules, settings

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
RESOURCES_URL = "https://resources.download.minecraft.net"
LIBRARIES_URL = "https://libraries.minecraft.net/"
NATIVE_SUFFIXES = (".so", ".dll", ".dylib", ".jnilib")

LogFn = Callable[[str], None]


# --------------------------------------------------------------------------
# Manifest e JSON de versão
# --------------------------------------------------------------------------

def get_manifest(refresh: bool = False) -> dict:
    path = paths.versions_dir() / "version_manifest_v2.json"
    fresh = path.exists() and time.time() - path.stat().st_mtime < 3600
    if path.exists() and fresh and not refresh:
        return json.loads(path.read_text("utf-8"))
    try:
        data = net.get_json(MANIFEST_URL)
        path.write_text(json.dumps(data), "utf-8")
        return data
    except Exception:
        if path.exists():  # offline: usa o cache antigo
            return json.loads(path.read_text("utf-8"))
        raise


def list_versions(snapshots: bool = False) -> list[str]:
    return [v["id"] for v in get_manifest()["versions"]
            if snapshots or v["type"] == "release"]


def version_json_path(version_id: str) -> Path:
    return paths.versions_dir() / version_id / f"{version_id}.json"


def fetch_version(version_id: str) -> dict:
    """Retorna o JSON cru da versão, baixando do manifest se necessário."""
    path = version_json_path(version_id)
    if path.exists():
        return json.loads(path.read_text("utf-8"))
    entry = next((v for v in get_manifest()["versions"] if v["id"] == version_id), None)
    if entry is None:
        raise ValueError(f"Versão do Minecraft desconhecida: {version_id}")
    net.download(net.Download(entry["url"], path, sha1=entry.get("sha1")))
    return json.loads(path.read_text("utf-8"))


def _lib_key(name: str) -> str:
    parts = name.split("@")[0].split(":")
    key = parts[:2] + parts[3:4]  # grupo:artefato[:classificador], sem versão
    return ":".join(key)


def merge(parent: dict, child: dict) -> dict:
    """Combina uma versão filha (loader) com a versão da qual ela herda."""
    out = {k: v for k, v in parent.items() if k != "jar"}
    for k, v in child.items():
        if k not in ("libraries", "arguments", "inheritsFrom"):
            out[k] = v
    child_libs = child.get("libraries", [])
    keys = {_lib_key(lib["name"]) for lib in child_libs}
    out["libraries"] = child_libs + [lib for lib in parent.get("libraries", [])
                                     if _lib_key(lib["name"]) not in keys]
    if "arguments" in parent or "arguments" in child:
        pa, ca = parent.get("arguments", {}), child.get("arguments", {})
        out["arguments"] = {
            "game": pa.get("game", []) + ca.get("game", []),
            "jvm": pa.get("jvm", []) + ca.get("jvm", []),
        }
    out["_vanilla"] = parent.get("_vanilla", parent["id"])
    return out


def resolve_version(version_id: str) -> dict:
    data = fetch_version(version_id)
    parent_id = data.get("inheritsFrom")
    if parent_id:
        return merge(resolve_version(parent_id), data)
    data = dict(data)
    data.setdefault("_vanilla", data["id"])
    return data


# --------------------------------------------------------------------------
# Bibliotecas
# --------------------------------------------------------------------------

def maven_path(name: str) -> str:
    ext = "jar"
    if "@" in name:
        name, ext = name.split("@", 1)
    parts = name.split(":")
    group, artifact, version = parts[:3]
    classifier = f"-{parts[3]}" if len(parts) > 3 else ""
    return "/".join(group.split(".") + [artifact, version,
                                         f"{artifact}-{version}{classifier}.{ext}"])


@dataclass
class LibFile:
    path: Path
    download: net.Download | None
    classpath: bool = True
    extract: bool = False


def library_files(version: dict) -> list[LibFile]:
    libdir = paths.libraries_dir()
    out: list[LibFile] = []
    for lib in version.get("libraries", []):
        if not rules.allows(lib.get("rules")):
            continue
        name = lib["name"]
        downloads = lib.get("downloads", {})
        natives = lib.get("natives")
        if natives:  # formato antigo (<= 1.18): classificador por SO
            classifier = natives.get(rules.os_name())
            if classifier:
                classifier = classifier.replace("${arch}", "64" if rules.is_64bit() else "32")
                info = downloads.get("classifiers", {}).get(classifier)
                if info:
                    path, url = info["path"], info["url"]
                    sha1, size = info.get("sha1"), info.get("size")
                else:
                    path = maven_path(f"{name}:{classifier}")
                    url, sha1, size = lib.get("url", LIBRARIES_URL).rstrip("/") + "/" + path, None, None
                out.append(LibFile(libdir / path, net.Download(url, libdir / path, sha1=sha1, size=size),
                                   classpath=False, extract=True))
        artifact = downloads.get("artifact")
        if artifact:
            path = artifact.get("path") or maven_path(name)
            url = artifact.get("url")
            dl = (net.Download(url, libdir / path, sha1=artifact.get("sha1"), size=artifact.get("size"))
                  if url else None)  # url vazia: arquivo gerado pelo instalador do Forge
            is_native = ":natives-" in name
            out.append(LibFile(libdir / path, dl, classpath=True, extract=is_native))
        elif not natives:
            path = maven_path(name)
            base = lib.get("url", LIBRARIES_URL).rstrip("/") + "/"
            out.append(LibFile(libdir / path, net.Download(base + path, libdir / path,
                                                           sha1=lib.get("sha1"), size=lib.get("size"))))
    return out


def client_jar_path(version: dict) -> Path:
    jar_id = version.get("jar") or version["id"]
    return paths.versions_dir() / jar_id / f"{jar_id}.jar"


# --------------------------------------------------------------------------
# Assets
# --------------------------------------------------------------------------

def asset_index(version: dict) -> dict | None:
    info = version.get("assetIndex")
    if not info:
        return None
    path = paths.assets_dir() / "indexes" / f"{info['id']}.json"
    net.download(net.Download(info["url"], path, sha1=info.get("sha1")))
    return json.loads(path.read_text("utf-8"))


def install_assets(version: dict, progress: net.ProgressFn | None = None) -> None:
    index = asset_index(version)
    if not index:
        return
    objects = paths.assets_dir() / "objects"
    downloads = []
    for obj in index["objects"].values():
        h = obj["hash"]
        downloads.append(net.Download(f"{RESOURCES_URL}/{h[:2]}/{h}", objects / h[:2] / h,
                                      sha1=h, size=obj.get("size")))
    net.download_many(downloads, settings.get("download_workers"), progress)


def legacy_assets_dir(version: dict, game_dir: Path) -> Path | None:
    """Versões antigas leem assets de uma pasta "virtual" com nomes reais."""
    index = asset_index(version)
    if not index or not (index.get("virtual") or index.get("map_to_resources")):
        return None
    if index.get("map_to_resources"):
        target = game_dir / "resources"
    else:
        target = paths.assets_dir() / "virtual" / version["assetIndex"]["id"]
    objects = paths.assets_dir() / "objects"
    for name, obj in index["objects"].items():
        dest = target / name
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(objects / obj["hash"][:2] / obj["hash"], dest)
    return target


# --------------------------------------------------------------------------
# Instalação completa
# --------------------------------------------------------------------------

def install_version(version: dict, log: LogFn = print,
                    progress: net.ProgressFn | None = None) -> None:
    workers = settings.get("download_workers")
    downloads = []
    client = version.get("downloads", {}).get("client")
    jar = client_jar_path(version)
    if client:
        downloads.append(net.Download(client["url"], jar, sha1=client.get("sha1"), size=client.get("size")))
    libs = library_files(version)
    downloads += [lf.download for lf in libs if lf.download]
    logging_file = version.get("logging", {}).get("client", {}).get("file")
    if logging_file:
        downloads.append(net.Download(logging_file["url"],
                                      paths.assets_dir() / "log_configs" / logging_file["id"],
                                      sha1=logging_file.get("sha1")))
    log(f"Verificando cliente e {len(libs)} bibliotecas...")
    net.download_many(downloads, workers, progress)
    missing = [lf.path.name for lf in libs if not lf.path.exists()]
    if missing:
        raise FileNotFoundError("Bibliotecas ausentes: " + ", ".join(missing[:5]))
    if not jar.exists():
        raise FileNotFoundError(f"Jar do cliente ausente: {jar}")
    log("Verificando assets...")
    install_assets(version, progress)


def natives_dir(version: dict) -> Path:
    return paths.versions_dir() / version["id"] / "natives"


def extract_natives(version: dict) -> Path:
    target = natives_dir(version)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    for lf in library_files(version):
        if not lf.extract or not lf.path.exists():
            continue
        with zipfile.ZipFile(lf.path) as zf:
            for member in zf.infolist():
                fname = member.filename.rsplit("/", 1)[-1]
                if member.is_dir() or member.filename.startswith("META-INF/"):
                    continue
                if fname.endswith(NATIVE_SUFFIXES):
                    (target / fname).write_bytes(zf.read(member))
    return target


# --------------------------------------------------------------------------
# Argumentos
# --------------------------------------------------------------------------

def _collect(args: list, features: dict) -> list[str]:
    out: list[str] = []
    for a in args:
        if isinstance(a, str):
            out.append(a)
        elif rules.allows(a.get("rules"), features):
            value = a["value"]
            out.extend([value] if isinstance(value, str) else value)
    return out


def substitute(arg: str, ctx: dict) -> str:
    return re.sub(r"\$\{(\w+)\}", lambda m: str(ctx.get(m.group(1), m.group(0))), arg)


def build_arguments(version: dict, ctx: dict, features: dict) -> tuple[list[str], list[str]]:
    if "arguments" in version:
        jvm = _collect(version["arguments"].get("jvm", []), features)
        game = _collect(version["arguments"].get("game", []), features)
    else:
        jvm = []
        game = version.get("minecraftArguments", "").split()
        if features.get("has_custom_resolution"):
            game += ["--width", "${resolution_width}", "--height", "${resolution_height}"]
    if not any("${classpath}" in a for a in jvm):
        jvm = ["-Djava.library.path=${natives_directory}", "-cp", "${classpath}"] + jvm
    return [substitute(a, ctx) for a in jvm], [substitute(a, ctx) for a in game]
