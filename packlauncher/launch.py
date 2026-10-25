"""Preparação e execução do jogo para uma instância."""
from __future__ import annotations

import os
import shlex
import subprocess
import threading
import time
from typing import Callable

from . import __version__, auth, instances, java, loaders, minecraft, net, paths
from .instances import Instance

LogFn = Callable[[str], None]


def ensure_version(inst: Instance, log: LogFn = print) -> dict:
    """Garante o loader instalado e retorna o JSON de versão mesclado."""
    vid = inst.version_id
    if not vid or not minecraft.version_json_path(vid).exists():
        if inst.loader != "vanilla" and not inst.loader_version:
            versions = loaders.list_versions(inst.loader, inst.minecraft)
            if not versions:
                raise RuntimeError(f"{inst.loader} não suporta Minecraft {inst.minecraft}")
            inst.loader_version = versions[0]
        vid = loaders.install(inst.loader, inst.minecraft, inst.loader_version or "",
                              log, inst.java_path or None)
        inst.version_id = vid
        inst.save()
    return minecraft.resolve_version(vid)


def prepare(inst: Instance, log: LogFn = print,
            progress: net.ProgressFn | None = None) -> tuple[dict, str]:
    log(f"Preparando {inst.name} ({inst.describe()})...")
    version = ensure_version(inst, log)
    java_bin = java.find_java(java.required_major(version), log, inst.java_path or None)
    minecraft.install_version(version, log, progress)
    return version, java_bin


def build_command(inst: Instance, version: dict, account: dict, java_bin: str) -> list[str]:
    game_dir = inst.game_dir
    natives = minecraft.extract_natives(version)
    sep = os.pathsep
    cp = [str(lf.path) for lf in minecraft.library_files(version) if lf.classpath]
    cp.append(str(minecraft.client_jar_path(version)))
    cp = list(dict.fromkeys(cp))  # remove duplicados mantendo a ordem
    assets_root = paths.assets_dir()
    legacy = minecraft.legacy_assets_dir(version, game_dir)
    msa = account["type"] == "msa"
    ctx = {
        "auth_player_name": account["name"],
        "auth_uuid": account["uuid"].replace("-", ""),
        "auth_access_token": account.get("access_token", "0") if msa else "0",
        "auth_session": account.get("access_token", "0") if msa else "0",
        "auth_xuid": account.get("xuid", "") if msa else "0",
        "clientid": "",
        "user_type": "msa" if msa else "legacy",
        "user_properties": "{}",
        "version_name": version["id"],
        "version_type": version.get("type", "release"),
        "game_directory": str(game_dir),
        "assets_root": str(assets_root),
        "game_assets": str(legacy or assets_root),
        "assets_index_name": version.get("assetIndex", {}).get("id", version.get("assets", "")),
        "natives_directory": str(natives),
        "launcher_name": "PackLauncher",
        "launcher_version": __version__,
        "classpath": sep.join(cp),
        "classpath_separator": sep,
        "library_directory": str(paths.libraries_dir()),
        "resolution_width": str(inst.width),
        "resolution_height": str(inst.height),
    }
    features = {"has_custom_resolution": bool(inst.width and inst.height)}
    jvm, game = minecraft.build_arguments(version, ctx, features)
    mem = inst.effective_memory
    cmd = [java_bin, f"-Xms{min(512, mem)}M", f"-Xmx{mem}M"]
    cmd += shlex.split(inst.jvm_args, posix=os.name != "nt") if inst.jvm_args else []
    logging = version.get("logging", {}).get("client")
    if logging and logging.get("file"):
        cfg = paths.assets_dir() / "log_configs" / logging["file"]["id"]
        cmd.append(logging["argument"].replace("${path}", str(cfg)))
    return cmd + jvm + [version["mainClass"]] + game


def launch(inst: Instance, account: dict | None = None, log: LogFn = print,
           progress: net.ProgressFn | None = None,
           on_exit: Callable[[int], None] | None = None) -> subprocess.Popen:
    account = account or auth.get_default()
    if not account:
        raise RuntimeError("Nenhuma conta configurada. Adicione uma conta primeiro.")
    account = auth.ensure_valid(account)
    version, java_bin = prepare(inst, log, progress)
    cmd = build_command(inst, version, account, java_bin)
    log(f"Iniciando Minecraft como {account['name']}...")
    logs = inst.dir / "logs"
    logs.mkdir(exist_ok=True)
    proc = subprocess.Popen(cmd, cwd=str(inst.game_dir), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors="replace",
                            creationflags=java.no_window_flags())
    started = time.time()
    inst.last_played = started
    inst.save()

    def pump():
        with open(logs / "latest-launcher.log", "w", encoding="utf-8") as f:
            for line in proc.stdout:  # type: ignore[union-attr]
                f.write(line)
                log(line.rstrip("\n"))
        code = proc.wait()
        fresh = instances.load(inst.dir)
        fresh.playtime += time.time() - started
        fresh.save()
        log(f"Minecraft encerrado (código {code}).")
        if on_exit:
            on_exit(code)

    threading.Thread(target=pump, daemon=True).start()
    return proc
