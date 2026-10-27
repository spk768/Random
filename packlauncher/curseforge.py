"""Integração com o CurseForge: busca, instalação/atualização de modpacks
(.zip com manifest.json) e adição de mods avulsos.

A API do CurseForge exige uma chave (https://console.curseforge.com). A URL
base também é configurável, para usar proxies compatíveis com a API oficial.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import zipfile
from pathlib import Path
from typing import Callable

from . import instances, net, paths, settings
from .instances import Instance
from .modrinth import PRESERVE_ON_UPDATE, PackError, safe_path

OFFICIAL_URL = "https://api.curseforge.com"
GAME_ID = 432  # Minecraft
CLASS_MODPACK = 4471
CLASS_FOLDERS = {6: "mods", 12: "resourcepacks", 6552: "shaderpacks", 6945: "datapacks"}
CLASS_TYPES = {"modpack": CLASS_MODPACK, "mod": 6, "resourcepack": 12, "shader": 6552}
LOADER_TYPES = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
LOADER_NAMES = {"forge", "fabric", "quilt", "neoforge"}
RELEASE_TYPES = {1: "release", 2: "beta", 3: "alpha"}

LogFn = Callable[[str], None]


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

def _config() -> tuple[str, str]:
    cfg = settings.load()
    url = (cfg.get("curseforge_api_url") or OFFICIAL_URL).rstrip("/")
    key = cfg.get("curseforge_api_key") or ""
    if not key and url == OFFICIAL_URL:
        raise PackError("Configure a chave da API do CurseForge em Configurações "
                        "(ou uma URL de API alternativa que não exija chave).")
    return url, key


def _headers(key: str) -> dict:
    h = {"Accept": "application/json"}
    if key:
        h["x-api-key"] = key
    return h


def _call(path: str, payload=None, **params):
    url, key = _config()
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    full = f"{url}/v1{path}" + (f"?{query}" if query else "")
    try:
        if payload is not None:
            return net.post_json(full, payload, _headers(key))
        return net.get_json(full, _headers(key))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise PackError("A API do CurseForge recusou a chave. Verifique-a em Configurações.") from e
        if e.code == 404:
            raise PackError("Não encontrado no CurseForge") from e
        raise


def project_id(pid: str | int) -> int:
    return int(str(pid).removeprefix("cf:"))


def _normalize(mod: dict) -> dict:
    """Converte um projeto do CurseForge para o formato usado pela interface."""
    versions, loaders = set(), set()
    for idx in mod.get("latestFilesIndexes", []):
        versions.add(idx.get("gameVersion"))
        lt = idx.get("modLoader")
        name = {v: k for k, v in LOADER_TYPES.items()}.get(lt)
        if name:
            loaders.add(name)
    ordered = sorted((v for v in versions if v), key=_version_key)
    shots = mod.get("screenshots") or []
    types = {v: k for k, v in CLASS_TYPES.items()}
    return {
        "source": "curseforge",
        "project_id": f"cf:{mod['id']}",
        "slug": mod.get("slug"),
        "title": mod.get("name"),
        "author": (mod.get("authors") or [{}])[0].get("name", ""),
        "description": mod.get("summary", ""),
        "downloads": int(mod.get("downloadCount", 0)),
        "follows": int(mod.get("thumbsUpCount", 0)),
        "icon_url": (mod.get("logo") or {}).get("thumbnailUrl"),
        "categories": sorted(loaders) + [c["name"].lower() for c in mod.get("categories", [])][:3],
        "display_categories": [c["name"].lower() for c in mod.get("categories", [])][:3],
        "versions": ordered,
        "featured_gallery": shots[0]["url"] if shots else None,
        "gallery": [{"url": s["url"], "title": s.get("title")} for s in shots],
        "project_type": types.get(mod.get("classId"), "mod"),
        "url": (mod.get("links") or {}).get("websiteUrl"),
        "class_id": mod.get("classId"),
    }


def _version_key(v: str):
    return [int(p) if p.isdigit() else 0 for p in v.split(".")]


def search(query: str = "", project_type: str = "modpack", game_version: str | None = None,
           loader: str | None = None, limit: int = 20, offset: int = 0) -> dict:
    res = _call("/mods/search", gameId=GAME_ID, classId=CLASS_TYPES.get(project_type, CLASS_MODPACK),
                searchFilter=query, gameVersion=game_version,
                modLoaderType=LOADER_TYPES.get(loader or ""), sortField=2, sortOrder="desc",
                index=offset, pageSize=min(limit, 50))
    pagination = res.get("pagination", {})
    return {"hits": [_normalize(m) for m in res.get("data", [])],
            "total_hits": min(int(pagination.get("totalCount", 0)), 10000)}


def get_project(pid) -> dict:
    return _normalize(_call(f"/mods/{project_id(pid)}")["data"])


def _file_info(f: dict) -> dict:
    gv = f.get("gameVersions", [])
    return {
        "id": str(f["id"]),
        "version_number": f.get("displayName") or f.get("fileName"),
        "game_versions": sorted((v for v in gv if v[:1].isdigit()), key=_version_key),
        "loaders": [v.lower() for v in gv if v.lower() in LOADER_NAMES],
        "version_type": RELEASE_TYPES.get(f.get("releaseType"), "release"),
        "file": f,
    }


def get_versions(pid, loaders: list[str] | None = None, game_versions: list[str] | None = None) -> list[dict]:
    """Arquivos do projeto, do mais recente para o mais antigo."""
    loader = (loaders or [None])[0]
    res = _call(f"/mods/{project_id(pid)}/files", gameVersion=(game_versions or [None])[0],
                modLoaderType=LOADER_TYPES.get(loader or ""), pageSize=50)
    files = sorted(res.get("data", []), key=lambda f: f.get("fileDate", ""), reverse=True)
    return [_file_info(f) for f in files]


def _get_file(pid, file_id) -> dict:
    return _call(f"/mods/{project_id(pid)}/files/{file_id}")["data"]


def _sha1(f: dict) -> str | None:
    return next((h["value"] for h in f.get("hashes", []) if h.get("algo") == 1), None)


def _urls(f: dict) -> list[str]:
    """URL de download; para arquivos com distribuição de terceiros desativada a
    API devolve null, então tenta também a CDN pública."""
    urls = [f["downloadUrl"]] if f.get("downloadUrl") else []
    fid, name = int(f["id"]), urllib.parse.quote(f["fileName"])
    urls.append(f"https://edge.forgecdn.net/files/{fid // 1000}/{fid % 1000}/{name}")
    urls.append(f"https://mediafilez.forgecdn.net/files/{fid // 1000}/{fid % 1000}/{name}")
    return list(dict.fromkeys(urls))


# --------------------------------------------------------------------------
# Modpacks
# --------------------------------------------------------------------------

def read_manifest(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        try:
            manifest = json.loads(zf.read("manifest.json"))
        except KeyError:
            raise PackError("Arquivo não é um modpack do CurseForge (manifest.json ausente)")
    if manifest.get("manifestType") not in (None, "minecraftModpack"):
        raise PackError(f"Tipo de manifest não suportado: {manifest.get('manifestType')}")
    return manifest


def is_curseforge_pack(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            return "manifest.json" in zf.namelist() and "modrinth.index.json" not in zf.namelist()
    except zipfile.BadZipFile:
        return False


def pack_requirements(manifest: dict) -> tuple[str, str, str | None]:
    mc = manifest.get("minecraft", {})
    if not mc.get("version"):
        raise PackError("O modpack não informa a versão do Minecraft")
    loaders = mc.get("modLoaders", [])
    primary = next((l for l in loaders if l.get("primary")), loaders[0] if loaders else None)
    if not primary:
        return mc["version"], "vanilla", None
    name, _, version = primary["id"].partition("-")
    if name not in LOADER_NAMES:
        raise PackError(f"Loader não suportado: {primary['id']}")
    return mc["version"], name, version


def apply_pack(path: Path, inst: Instance, log: LogFn = print,
               progress: net.ProgressFn | None = None) -> list[dict]:
    """Instala/atualiza um modpack do CurseForge na instância. Retorna os arquivos
    que não puderam ser baixados automaticamente."""
    manifest = read_manifest(path)
    mc, loader, loader_version = pack_requirements(manifest)
    game = inst.game_dir
    updating = bool(inst.pack.get("files"))
    entries = [f for f in manifest.get("files", []) if f.get("required", True)]

    files_info: dict[int, dict] = {}
    mods_info: dict[int, dict] = {}
    if entries:
        log(f"Consultando {len(entries)} arquivos no CurseForge...")
        ids = [int(f["fileID"]) for f in entries]
        for i in range(0, len(ids), 500):
            for f in _call("/mods/files", {"fileIds": ids[i:i + 500]})["data"]:
                files_info[int(f["id"])] = f
        pids = sorted({int(f["projectID"]) for f in entries})
        for i in range(0, len(pids), 500):
            for m in _call("/mods", {"modIds": pids[i:i + 500], "filterPcOnly": True})["data"]:
                mods_info[int(m["id"])] = m

    downloads, new_files, missing = [], [], []
    for entry in entries:
        f = files_info.get(int(entry["fileID"]))
        mod = mods_info.get(int(entry["projectID"]), {})
        if not f:
            missing.append({"name": mod.get("name", f"projeto {entry['projectID']}"),
                            "url": (mod.get("links") or {}).get("websiteUrl")})
            continue
        folder = CLASS_FOLDERS.get(mod.get("classId"), "mods")
        rel = f"{folder}/{f['fileName']}"
        dest = safe_path(game, rel)
        disabled = dest.with_name(dest.name + ".disabled")
        if disabled.exists():
            dest = disabled
        downloads.append((net.Download(_urls(f), dest, sha1=_sha1(f), size=f.get("fileLength")), mod, f))
        new_files.append(rel)

    for old in set(inst.pack.get("files", [])) - set(new_files):
        try:
            target = safe_path(game, old)
        except PackError:
            continue
        for p in (target, target.with_name(target.name + ".disabled")):
            if p.is_file():
                log(f"Removendo {old}")
                p.unlink()

    log(f"Baixando {len(downloads)} arquivos do modpack...")
    try:
        net.download_many([d for d, _, _ in downloads], settings.get("download_workers"), progress)
    except net.DownloadError:
        pass  # os que faltarem são listados abaixo
    for d, mod, f in downloads:
        if not d.dest.exists():
            missing.append({"name": mod.get("name", f["fileName"]), "file": f["fileName"],
                            "url": (mod.get("links") or {}).get("websiteUrl")})

    overrides = (manifest.get("overrides") or "overrides").strip("/") + "/"
    with zipfile.ZipFile(path) as zf:
        for member in zf.infolist():
            if member.is_dir() or not member.filename.startswith(overrides):
                continue
            rel = member.filename[len(overrides):]
            dest = safe_path(game, rel)
            if updating and rel in PRESERVE_ON_UPDATE and dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(dest, "wb") as out:
                out.write(src.read())

    if (inst.minecraft, inst.loader, inst.loader_version) != (mc, loader, loader_version):
        inst.version_id = None
    inst.minecraft, inst.loader, inst.loader_version = mc, loader, loader_version
    inst.pack.update({"files": new_files, "title": manifest.get("name") or inst.pack.get("title"),
                      "version_number": manifest.get("version"), "missing": missing})
    inst.save()
    if missing:
        log(f"Atenção: {len(missing)} arquivo(s) não permitem download automático. Baixe manualmente "
            "na página do CurseForge e coloque na pasta mods: " + ", ".join(m["name"] for m in missing))
    return missing


def _download_pack_file(f: dict, log: LogFn) -> Path:
    dest = paths.cache_dir() / "cfpacks" / f["fileName"]
    log(f"Baixando {f['fileName']}...")
    net.download(net.Download(_urls(f), dest, sha1=_sha1(f), size=f.get("fileLength")))
    return dest


def _latest_file(pid) -> dict:
    files = get_versions(pid)
    if not files:
        raise PackError("O projeto não tem arquivos publicados")
    releases = [v for v in files if v["version_type"] == "release"]
    return (releases or files)[0]["file"]


def install_pack(pid, file_id: str | None = None, name: str | None = None, log: LogFn = print,
                 progress: net.ProgressFn | None = None, **_) -> Instance:
    proj = get_project(pid)
    if proj["class_id"] != CLASS_MODPACK:
        raise PackError(f"{proj['title']} não é um modpack")
    f = _get_file(pid, file_id) if file_id else _latest_file(pid)
    path = _download_pack_file(f, log)
    mc, loader, loader_version = pack_requirements(read_manifest(path))
    inst = instances.create(name or proj["title"], mc, loader, loader_version)
    inst.pack = {"source": "curseforge", "project_id": proj["project_id"], "slug": proj["slug"],
                 "version_id": str(f["id"]), "icon_url": proj["icon_url"],
                 "banner_url": proj["featured_gallery"], "url": proj["url"], "files": []}
    try:
        apply_pack(path, inst, log, progress)
    except Exception:
        instances.delete(inst)
        raise
    log(f"Modpack instalado: {inst.name} ({f.get('displayName')})")
    return inst


def import_pack(path: Path, name: str | None = None, log: LogFn = print,
                progress: net.ProgressFn | None = None, **_) -> Instance:
    manifest = read_manifest(path)
    mc, loader, loader_version = pack_requirements(manifest)
    inst = instances.create(name or manifest.get("name") or path.stem, mc, loader, loader_version)
    inst.pack = {"source": "file", "format": "curseforge", "files": []}
    try:
        apply_pack(path, inst, log, progress)
    except Exception:
        instances.delete(inst)
        raise
    return inst


def check_update(inst: Instance) -> dict | None:
    if inst.pack.get("source") != "curseforge":
        return None
    latest = _latest_file(inst.pack["project_id"])
    if str(latest["id"]) == inst.pack.get("version_id"):
        return None
    return {"id": str(latest["id"]), "version_number": latest.get("displayName") or latest["fileName"]}


def update_pack(inst: Instance, file_id: str | None = None, log: LogFn = print,
                progress: net.ProgressFn | None = None) -> bool:
    if inst.pack.get("source") != "curseforge":
        raise PackError("Esta instância não veio de um modpack do CurseForge")
    pid = inst.pack["project_id"]
    f = _get_file(pid, file_id) if file_id else _latest_file(pid)
    if str(f["id"]) == inst.pack.get("version_id"):
        log("O modpack já está na versão selecionada.")
        return False
    apply_pack(_download_pack_file(f, log), inst, log, progress)
    inst.pack["version_id"] = str(f["id"])
    inst.save()
    log(f"Modpack atualizado para {f.get('displayName')}")
    return True


# --------------------------------------------------------------------------
# Mods avulsos
# --------------------------------------------------------------------------

def add_project(inst: Instance, pid, log: LogFn = print, _seen: set | None = None) -> None:
    seen = _seen if _seen is not None else set()
    proj = get_project(pid)
    key = proj["project_id"]
    if key in seen or key in inst.extra_projects:
        return
    seen.add(key)
    folder = CLASS_FOLDERS.get(proj["class_id"])
    if not folder or folder == "datapacks":
        raise PackError(f"Tipo de projeto não suportado: {proj['title']}")
    loaders = [inst.loader] if proj["class_id"] == 6 and inst.loader != "vanilla" else None
    files = get_versions(pid, loaders, [inst.minecraft])
    if not files:
        raise PackError(f"{proj['title']} não tem versão para {inst.describe()}")
    f = files[0]["file"]
    dest = safe_path(inst.game_dir, f"{folder}/{f['fileName']}")
    log(f"Adicionando {proj['title']} {f.get('displayName')}")
    net.download(net.Download(_urls(f), dest, sha1=_sha1(f), size=f.get("fileLength")))
    inst.extra_projects[key] = f"{folder}/{f['fileName']}"
    inst.save()
    for dep in f.get("dependencies", []):
        if dep.get("relationType") == 3:  # dependência obrigatória
            add_project(inst, f"cf:{dep['modId']}", log, seen)
