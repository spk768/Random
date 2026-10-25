"""Instâncias: cada uma tem pasta de jogo, versão, loader e (opcionalmente) um modpack."""
from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import paths, settings


@dataclass
class Instance:
    name: str
    minecraft: str
    loader: str = "vanilla"
    loader_version: str | None = None
    version_id: str | None = None  # id resolvido em versions/ após instalar o loader
    memory_mb: int = 0  # 0 = padrão global
    java_path: str = ""
    jvm_args: str = ""
    width: int = 0
    height: int = 0
    # Modpack de origem: source, project_id, version_id, version_number, title, files...
    pack: dict = field(default_factory=dict)
    # Projetos adicionados manualmente do Modrinth: {project_id: caminho relativo}
    extra_projects: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    last_played: float = 0
    playtime: float = 0
    dir: Path = field(default=None, repr=False, compare=False)  # type: ignore[assignment]

    @property
    def game_dir(self) -> Path:
        path = self.dir / "minecraft"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def mods_dir(self) -> Path:
        return self.game_dir / "mods"

    @property
    def effective_memory(self) -> int:
        return self.memory_mb or int(settings.get("default_memory_mb"))

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data.pop("dir")
        (self.dir / "instance.json").write_text(json.dumps(data, indent=2), "utf-8")

    def describe(self) -> str:
        loader = "" if self.loader == "vanilla" else f" {self.loader} {self.loader_version or ''}"
        return f"Minecraft {self.minecraft}{loader}".strip()


def _slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "instancia"
    base, n = slug, 2
    while (paths.instances_dir() / slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def load(directory: Path) -> Instance:
    data = json.loads((directory / "instance.json").read_text("utf-8"))
    known = Instance.__dataclass_fields__
    inst = Instance(**{k: v for k, v in data.items() if k in known and k != "dir"})
    inst.dir = directory
    return inst


def list_all() -> list[Instance]:
    out = []
    for d in sorted(paths.instances_dir().iterdir()):
        if (d / "instance.json").is_file():
            try:
                out.append(load(d))
            except (ValueError, TypeError):
                continue
    out.sort(key=lambda i: (-i.last_played, i.name.lower()))
    return out


def find(key: str) -> Instance:
    for inst in list_all():
        if key in (inst.name, inst.dir.name) or key.lower() == inst.name.lower():
            return inst
    raise KeyError(f"Instância não encontrada: {key}")


def unique_name(name: str) -> str:
    names = {i.name.lower() for i in list_all()}
    candidate, n = name, 2
    while candidate.lower() in names:
        candidate = f"{name} ({n})"
        n += 1
    return candidate


def create(name: str, minecraft: str, loader: str = "vanilla",
           loader_version: str | None = None, **extra) -> Instance:
    name = unique_name(name)
    inst = Instance(name=name, minecraft=minecraft, loader=loader,
                    loader_version=loader_version, **extra)
    inst.dir = paths.instances_dir() / _slug(name)
    inst.save()
    inst.game_dir  # cria a pasta do jogo
    return inst


def delete(inst: Instance) -> None:
    shutil.rmtree(inst.dir)


# --------------------------------------------------------------------------
# Mods
# --------------------------------------------------------------------------

def list_mods(inst: Instance) -> list[dict]:
    mods_dir = inst.mods_dir
    if not mods_dir.is_dir():
        return []
    out = []
    for f in sorted(mods_dir.iterdir(), key=lambda p: p.name.lower()):
        if f.suffix == ".jar" or f.name.endswith(".jar.disabled"):
            out.append({"file": f.name, "path": f, "enabled": f.suffix == ".jar",
                        "from_pack": f"mods/{f.name.removesuffix('.disabled')}"
                                     in inst.pack.get("files", [])})
    return out


def set_mod_enabled(inst: Instance, filename: str, enabled: bool) -> str:
    path = inst.mods_dir / filename
    if not path.exists():
        raise FileNotFoundError(filename)
    if enabled and path.name.endswith(".disabled"):
        new = path.with_name(path.name.removesuffix(".disabled"))
    elif not enabled and not path.name.endswith(".disabled"):
        new = path.with_name(path.name + ".disabled")
    else:
        return path.name
    path.rename(new)
    return new.name
