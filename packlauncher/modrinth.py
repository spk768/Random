"""Integração com o Modrinth: busca, instalação/atualização de modpacks (.mrpack),
adição de mods avulsos e exportação de instâncias para .mrpack."""
from __future__ import annotations

import json
import re
import urllib.parse
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable

from . import instances, net, paths, settings
from .instances import Instance

API = "https://api.modrinth.com/v2"
# Domínios permitidos para downloads de arquivos de um .mrpack (especificação do formato)
ALLOWED_HOSTS = {"cdn.modrinth.com", "github.com", "raw.githubusercontent.com", "gitlab.com"}
LOADER_KEYS = {"fabric-loader": "fabric", "quilt-loader": "quilt",
               "forge": "forge", "neoforge": "neoforge"}
# Arquivos do usuário que não são sobrescritos pelos overrides ao atualizar
PRESERVE_ON_UPDATE = {"options.txt", "servers.dat", "optionsof.txt", "optionsshaders.txt"}

LogFn = Callable[[str], None]


class PackError(Exception):
    pass


def _get(path: str, **params):
    query = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                                    for k, v in params.items() if v is not None})
    return net.get_json(f"{API}{path}" + (f"?{query}" if query else ""))


# --------------------------------------------------------------------------
# Consulta
# --------------------------------------------------------------------------

def search(query: str = "", project_type: str = "modpack", game_version: str | None = None,
           loader: str | None = None, limit: int = 20, offset: int = 0) -> dict:
    facets = [[f"project_type:{project_type}"]]
    if game_version:
        facets.append([f"versions:{game_version}"])
    if loader:
        facets.append([f"categories:{loader}"])
    return _get("/search", query=query, facets=facets, limit=limit, offset=offset,
                index="relevance" if query else "downloads")


def get_project(id_or_slug: str) -> dict:
    return _get(f"/project/{urllib.parse.quote(id_or_slug)}")


def get_versions(id_or_slug: str, loaders: list[str] | None = None,
                 game_versions: list[str] | None = None) -> list[dict]:
    """Versões do projeto, da mais recente para a mais antiga."""
    return _get(f"/project/{urllib.parse.quote(id_or_slug)}/version",
                loaders=loaders, game_versions=game_versions)


def get_version(version_id: str) -> dict:
    return _get(f"/version/{version_id}")


def primary_file(version: dict) -> dict:
    files = version.get("files", [])
    if not files:
        raise PackError(f"A versão {version.get('version_number')} não tem arquivos")
    return next((f for f in files if f.get("primary")), files[0])


# --------------------------------------------------------------------------
# .mrpack
# --------------------------------------------------------------------------

def safe_path(root: Path, rel: str) -> Path:
    """Resolve um caminho relativo do pack recusando caminhos absolutos ou com '..'."""
    rel = rel.replace("\\", "/")
    pure = PurePosixPath(rel)
    if not rel or pure.is_absolute() or re.match(r"^[A-Za-z]:", rel) or ".." in pure.parts:
        raise PackError(f"Caminho inseguro no modpack: {rel!r}")
    return root.joinpath(*pure.parts)


def _allowed(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS


def read_index(mrpack: Path) -> dict:
    with zipfile.ZipFile(mrpack) as zf:
        try:
            index = json.loads(zf.read("modrinth.index.json"))
        except KeyError:
            raise PackError("Arquivo não é um .mrpack válido (modrinth.index.json ausente)")
    if index.get("game") != "minecraft":
        raise PackError(f"Jogo não suportado: {index.get('game')}")
    if index.get("formatVersion") != 1:
        raise PackError(f"formatVersion não suportado: {index.get('formatVersion')}")
    return index


def pack_requirements(index: dict) -> tuple[str, str, str | None]:
    deps = index.get("dependencies", {})
    if "minecraft" not in deps:
        raise PackError("O modpack não informa a versão do Minecraft")
    for key, loader in LOADER_KEYS.items():
        if key in deps:
            return deps["minecraft"], loader, deps[key]
    return deps["minecraft"], "vanilla", None


def apply_mrpack(mrpack: Path, inst: Instance, include_optional: Callable[[dict], bool] = lambda f: True,
                 log: LogFn = print, progress: net.ProgressFn | None = None) -> None:
    """Instala/atualiza o conteúdo de um .mrpack na instância."""
    index = read_index(mrpack)
    mc, loader, loader_version = pack_requirements(index)
    game = inst.game_dir
    updating = bool(inst.pack.get("files"))

    downloads, new_files = [], []
    for f in index.get("files", []):
        client = (f.get("env") or {}).get("client", "required")
        if client == "unsupported" or (client == "optional" and not include_optional(f)):
            continue
        dest = safe_path(game, f["path"])
        urls = [u for u in f.get("downloads", []) if _allowed(u)]
        if not urls:
            raise PackError(f"Nenhum download permitido para {f['path']}")
        disabled = dest.with_name(dest.name + ".disabled")
        if disabled.exists():  # mantém desativado o que o usuário desativou
            dest = disabled
        hashes = f.get("hashes", {})
        downloads.append(net.Download(urls, dest, sha1=hashes.get("sha1"),
                                      sha512=hashes.get("sha512"), size=f.get("fileSize")))
        new_files.append(f["path"].replace("\\", "/"))

    # Remove arquivos da versão anterior do pack que saíram nesta versão
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
    net.download_many(downloads, settings.get("download_workers"), progress)

    with zipfile.ZipFile(mrpack) as zf:
        for prefix in ("overrides/", "client-overrides/"):
            for member in zf.infolist():
                if member.is_dir() or not member.filename.startswith(prefix):
                    continue
                rel = member.filename[len(prefix):]
                dest = safe_path(game, rel)
                if updating and rel in PRESERVE_ON_UPDATE and dest.exists():
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(dest, "wb") as out:
                    out.write(src.read())

    if (inst.minecraft, inst.loader, inst.loader_version) != (mc, loader, loader_version):
        inst.version_id = None  # força reinstalar o loader no próximo launch
    inst.minecraft, inst.loader, inst.loader_version = mc, loader, loader_version
    inst.pack.update({"files": new_files, "title": index.get("name", inst.pack.get("title")),
                      "version_number": index.get("versionId")})
    inst.save()


def download_pack_version(version: dict, log: LogFn = print) -> Path:
    file = primary_file(version)
    dest = paths.cache_dir() / "mrpacks" / file["filename"]
    log(f"Baixando {file['filename']}...")
    net.download(net.Download(file["url"], dest, sha1=file.get("hashes", {}).get("sha1"),
                              sha512=file.get("hashes", {}).get("sha512"), size=file.get("size")))
    return dest


def install_pack(project: str, version_id: str | None = None, name: str | None = None,
                 log: LogFn = print, progress: net.ProgressFn | None = None,
                 include_optional: Callable[[dict], bool] = lambda f: True) -> Instance:
    """Cria uma instância a partir de um modpack do Modrinth (slug ou id)."""
    proj = get_project(project)
    if proj.get("project_type") != "modpack":
        raise PackError(f"{proj['title']} não é um modpack")
    version = get_version(version_id) if version_id else _latest(proj["id"])
    mrpack = download_pack_version(version, log)
    mc, loader, loader_version = pack_requirements(read_index(mrpack))
    inst = instances.create(name or proj["title"], mc, loader, loader_version)
    gallery = proj.get("gallery") or []
    banner = next((g["url"] for g in gallery if g.get("featured")), gallery[0]["url"] if gallery else None)
    inst.pack = {"source": "modrinth", "project_id": proj["id"], "slug": proj["slug"],
                 "version_id": version["id"], "icon_url": proj.get("icon_url"),
                 "banner_url": banner, "files": []}
    try:
        apply_mrpack(mrpack, inst, include_optional, log, progress)
    except Exception:
        instances.delete(inst)
        raise
    log(f"Modpack instalado: {inst.name} ({version['version_number']})")
    return inst


def import_mrpack(mrpack: Path, name: str | None = None, log: LogFn = print,
                  progress: net.ProgressFn | None = None,
                  include_optional: Callable[[dict], bool] = lambda f: True) -> Instance:
    """Cria uma instância a partir de um arquivo .mrpack local."""
    index = read_index(mrpack)
    mc, loader, loader_version = pack_requirements(index)
    inst = instances.create(name or index.get("name", mrpack.stem), mc, loader, loader_version)
    inst.pack = {"source": "file", "files": []}
    try:
        apply_mrpack(mrpack, inst, include_optional, log, progress)
    except Exception:
        instances.delete(inst)
        raise
    return inst


def _latest(project_id: str) -> dict:
    versions = get_versions(project_id)
    if not versions:
        raise PackError("O projeto não tem versões publicadas")
    releases = [v for v in versions if v.get("version_type") == "release"]
    return (releases or versions)[0]


def check_update(inst: Instance) -> dict | None:
    """Retorna a versão mais recente do modpack se for diferente da instalada."""
    if inst.pack.get("source") != "modrinth":
        return None
    latest = _latest(inst.pack["project_id"])
    return latest if latest["id"] != inst.pack.get("version_id") else None


def update_pack(inst: Instance, version_id: str | None = None, log: LogFn = print,
                progress: net.ProgressFn | None = None) -> bool:
    if inst.pack.get("source") != "modrinth":
        raise PackError("Esta instância não veio de um modpack do Modrinth")
    version = get_version(version_id) if version_id else _latest(inst.pack["project_id"])
    if version["id"] == inst.pack.get("version_id"):
        log("O modpack já está na versão selecionada.")
        return False
    mrpack = download_pack_version(version, log)
    apply_mrpack(mrpack, inst, log=log, progress=progress)
    inst.pack["version_id"] = version["id"]
    inst.save()
    log(f"Modpack atualizado para {version['version_number']}")
    return True


# --------------------------------------------------------------------------
# Mods avulsos
# --------------------------------------------------------------------------

FOLDERS = {"mod": "mods", "resourcepack": "resourcepacks", "shader": "shaderpacks"}


def add_project(inst: Instance, project: str, log: LogFn = print, _seen: set | None = None) -> None:
    """Adiciona um mod/resource pack/shader do Modrinth, com dependências obrigatórias."""
    seen = _seen if _seen is not None else set()
    proj = get_project(project)
    if proj["id"] in seen or proj["id"] in inst.extra_projects:
        return
    seen.add(proj["id"])
    folder = FOLDERS.get(proj["project_type"])
    if not folder:
        raise PackError(f"Tipo de projeto não suportado: {proj['project_type']}")
    loaders = [inst.loader] if proj["project_type"] == "mod" else None
    versions = get_versions(proj["id"], loaders=loaders, game_versions=[inst.minecraft])
    if not versions:
        raise PackError(f"{proj['title']} não tem versão para {inst.describe()}")
    version = versions[0]
    file = primary_file(version)
    dest = safe_path(inst.game_dir, f"{folder}/{file['filename']}")
    log(f"Adicionando {proj['title']} {version['version_number']}")
    net.download(net.Download(file["url"], dest, sha512=file.get("hashes", {}).get("sha512")))
    inst.extra_projects[proj["id"]] = f"{folder}/{file['filename']}"
    inst.save()
    for dep in version.get("dependencies", []):
        if dep.get("dependency_type") == "required" and dep.get("project_id"):
            add_project(inst, dep["project_id"], log, seen)


# --------------------------------------------------------------------------
# Exportação
# --------------------------------------------------------------------------

EXPORT_INDEXED = ("mods", "resourcepacks", "shaderpacks")
EXPORT_OVERRIDES = ("config", "defaultconfigs", "kubejs", "scripts", "global_packs")


def export_mrpack(inst: Instance, out: Path, version_number: str = "1.0.0",
                  summary: str = "", log: LogFn = print) -> Path:
    """Exporta a instância como .mrpack. Arquivos encontrados no Modrinth viram
    downloads; o restante vai para overrides/."""
    game = inst.game_dir
    candidates = [p for folder in EXPORT_INDEXED if (game / folder).is_dir()
                  for p in sorted((game / folder).iterdir())
                  if p.is_file() and not p.name.endswith(".disabled")]
    by_sha1 = {net.hash_file(p, "sha1"): p for p in candidates}
    found: dict = {}
    if by_sha1:
        try:
            found = net.post_json(f"{API}/version_files",
                                  {"hashes": list(by_sha1), "algorithm": "sha1"}) or {}
        except Exception as e:
            log(f"Aviso: não foi possível consultar o Modrinth ({e}); tudo irá em overrides.")

    files, overrides = [], []
    for sha1, path in by_sha1.items():
        rel = path.relative_to(game).as_posix()
        version = found.get(sha1)
        vfile = next((f for f in (version or {}).get("files", [])
                      if f.get("hashes", {}).get("sha1") == sha1), None)
        if vfile:
            files.append({"path": rel, "hashes": {"sha1": sha1, "sha512": net.hash_file(path, "sha512")},
                          "downloads": [vfile["url"]], "fileSize": path.stat().st_size})
        else:
            overrides.append(path)
    for folder in EXPORT_OVERRIDES:
        if (game / folder).is_dir():
            overrides += [p for p in sorted((game / folder).rglob("*")) if p.is_file()]

    deps = {"minecraft": inst.minecraft}
    key = {v: k for k, v in LOADER_KEYS.items()}.get(inst.loader)
    if key:
        deps[key] = inst.loader_version
    index = {"formatVersion": 1, "game": "minecraft", "versionId": version_number,
             "name": inst.pack.get("title") or inst.name, "files": files, "dependencies": deps}
    if summary:
        index["summary"] = summary
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("modrinth.index.json", json.dumps(index, indent=2))
        for p in overrides:
            zf.write(p, "overrides/" + p.relative_to(game).as_posix())
    log(f"Exportado: {out} ({len(files)} do Modrinth, {len(overrides)} em overrides)")
    return out
