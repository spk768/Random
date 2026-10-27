"""Interface gráfica: servidor local + página web (estilo GD Launcher).

A interface roda em uma janela de aplicativo do Chrome/Edge/Chromium quando
disponível (sem barra de endereço), ou no navegador padrão.
"""
from __future__ import annotations

import json
import mimetypes
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import (__version__, auth, instances, java, launch, loaders, minecraft, modrinth,
               paths, settings)
from .instances import Instance

WEB_DIR = Path(__file__).parent / "web"


# ---------------------------------------------------------------------------
# Eventos e tarefas em segundo plano
# ---------------------------------------------------------------------------

class Hub:
    """Distribui eventos para os clientes conectados via Server-Sent Events."""

    def __init__(self) -> None:
        self.clients: set[queue.Queue] = set()
        self.lock = threading.Lock()
        self.last_disconnect = time.time()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self.lock:
            self.clients.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            self.clients.discard(q)
            self.last_disconnect = time.time()

    def publish(self, event: str, data) -> None:
        with self.lock:
            for q in self.clients:
                q.put((event, data))


class Task:
    def __init__(self, tasks: "Tasks", title: str, instance: str | None) -> None:
        self.id = secrets.token_hex(4)
        self.tasks = tasks
        self.title = title
        self.instance = instance
        self.status = "running"
        self.message = ""
        self.done = 0
        self.total = 0
        self._last_emit = 0.0

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "instance": self.instance, "status": self.status,
                "message": self.message, "done": self.done, "total": self.total}

    def log(self, msg: str) -> None:
        self.message = msg
        if self.instance:
            self.tasks.app.add_log(self.instance, msg)
        self.emit(force=True)

    def progress(self, done: int, total: int) -> None:
        self.done, self.total = done, total
        self.emit(force=done == total)

    def emit(self, force: bool = False) -> None:
        now = time.time()
        if force or now - self._last_emit > 0.15:
            self._last_emit = now
            self.tasks.app.hub.publish("task", self.as_dict())


class Tasks:
    def __init__(self, app: "App") -> None:
        self.app = app
        self.items: dict[str, Task] = {}

    def start(self, title: str, fn, instance: str | None = None) -> Task:
        task = Task(self, title, instance)
        self.items[task.id] = task
        task.emit(force=True)

        def worker():
            try:
                fn(task)
                task.status = "done"
            except Exception as e:
                traceback.print_exc()
                task.status = "error"
                task.message = str(e)
                if task.instance:
                    self.app.add_log(task.instance, f"Erro: {e}")
            task.emit(force=True)
            self.app.hub.publish("state", None)
            threading.Timer(30, lambda: self.items.pop(task.id, None)).start()

        threading.Thread(target=worker, daemon=True).start()
        return task

    def busy(self, instance: str) -> bool:
        return any(t.instance == instance and t.status == "running" for t in self.items.values())


# ---------------------------------------------------------------------------
# Estado da aplicação
# ---------------------------------------------------------------------------

def _loader_label(loader: str) -> str:
    return {"vanilla": "Vanilla", "fabric": "Fabric", "quilt": "Quilt",
            "forge": "Forge", "neoforge": "NeoForge"}.get(loader, loader)


def instance_dict(inst: Instance, running: bool = False) -> dict:
    mods = instances.list_mods(inst)
    return {
        "id": inst.dir.name, "name": inst.name, "minecraft": inst.minecraft,
        "loader": inst.loader, "loader_label": _loader_label(inst.loader),
        "loader_version": inst.loader_version, "pack": {k: v for k, v in inst.pack.items() if k != "files"},
        "memory_mb": inst.memory_mb, "effective_memory": inst.effective_memory,
        "java_path": inst.java_path, "jvm_args": inst.jvm_args, "width": inst.width, "height": inst.height,
        "last_played": inst.last_played, "playtime": inst.playtime, "created": inst.created,
        "mods_total": len(mods), "mods_enabled": sum(m["enabled"] for m in mods), "running": running,
    }


class App:
    def __init__(self) -> None:
        self.hub = Hub()
        self.tasks = Tasks(self)
        self.running: dict[str, subprocess.Popen] = {}
        self.logs: dict[str, deque] = {}
        self.token = secrets.token_urlsafe(24)
        self.login_cancel: threading.Event | None = None

    def add_log(self, inst_id: str, line: str) -> None:
        self.logs.setdefault(inst_id, deque(maxlen=3000)).append(line)
        self.hub.publish("log", {"instance": inst_id, "line": line})

    def get_instance(self, inst_id: str) -> Instance:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", inst_id) or inst_id in (".", ".."):
            raise KeyError(inst_id)
        directory = paths.instances_dir() / inst_id
        if not (directory / "instance.json").is_file():
            raise KeyError(f"Instância não encontrada: {inst_id}")
        return instances.load(directory)

    def state(self) -> dict:
        default = auth.get_default()
        accounts = [{k: a[k] for k in ("name", "uuid", "type")} for a in auth.list_accounts()]
        cfg = settings.load()
        return {
            "version": __version__,
            "instances": [instance_dict(i, i.dir.name in self.running) for i in instances.list_all()],
            "accounts": accounts,
            "default_account": default["uuid"] if default else None,
            "tasks": [t.as_dict() for t in self.tasks.items.values()],
            "settings": {k: cfg.get(k) for k in ("default_memory_mb", "download_workers", "msa_client_id",
                                                  "auto_download_java", "java_paths")},
            "data_dir": str(paths.root()),
        }

    # ------------------------------------------------------------ ações
    def launch(self, inst_id: str) -> dict:
        if inst_id in self.running:
            raise ValueError("A instância já está em execução")
        if self.tasks.busy(inst_id):
            raise ValueError("Aguarde a tarefa em andamento terminar")
        inst = self.get_instance(inst_id)
        account = auth.get_default()
        if not account:
            raise ValueError("Adicione uma conta antes de jogar")
        self.logs[inst_id] = deque(maxlen=3000)

        def on_exit(code: int) -> None:
            self.running.pop(inst_id, None)
            self.hub.publish("state", None)
            self.hub.publish("exit", {"instance": inst_id, "code": code})

        def run(task: Task) -> None:
            proc = launch.launch(inst, account, lambda m: self.add_log(inst_id, m), task.progress, on_exit)
            if proc.poll() is None:
                self.running[inst_id] = proc
            task.log("Jogo iniciado")

        return self.tasks.start(f"Iniciando {inst.name}", run, inst_id).as_dict()

    def stop(self, inst_id: str) -> None:
        proc = self.running.get(inst_id)
        if proc:
            proc.terminate()

    def install(self, project: str, version: str | None, name: str | None, title: str) -> dict:
        def run(task: Task) -> None:
            inst = modrinth.install_pack(project, version, name, task.log, task.progress)
            task.instance = inst.dir.name
            task.log(f"{inst.name} instalado!")
        return self.tasks.start(f"Instalando {title}", run).as_dict()

    def import_pack(self, data: bytes, filename: str) -> dict:
        tmp_dir = Path(tempfile.mkdtemp(dir=paths.cache_dir()))
        path = tmp_dir / (Path(filename).name or "pack.mrpack")
        path.write_bytes(data)

        def run(task: Task) -> None:
            try:
                inst = modrinth.import_mrpack(path, None, task.log, task.progress)
                task.instance = inst.dir.name
                task.log(f"{inst.name} importado!")
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        return self.tasks.start(f"Importando {path.name}", run).as_dict()

    def update(self, inst_id: str, version_id: str | None) -> dict:
        inst = self.get_instance(inst_id)
        return self.tasks.start(f"Atualizando {inst.name}",
                                lambda t: modrinth.update_pack(inst, version_id, t.log, t.progress),
                                inst_id).as_dict()

    def add_project(self, inst_id: str, project: str, title: str) -> dict:
        inst = self.get_instance(inst_id)
        return self.tasks.start(f"Adicionando {title}", lambda t: modrinth.add_project(inst, project, t.log),
                                inst_id).as_dict()

    def login_microsoft(self) -> dict:
        self.login_cancel = cancel = threading.Event()

        def show(url: str, code: str) -> None:
            self.hub.publish("login", {"url": url, "code": code})

        def run(task: Task) -> None:
            acc = auth.login_microsoft(show, cancel.is_set)
            task.log(f"Logado como {acc['name']}")
            self.hub.publish("login", {"done": True, "name": acc["name"]})
        return self.tasks.start("Login Microsoft", run).as_dict()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


ROUTES: list[tuple[str, re.Pattern, str]] = []


def route(method: str, pattern: str):
    def deco(fn):
        ROUTES.append((method, re.compile(f"^{pattern}$"), fn.__name__))
        return fn
    return deco


class Handler(BaseHTTPRequestHandler):
    app: App
    port: int
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args) -> None:  # silencioso
        pass

    # ------------------------------------------------------------ helpers
    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        self._send(status, json.dumps(data).encode(), "application/json; charset=utf-8")

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _json_body(self) -> dict:
        raw = self._body()
        return json.loads(raw) if raw else {}

    def _host_ok(self) -> bool:
        # Evita DNS rebinding: só aceita o host local exato
        return self.headers.get("Host") in (f"127.0.0.1:{self.port}", f"localhost:{self.port}")

    def _authorized(self, query: dict) -> bool:
        token = self.headers.get("X-Token") or query.get("t", [""])[0]
        return secrets.compare_digest(token, self.app.token)

    # ------------------------------------------------------------ dispatch
    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        if not self._host_ok():
            self._send(403, b"forbidden", "text/plain")
            return
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path
        if not path.startswith("/api/"):
            if method == "GET":
                self._static(path)
            else:
                self._send(405, b"", "text/plain")
            return
        if not self._authorized(query):
            self._json({"error": "não autorizado"}, 401)
            return
        for m, pattern, name in ROUTES:
            match = pattern.match(path)
            if m == method and match:
                try:
                    getattr(self, name)(query, *match.groups())
                except ApiError as e:
                    self._json({"error": str(e)}, e.status)
                except KeyError as e:
                    self._json({"error": str(e).strip("'")}, 404)
                except Exception as e:
                    traceback.print_exc()
                    self._json({"error": str(e)}, 400)
                return
        self._json({"error": "rota não encontrada"}, 404)

    def _static(self, path: str) -> None:
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (WEB_DIR / rel).resolve()
        if WEB_DIR.resolve() not in target.parents or not target.is_file():
            self._send(404, b"not found", "text/plain")
            return
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    # ------------------------------------------------------------ rotas
    @route("GET", "/api/events")
    def events(self, query) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = self.app.hub.subscribe()
        try:
            self.wfile.write(b"event: hello\ndata: {}\n\n")
            self.wfile.flush()
            while True:
                try:
                    event, data = q.get(timeout=15)
                    chunk = f"event: {event}\ndata: {json.dumps(data)}\n\n"
                except queue.Empty:
                    chunk = ": ping\n\n"
                self.wfile.write(chunk.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.app.hub.unsubscribe(q)
            self.close_connection = True

    @route("GET", "/api/state")
    def get_state(self, query) -> None:
        self._json(self.app.state())

    @route("GET", r"/api/instances/([^/]+)")
    def get_instance(self, query, inst_id) -> None:
        inst = self.app.get_instance(inst_id)
        data = instance_dict(inst, inst_id in self.app.running)
        data["mods"] = [{"file": m["file"], "enabled": m["enabled"], "from_pack": m["from_pack"],
                         "size": m["path"].stat().st_size} for m in instances.list_mods(inst)]
        data["logs"] = list(self.app.logs.get(inst_id, []))
        data["game_dir"] = str(inst.game_dir)
        self._json(data)

    @route("POST", "/api/instances")
    def create_instance(self, query) -> None:
        body = self._json_body()
        name, mc, loader = body.get("name", "").strip(), body.get("minecraft", ""), body.get("loader", "vanilla")
        if not name or not mc:
            raise ApiError(400, "Informe nome e versão")
        if loader not in loaders.LOADERS:
            raise ApiError(400, "Loader inválido")
        inst = instances.create(name, mc, loader, body.get("loader_version") or None)
        self.app.hub.publish("state", None)
        self._json({"id": inst.dir.name})

    @route("POST", r"/api/instances/([^/]+)/launch")
    def launch_instance(self, query, inst_id) -> None:
        try:
            self._json(self.app.launch(inst_id))
        except ValueError as e:
            raise ApiError(409, str(e))

    @route("POST", r"/api/instances/([^/]+)/stop")
    def stop_instance(self, query, inst_id) -> None:
        self.app.stop(inst_id)
        self._json({"ok": True})

    @route("POST", r"/api/instances/([^/]+)/settings")
    def save_instance(self, query, inst_id) -> None:
        inst = self.app.get_instance(inst_id)
        body = self._json_body()
        if body.get("name", "").strip():
            inst.name = body["name"].strip()
        for key in ("memory_mb", "width", "height"):
            if key in body:
                inst.__setattr__(key, max(0, int(body[key] or 0)))
        for key in ("java_path", "jvm_args"):
            if key in body:
                inst.__setattr__(key, str(body[key]).strip())
        inst.save()
        self.app.hub.publish("state", None)
        self._json({"ok": True})

    @route("POST", r"/api/instances/([^/]+)/delete")
    def delete_instance(self, query, inst_id) -> None:
        if inst_id in self.app.running:
            raise ApiError(409, "Feche o jogo antes de excluir")
        instances.delete(self.app.get_instance(inst_id))
        self.app.hub.publish("state", None)
        self._json({"ok": True})

    @route("POST", r"/api/instances/([^/]+)/duplicate")
    def duplicate_instance(self, query, inst_id) -> None:
        src = self.app.get_instance(inst_id)
        copy = instances.create(f"{src.name} (cópia)", src.minecraft, src.loader, src.loader_version)
        shutil.rmtree(copy.dir)
        shutil.copytree(src.dir, copy.dir, ignore=shutil.ignore_patterns("logs"))
        dup = instances.load(copy.dir)
        dup.name, dup.playtime, dup.last_played = copy.name, 0, 0
        dup.save()
        self.app.hub.publish("state", None)
        self._json({"id": dup.dir.name})

    @route("POST", r"/api/instances/([^/]+)/open-folder")
    def open_folder(self, query, inst_id) -> None:
        inst = self.app.get_instance(inst_id)
        sub = self._json_body().get("sub", "")
        folder = inst.game_dir / sub if sub in ("", "mods", "config", "saves", "resourcepacks",
                                                "shaderpacks", "screenshots", "logs") else inst.game_dir
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])
        self._json({"ok": True})

    @route("POST", r"/api/instances/([^/]+)/mods/toggle")
    def toggle_mod(self, query, inst_id) -> None:
        body = self._json_body()
        new = instances.set_mod_enabled(self.app.get_instance(inst_id), body["file"], bool(body["enabled"]))
        self._json({"file": new})

    @route("POST", r"/api/instances/([^/]+)/mods/delete")
    def delete_mod(self, query, inst_id) -> None:
        inst = self.app.get_instance(inst_id)
        name = self._json_body()["file"]
        target = inst.mods_dir / Path(name).name
        if target.is_file():
            target.unlink()
        self._json({"ok": True})

    @route("POST", r"/api/instances/([^/]+)/mods/add")
    def add_mod(self, query, inst_id) -> None:
        body = self._json_body()
        self._json(self.app.add_project(inst_id, body["project"], body.get("title") or body["project"]))

    @route("GET", r"/api/instances/([^/]+)/update")
    def check_update(self, query, inst_id) -> None:
        latest = modrinth.check_update(self.app.get_instance(inst_id))
        self._json({"latest": latest and {"id": latest["id"], "version_number": latest["version_number"]}})

    @route("POST", r"/api/instances/([^/]+)/update")
    def update_instance(self, query, inst_id) -> None:
        self._json(self.app.update(inst_id, self._json_body().get("version_id")))

    @route("GET", r"/api/instances/([^/]+)/export")
    def export_instance(self, query, inst_id) -> None:
        inst = self.app.get_instance(inst_id)
        version = query.get("version", ["1.0.0"])[0]
        tmp_dir = Path(tempfile.mkdtemp(dir=paths.cache_dir()))
        try:
            out = modrinth.export_mrpack(inst, tmp_dir / "pack.mrpack", version,
                                         log=lambda m: self.app.add_log(inst_id, m))
            filename = re.sub(r"[^A-Za-z0-9._ -]+", "_", f"{inst.name}-{version}.mrpack")
            self._send(200, out.read_bytes(), "application/x-modrinth-modpack+zip",
                       {"Content-Disposition": f'attachment; filename="{filename}"'})
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @route("POST", "/api/import")
    def import_pack(self, query) -> None:
        filename = urllib.parse.unquote(self.headers.get("X-Filename", "pack.mrpack"))
        self._json(self.app.import_pack(self._body(), filename))

    @route("GET", "/api/search")
    def search(self, query) -> None:
        q = {k: v[0] for k, v in query.items()}
        self._json(modrinth.search(q.get("q", ""), q.get("type", "modpack"), q.get("mc") or None,
                                   q.get("loader") or None, int(q.get("limit", 24)), int(q.get("offset", 0))))

    @route("GET", r"/api/project/([^/]+)")
    def project(self, query, pid) -> None:
        self._json(modrinth.get_project(pid))

    @route("GET", r"/api/project/([^/]+)/versions")
    def project_versions(self, query, pid) -> None:
        loader = query.get("loader", [None])[0]
        mc = query.get("mc", [None])[0]
        self._json(modrinth.get_versions(pid, [loader] if loader else None, [mc] if mc else None))

    @route("POST", "/api/install")
    def install(self, query) -> None:
        body = self._json_body()
        self._json(self.app.install(body["project"], body.get("version_id"), body.get("name") or None,
                                    body.get("title") or body["project"]))

    @route("GET", "/api/mc-versions")
    def mc_versions(self, query) -> None:
        self._json(minecraft.list_versions("snapshots" in query))

    @route("GET", "/api/loader-versions")
    def loader_versions(self, query) -> None:
        self._json(loaders.list_versions(query["loader"][0], query["mc"][0]))

    @route("POST", "/api/accounts/offline")
    def add_offline(self, query) -> None:
        try:
            acc = auth.add_offline(self._json_body().get("name", "").strip())
        except auth.AuthError as e:
            raise ApiError(400, str(e))
        auth.set_default(acc["uuid"])
        self.app.hub.publish("state", None)
        self._json({"ok": True})

    @route("POST", "/api/accounts/microsoft")
    def login_microsoft(self, query) -> None:
        if not settings.get("msa_client_id"):
            raise ApiError(400, "Configure o Client ID do Azure em Configurações para usar contas Microsoft")
        self._json(self.app.login_microsoft())

    @route("POST", "/api/accounts/microsoft/cancel")
    def cancel_login(self, query) -> None:
        if self.app.login_cancel:
            self.app.login_cancel.set()
        self._json({"ok": True})

    @route("POST", "/api/accounts/default")
    def default_account(self, query) -> None:
        auth.set_default(self._json_body()["uuid"])
        self.app.hub.publish("state", None)
        self._json({"ok": True})

    @route("POST", "/api/accounts/remove")
    def remove_account(self, query) -> None:
        auth.remove(self._json_body()["uuid"])
        self.app.hub.publish("state", None)
        self._json({"ok": True})

    @route("POST", "/api/settings")
    def save_settings(self, query) -> None:
        body = self._json_body()
        data = settings.load()
        if "default_memory_mb" in body:
            data["default_memory_mb"] = max(512, int(body["default_memory_mb"]))
        if "download_workers" in body:
            data["download_workers"] = min(32, max(1, int(body["download_workers"])))
        if "msa_client_id" in body:
            data["msa_client_id"] = str(body["msa_client_id"]).strip()
        if "auto_download_java" in body:
            data["auto_download_java"] = bool(body["auto_download_java"])
        if "java_paths" in body:
            data["java_paths"] = {str(k): str(v) for k, v in body["java_paths"].items() if v}
        settings.save(data)
        self.app.hub.publish("state", None)
        self._json({"ok": True})

    @route("GET", "/api/java")
    def list_java(self, query) -> None:
        found = [{"path": c, "major": java.probe(c)} for c in java.candidates()]
        self._json([f for f in found if f["major"]])

    @route("POST", "/api/open-data-dir")
    def open_data_dir(self, query) -> None:
        folder = paths.root()
        if sys.platform == "win32":
            os.startfile(folder)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])
        self._json({"ok": True})


# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------

def _app_browser() -> str | None:
    """Encontra um navegador Chromium para abrir a interface como janela de app."""
    names = ["msedge", "chrome", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
             "brave-browser", "brave"]
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                     os.environ.get("LOCALAPPDATA", "")):
            for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe",
                        r"BraveSoftware\Brave-Browser\Application\brave.exe"):
                p = Path(base) / rel
                if base and p.is_file():
                    return str(p)
    if sys.platform == "darwin":
        for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium"):
            if os.path.isfile(p):
                return p
    return None


def serve(port: int = 0) -> tuple[ThreadingHTTPServer, App]:
    app = App()
    handler = type("BoundHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    handler.port = server.server_address[1]
    return server, app


def main(open_window: bool = True, port: int = 0) -> int:
    server, app = serve(port)
    url = f"http://127.0.0.1:{server.server_address[1]}/#t={app.token}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"PackLauncher {__version__} rodando em {url}")
    print("Feche a janela do launcher (ou Ctrl+C) para sair.")

    window = None
    if open_window:
        browser = _app_browser()
        if browser:
            profile = paths.root() / "ui-profile"
            window = subprocess.Popen([browser, f"--app={url}", f"--user-data-dir={profile}",
                                       "--window-size=1280,800", "--no-first-run",
                                       "--no-default-browser-check"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            webbrowser.open(url)
    try:
        started = time.time()
        if window:
            window.wait()
        if not window or time.time() - started < 5:
            # Sem janela própria (ou o navegador repassou a janela a um processo já aberto):
            # encerra quando nenhuma aba estiver conectada por 20s
            while True:
                time.sleep(2)
                idle = not app.hub.clients and time.time() - app.hub.last_disconnect > 20
                if open_window and idle and not app.running:
                    break
        while app.running:  # não derruba jogos abertos (a saída deles passa pelo launcher)
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    server.shutdown()
    return 0
