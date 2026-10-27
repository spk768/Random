"""Interface de linha de comando. Sem argumentos, abre a interface gráfica."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import __version__, auth, curseforge, instances, launch, loaders, minecraft, modrinth, net, settings


def _progress():
    state = {"t": 0.0}

    def report(done: int, total: int) -> None:
        now = time.time()
        if done == total or now - state["t"] > 0.2:
            state["t"] = now
            end = "\n" if done == total else ""
            print(f"\r  {done}/{total} ({done * 100 // total}%)", end=end, flush=True)
    return report


def _human(n: int) -> str:
    for unit in ("", "K", "M"):
        if n < 1000:
            return f"{n}{unit}"
        n //= 1000
    return f"{n}B"


def _provider(key):
    """CurseForge para ids "cf:123" (ou source "curseforge"); Modrinth caso contrário."""
    key = str(key or "")
    return curseforge if key.startswith("cf:") or key in ("curseforge", "True") else modrinth


def cmd_search(a) -> None:
    res = _provider(a.cf).search(a.query, game_version=a.mc, loader=a.loader, limit=a.limit)
    for hit in res["hits"]:
        mc = hit.get("versions", [])[-1:] or ["?"]
        ident = hit["project_id"] if a.cf else hit["slug"]
        print(f"{ident:<32} {_human(hit['downloads']):>6} ↓  MC {mc[0]:<8} {hit['title']}")
        print(f"    {hit['description'][:100]}")
    print(f"\n{res['total_hits']} resultados. Instale com: packlauncher install <slug>")


def cmd_versions(a) -> None:
    for v in _provider(a.project).get_versions(a.project)[: a.limit]:
        print(f"{v['id']}  {v['version_number']:<20} {v['version_type']:<8} "
              f"MC {', '.join(v['game_versions'])}  [{', '.join(v['loaders'])}]")


def cmd_install(a) -> None:
    optional = (lambda f: False) if a.no_optional else (lambda f: True)
    source = a.source
    if source.endswith(".zip") and Path(source).exists():
        inst = curseforge.import_pack(Path(source), a.name, progress=_progress())
    elif source.endswith(".mrpack") and Path(source).exists():
        inst = modrinth.import_mrpack(Path(source), a.name, progress=_progress(),
                                      include_optional=optional)
    else:
        inst = _provider(source).install_pack(source, a.version, a.name, progress=_progress(),
                                              include_optional=optional)
    print(f"Pronto! Jogue com: packlauncher launch \"{inst.name}\"")


def cmd_update(a) -> None:
    inst = instances.find(a.instance)
    if a.check:
        latest = _provider(inst.pack.get("source")).check_update(inst)
        print(f"Atualização disponível: {latest['version_number']}" if latest
              else "O modpack está atualizado.")
        return
    _provider(inst.pack.get("source")).update_pack(inst, a.version, progress=_progress())


def cmd_create(a) -> None:
    inst = instances.create(a.name, a.mc, a.loader, a.loader_version)
    print(f"Instância criada: {inst.name} ({inst.describe()})")


def cmd_list(a) -> None:
    items = instances.list_all()
    if not items:
        print("Nenhuma instância. Use 'search' e 'install' para baixar um modpack.")
    for inst in items:
        pack = inst.pack.get("title")
        extra = f"  [{pack} {inst.pack.get('version_number', '')}]" if pack else ""
        hours = inst.playtime / 3600
        print(f"{inst.name:<28} {inst.describe():<34} {hours:5.1f}h{extra}")


def cmd_delete(a) -> None:
    inst = instances.find(a.instance)
    if not a.yes and input(f"Excluir '{inst.name}' e todos os mundos? [s/N] ").lower() != "s":
        return
    instances.delete(inst)
    print("Excluída.")


def cmd_mods(a) -> None:
    inst = instances.find(a.instance)
    if a.add:
        _provider(a.add).add_project(inst, a.add)
    for name in a.enable or []:
        instances.set_mod_enabled(inst, name, True)
    for name in a.disable or []:
        instances.set_mod_enabled(inst, name, False)
    for m in instances.list_mods(inst):
        mark = "x" if m["enabled"] else " "
        origin = "pack" if m["from_pack"] else "    "
        print(f"[{mark}] {origin}  {m['file']}")


def cmd_export(a) -> None:
    inst = instances.find(a.instance)
    out = Path(a.output or f"{inst.name}-{a.version_number}.mrpack")
    modrinth.export_mrpack(inst, out, a.version_number, a.summary or "")


def cmd_launch(a) -> None:
    inst = instances.find(a.instance)
    account = auth.find(a.account) if a.account else auth.get_default()
    if a.account and not account:
        raise SystemExit(f"Conta não encontrada: {a.account}")
    if a.dry_run:
        version, java_bin = launch.prepare(inst, progress=_progress())
        account = account or {"type": "offline", "name": "Player",
                              "uuid": auth.offline_uuid("Player")}
        print(" ".join(launch.build_command(inst, version, account, java_bin)))
        return
    proc = launch.launch(inst, account, progress=_progress())
    proc.wait()
    time.sleep(0.5)  # deixa a thread de log terminar


def cmd_account(a) -> None:
    if a.action == "offline":
        acc = auth.add_offline(a.name)
        print(f"Conta offline adicionada: {acc['name']}")
    elif a.action == "microsoft":
        acc = auth.login_microsoft(lambda url, code: print(f"Abra {url} e digite o código: {code}"))
        print(f"Logado como {acc['name']}")
    elif a.action == "default":
        acc = auth.find(a.name)
        if not acc:
            raise SystemExit("Conta não encontrada")
        auth.set_default(acc["uuid"])
    elif a.action == "remove":
        acc = auth.find(a.name)
        if not acc:
            raise SystemExit("Conta não encontrada")
        auth.remove(acc["uuid"])
    default = auth.get_default()
    for acc in auth.list_accounts():
        star = "*" if default and acc["uuid"] == default["uuid"] else " "
        print(f"{star} {acc['name']:<16} {acc['type']:<8} {acc['uuid']}")


def cmd_mc_versions(a) -> None:
    if a.loader and a.loader != "vanilla":
        print("\n".join(loaders.list_versions(a.loader, a.mc)[:20]))
    else:
        print("\n".join(minecraft.list_versions(a.snapshots)[:40]))


def cmd_config(a) -> None:
    if a.key and a.value is not None:
        value = a.value
        if value.isdigit():
            value = int(value)
        elif value.lower() in ("true", "false"):
            value = value.lower() == "true"
        settings.set(a.key, value)
    for k, v in settings.load().items():
        print(f"{k} = {v}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="packlauncher", description="Launcher de Minecraft focado em modpacks")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("gui", help="abre a interface gráfica")
    s.add_argument("--port", type=int, default=0, help="porta local (padrão: aleatória)")
    s.add_argument("--no-window", action="store_true", help="só inicia o servidor e mostra a URL")
    s.set_defaults(func=lambda a: __import__("packlauncher.gui", fromlist=["main"])
                   .main(open_window=not a.no_window, port=a.port))

    s = sub.add_parser("search", help="busca modpacks no Modrinth")
    s.add_argument("query", nargs="?", default="")
    s.add_argument("--mc", help="versão do Minecraft")
    s.add_argument("--loader", choices=loaders.LOADERS[1:])
    s.add_argument("--limit", type=int, default=15)
    s.add_argument("--cf", action="store_true", help="busca no CurseForge em vez do Modrinth")
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("versions", help="lista versões de um modpack")
    s.add_argument("project")
    s.add_argument("--limit", type=int, default=15)
    s.set_defaults(func=cmd_versions)

    s = sub.add_parser("install", help="instala um modpack (slug do Modrinth, cf:ID do CurseForge, .mrpack ou .zip)")
    s.add_argument("source")
    s.add_argument("--version", help="id da versão do modpack (padrão: mais recente)")
    s.add_argument("--name", help="nome da instância")
    s.add_argument("--no-optional", action="store_true", help="não instala arquivos opcionais")
    s.set_defaults(func=cmd_install)

    s = sub.add_parser("update", help="atualiza o modpack de uma instância")
    s.add_argument("instance")
    s.add_argument("--version", help="id da versão (padrão: mais recente)")
    s.add_argument("--check", action="store_true", help="apenas verifica")
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("create", help="cria uma instância sem modpack")
    s.add_argument("name")
    s.add_argument("--mc", required=True)
    s.add_argument("--loader", default="vanilla", choices=loaders.LOADERS)
    s.add_argument("--loader-version")
    s.set_defaults(func=cmd_create)

    s = sub.add_parser("list", help="lista instâncias")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("delete", help="exclui uma instância")
    s.add_argument("instance")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(func=cmd_delete)

    s = sub.add_parser("mods", help="lista/ativa/desativa/adiciona mods")
    s.add_argument("instance")
    s.add_argument("--add", metavar="PROJETO", help="adiciona do Modrinth (mod, resource pack ou shader)")
    s.add_argument("--enable", nargs="+", metavar="ARQUIVO")
    s.add_argument("--disable", nargs="+", metavar="ARQUIVO")
    s.set_defaults(func=cmd_mods)

    s = sub.add_parser("export", help="exporta a instância como .mrpack")
    s.add_argument("instance")
    s.add_argument("-o", "--output")
    s.add_argument("--version-number", default="1.0.0")
    s.add_argument("--summary")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("launch", help="inicia uma instância")
    s.add_argument("instance")
    s.add_argument("--account")
    s.add_argument("--dry-run", action="store_true", help="instala tudo e só mostra o comando")
    s.set_defaults(func=cmd_launch)

    s = sub.add_parser("account", help="gerencia contas")
    s.add_argument("action", nargs="?", default="list",
                   choices=["list", "offline", "microsoft", "default", "remove"])
    s.add_argument("name", nargs="?")
    s.set_defaults(func=cmd_account)

    s = sub.add_parser("mc-versions", help="lista versões do Minecraft ou de um loader")
    s.add_argument("--loader", choices=loaders.LOADERS)
    s.add_argument("--mc")
    s.add_argument("--snapshots", action="store_true")
    s.set_defaults(func=cmd_mc_versions)

    s = sub.add_parser("config", help="mostra ou altera configurações")
    s.add_argument("key", nargs="?")
    s.add_argument("value", nargs="?")
    s.set_defaults(func=cmd_config)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd:
        from . import gui
        return gui.main()
    if args.cmd == "account" and args.action in ("offline", "default", "remove") and not args.name:
        parser.error("informe o nome da conta")
    if args.cmd == "mc-versions" and args.loader not in (None, "vanilla") and not args.mc:
        parser.error("--mc é obrigatório com --loader")
    try:
        args.func(args)
    except KeyboardInterrupt:
        return 130
    except (KeyError, ValueError, RuntimeError, OSError, modrinth.PackError, auth.AuthError,
            net.DownloadError) as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    return 0
