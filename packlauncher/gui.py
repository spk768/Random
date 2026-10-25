"""Interface gráfica (tkinter)."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import __version__, auth, instances, launch, loaders, minecraft, modrinth
from .instances import Instance


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _human(n: int) -> str:
    for unit in ("", "K", "M"):
        if n < 1000:
            return f"{n}{unit}"
        n //= 1000
    return f"{n}B"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"PackLauncher {__version__}")
        self.geometry("1000x640")
        self.minsize(820, 520)
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.running: dict[str, subprocess.Popen] = {}
        self._build()
        self.refresh_instances()
        self.refresh_accounts()
        self.after(50, self._drain_events)

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Play.TButton", font=("TkDefaultFont", 12, "bold"), padding=8)
        style.configure("Title.TLabel", font=("TkDefaultFont", 15, "bold"))

        bar = ttk.Frame(self, padding=(8, 8, 8, 4))
        bar.pack(fill="x")
        ttk.Button(bar, text="🔎 Buscar modpacks", command=lambda: SearchDialog(self)).pack(side="left")
        ttk.Button(bar, text="📦 Importar .mrpack", command=self.import_mrpack).pack(side="left", padx=4)
        ttk.Button(bar, text="➕ Nova instância", command=lambda: NewInstanceDialog(self)).pack(side="left")
        ttk.Button(bar, text="👤 Contas", command=lambda: AccountsDialog(self)).pack(side="right")
        self.account_var = tk.StringVar()
        self.account_box = ttk.Combobox(bar, textvariable=self.account_var, state="readonly", width=18)
        self.account_box.pack(side="right", padx=4)
        self.account_box.bind("<<ComboboxSelected>>", self._account_selected)
        ttk.Label(bar, text="Conta:").pack(side="right")

        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(fill="both", expand=True, padx=8)
        top = ttk.PanedWindow(paned, orient="horizontal")
        paned.add(top, weight=3)

        left = ttk.Frame(top)
        top.add(left, weight=2)
        self.tree = ttk.Treeview(left, columns=("versao", "pack"), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Instância")
        self.tree.heading("versao", text="Versão")
        self.tree.heading("pack", text="Modpack")
        self.tree.column("#0", width=200)
        self.tree.column("versao", width=180)
        self.tree.column("pack", width=120)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_details())
        self.tree.bind("<Double-1>", lambda e: self.play())

        right = ttk.Frame(top, padding=10)
        top.add(right, weight=1)
        self.title_lbl = ttk.Label(right, text="Selecione uma instância", style="Title.TLabel", wraplength=300)
        self.title_lbl.pack(anchor="w")
        self.info_lbl = ttk.Label(right, text="", justify="left", wraplength=300)
        self.info_lbl.pack(anchor="w", pady=(4, 12))
        self.play_btn = ttk.Button(right, text="▶  Jogar", style="Play.TButton", command=self.play)
        self.play_btn.pack(fill="x", pady=(0, 8))
        self.action_buttons = []
        for text, cmd in (("⟳ Atualizar modpack", self.update_pack), ("🧩 Mods", self.open_mods),
                          ("📁 Abrir pasta", self.open_instance_folder), ("⚙ Configurações", self.edit_instance),
                          ("💾 Exportar .mrpack", self.export_pack), ("🗑 Excluir", self.delete_instance)):
            btn = ttk.Button(right, text=text, command=cmd)
            btn.pack(fill="x", pady=2)
            self.action_buttons.append(btn)

        bottom = ttk.Frame(paned)
        paned.add(bottom, weight=1)
        status = ttk.Frame(bottom)
        status.pack(fill="x", pady=(6, 2))
        self.status_var = tk.StringVar(value="Pronto")
        ttk.Label(status, textvariable=self.status_var).pack(side="left")
        self.progress = ttk.Progressbar(status, length=260, mode="determinate")
        self.progress.pack(side="right")
        log_frame = ttk.Frame(bottom)
        log_frame.pack(fill="both", expand=True, pady=(0, 8))
        self.log_text = tk.Text(log_frame, height=8, wrap="none", state="disabled",
                                background="#1e1e1e", foreground="#d4d4d4", font=("TkFixedFont", 9))
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)
        self.show_details()

    # ------------------------------------------------------------- threading
    def log(self, msg: str) -> None:
        """Seguro para chamar de qualquer thread."""
        self.events.put(("log", msg))

    def set_progress(self, done: int, total: int) -> None:
        self.events.put(("progress", (done, total)))

    def call(self, fn, *args) -> None:
        """Agenda fn(*args) na thread da interface."""
        self.events.put(("call", (fn, args)))

    def _drain_events(self) -> None:
        lines = []
        try:
            for _ in range(500):
                kind, data = self.events.get_nowait()
                if kind == "log":
                    lines.append(data)
                elif kind == "progress":
                    done, total = data
                    self.progress["maximum"] = max(total, 1)
                    self.progress["value"] = done
                elif kind == "call":
                    fn, args = data
                    fn(*args)
        except queue.Empty:
            pass
        if lines:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", "\n".join(lines) + "\n")
            excess = int(self.log_text.index("end-1c").split(".")[0]) - 3000
            if excess > 0:
                self.log_text.delete("1.0", f"{excess}.0")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
            self.status_var.set(lines[-1][:90])
        self.after(50, self._drain_events)

    def run_task(self, label: str, fn, on_done=None) -> None:
        if self.busy:
            messagebox.showinfo("Aguarde", "Já existe uma tarefa em andamento.")
            return
        self.busy = True
        self.status_var.set(label)
        self.progress["value"] = 0
        self.log(label)

        def worker():
            try:
                result = fn()
            except Exception as e:  # mostra qualquer falha ao usuário
                self.log(f"Erro: {e}")
                self.call(messagebox.showerror, "Erro", str(e))
                result = None
                ok = False
            else:
                ok = True
            self.call(self._task_finished, on_done if ok else None, result)

        threading.Thread(target=worker, daemon=True).start()

    def _task_finished(self, on_done, result) -> None:
        self.busy = False
        self.status_var.set("Pronto")
        self.refresh_instances()
        if on_done:
            on_done(result)

    # ---------------------------------------------------------- instâncias
    def selected(self) -> Instance | None:
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return instances.load(Path(sel[0]))
        except (OSError, ValueError):
            return None

    def refresh_instances(self, select: str | None = None) -> None:
        current = select or (self.tree.selection() or [None])[0]
        self.tree.delete(*self.tree.get_children())
        for inst in instances.list_all():
            pack = inst.pack.get("version_number") or ("—" if not inst.pack else "")
            self.tree.insert("", "end", iid=str(inst.dir), text=inst.name, values=(inst.describe(), pack))
        if current and self.tree.exists(current):
            self.tree.selection_set(current)
        elif self.tree.get_children():
            self.tree.selection_set(self.tree.get_children()[0])
        self.show_details()

    def show_details(self) -> None:
        inst = self.selected()
        state = "normal" if inst else "disabled"
        for btn in [self.play_btn, *self.action_buttons]:
            btn.configure(state=state)
        if not inst:
            self.title_lbl.configure(text="Nenhuma instância")
            self.info_lbl.configure(text="Use “Buscar modpacks” para instalar um modpack do Modrinth.")
            return
        mods = instances.list_mods(inst)
        active = sum(m["enabled"] for m in mods)
        lines = [inst.describe()]
        if inst.pack.get("title"):
            lines.append(f"Modpack: {inst.pack['title']} {inst.pack.get('version_number', '')}")
        lines.append(f"Mods: {active} ativos de {len(mods)}")
        lines.append(f"Memória: {inst.effective_memory} MB")
        lines.append(f"Tempo de jogo: {inst.playtime / 3600:.1f} h")
        if inst.last_played:
            lines.append("Última vez: " + time.strftime("%d/%m/%Y %H:%M", time.localtime(inst.last_played)))
        self.title_lbl.configure(text=inst.name)
        self.info_lbl.configure(text="\n".join(lines))
        running = str(inst.dir) in self.running
        self.play_btn.configure(text="■  Fechar jogo" if running else "▶  Jogar")
        self.action_buttons[0].configure(state="normal" if inst.pack.get("source") == "modrinth" else "disabled")

    def play(self) -> None:
        inst = self.selected()
        if not inst:
            return
        key = str(inst.dir)
        if key in self.running:
            if messagebox.askyesno("Fechar", "Forçar o fechamento do jogo?"):
                self.running[key].terminate()
            return
        account = self.current_account()
        if not account:
            messagebox.showinfo("Conta", "Adicione uma conta antes de jogar.")
            AccountsDialog(self)
            return

        def on_exit(code: int) -> None:
            self.call(self._game_exited, key, code)

        def task():
            return launch.launch(inst, account, self.log, self.set_progress, on_exit)

        def started(proc):
            if proc.poll() is None:
                self.running[key] = proc
            self.show_details()

        self.run_task(f"Iniciando {inst.name}...", task, started)

    def _game_exited(self, key: str, code: int) -> None:
        self.running.pop(key, None)
        self.refresh_instances()
        if code not in (0, 1, 130, 143, -15):
            messagebox.showwarning("Minecraft", f"O jogo fechou com erro (código {code}). Veja o log abaixo.")

    def update_pack(self) -> None:
        inst = self.selected()
        if not inst:
            return

        def check():
            return modrinth.check_update(inst)

        def checked(latest):
            if not latest:
                messagebox.showinfo("Atualizado", "O modpack já está na versão mais recente.")
                return
            if messagebox.askyesno("Atualização", f"Atualizar {inst.name} para {latest['version_number']}?\n\n"
                                                  "Mundos e configurações pessoais são mantidos."):
                self.run_task("Atualizando modpack...",
                              lambda: modrinth.update_pack(inst, latest["id"], self.log, self.set_progress))

        self.run_task("Verificando atualizações...", check, checked)

    def open_mods(self) -> None:
        inst = self.selected()
        if inst:
            ModsDialog(self, inst)

    def open_instance_folder(self) -> None:
        inst = self.selected()
        if inst:
            open_folder(inst.game_dir)

    def edit_instance(self) -> None:
        inst = self.selected()
        if inst:
            InstanceSettingsDialog(self, inst)

    def export_pack(self) -> None:
        inst = self.selected()
        if not inst:
            return
        version = simpledialog.askstring("Exportar", "Versão do modpack:", initialvalue="1.0.0", parent=self)
        if not version:
            return
        out = filedialog.asksaveasfilename(defaultextension=".mrpack", initialfile=f"{inst.name}-{version}.mrpack",
                                           filetypes=[("Modrinth modpack", "*.mrpack")])
        if out:
            self.run_task("Exportando...", lambda: modrinth.export_mrpack(inst, Path(out), version, log=self.log),
                          lambda p: messagebox.showinfo("Exportado", f"Salvo em {p}"))

    def delete_instance(self) -> None:
        inst = self.selected()
        if inst and messagebox.askyesno("Excluir", f"Excluir “{inst.name}”?\nMundos e configurações serão "
                                                   "apagados permanentemente.", icon="warning"):
            instances.delete(inst)
            self.refresh_instances()

    def import_mrpack(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Modrinth modpack", "*.mrpack"), ("Todos", "*.*")])
        if path:
            self.run_task("Importando modpack...",
                          lambda: modrinth.import_mrpack(Path(path), log=self.log, progress=self.set_progress),
                          lambda inst: self.refresh_instances(str(inst.dir)))

    # -------------------------------------------------------------- contas
    def refresh_accounts(self) -> None:
        accounts = auth.list_accounts()
        self.account_box["values"] = [a["name"] for a in accounts]
        default = auth.get_default()
        self.account_var.set(default["name"] if default else "")

    def _account_selected(self, _event=None) -> None:
        acc = auth.find(self.account_var.get())
        if acc:
            auth.set_default(acc["uuid"])

    def current_account(self) -> dict | None:
        return auth.find(self.account_var.get()) if self.account_var.get() else auth.get_default()


# ---------------------------------------------------------------------------
# Diálogos
# ---------------------------------------------------------------------------

class Dialog(tk.Toplevel):
    def __init__(self, app: App, title: str, size: str = "") -> None:
        super().__init__(app)
        self.app = app
        self.title(title)
        if size:
            self.geometry(size)
        self.transient(app)
        self.body = ttk.Frame(self, padding=10)
        self.body.pack(fill="both", expand=True)


class SearchDialog(Dialog):
    def __init__(self, app: App) -> None:
        super().__init__(app, "Buscar modpacks no Modrinth", "900x560")
        top = ttk.Frame(self.body)
        top.pack(fill="x")
        self.query = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.query)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self.search())
        entry.focus_set()
        ttk.Label(top, text=" MC:").pack(side="left")
        self.mc = tk.StringVar()
        ttk.Entry(top, textvariable=self.mc, width=9).pack(side="left")
        ttk.Label(top, text=" Loader:").pack(side="left")
        self.loader = tk.StringVar(value="")
        ttk.Combobox(top, textvariable=self.loader, values=["", "fabric", "quilt", "forge", "neoforge"],
                     state="readonly", width=9).pack(side="left")
        ttk.Button(top, text="Buscar", command=self.search).pack(side="left", padx=(6, 0))

        self.results = ttk.Treeview(self.body, columns=("downloads", "autor", "desc"), show="tree headings")
        self.results.heading("#0", text="Modpack")
        self.results.heading("downloads", text="Downloads")
        self.results.heading("autor", text="Autor")
        self.results.heading("desc", text="Descrição")
        self.results.column("#0", width=200)
        self.results.column("downloads", width=80, anchor="e")
        self.results.column("autor", width=110)
        self.results.column("desc", width=440)
        self.results.pack(fill="both", expand=True, pady=8)
        self.results.bind("<<TreeviewSelect>>", lambda e: self.load_versions())

        bottom = ttk.Frame(self.body)
        bottom.pack(fill="x")
        ttk.Label(bottom, text="Versão:").pack(side="left")
        self.version_var = tk.StringVar()
        self.version_box = ttk.Combobox(bottom, textvariable=self.version_var, state="readonly", width=60)
        self.version_box.pack(side="left", padx=4)
        ttk.Button(bottom, text="Abrir no site", command=self.open_page).pack(side="right")
        self.install_btn = ttk.Button(bottom, text="Instalar", command=self.install, state="disabled")
        self.install_btn.pack(side="right", padx=4)
        self.hits: dict[str, dict] = {}
        self.versions: list[dict] = []
        self.search()

    def _bg(self, fn, done) -> None:
        def worker():
            try:
                result = fn()
            except Exception as e:
                self.app.call(lambda msg=str(e): messagebox.showerror("Erro", msg, parent=self))
                return
            self.app.call(lambda: self.winfo_exists() and done(result))
        threading.Thread(target=worker, daemon=True).start()

    def search(self) -> None:
        q, mc, loader = self.query.get(), self.mc.get().strip() or None, self.loader.get() or None
        self._bg(lambda: modrinth.search(q, game_version=mc, loader=loader, limit=40), self._show_results)

    def _show_results(self, res: dict) -> None:
        self.results.delete(*self.results.get_children())
        self.hits = {h["project_id"]: h for h in res["hits"]}
        for h in res["hits"]:
            self.results.insert("", "end", iid=h["project_id"], text=h["title"],
                                values=(_human(h["downloads"]), h.get("author", ""), h["description"]))

    def _selected_hit(self) -> dict | None:
        sel = self.results.selection()
        return self.hits.get(sel[0]) if sel else None

    def load_versions(self) -> None:
        hit = self._selected_hit()
        if not hit:
            return
        self.install_btn.configure(state="disabled")
        self.version_box["values"] = ["Carregando..."]
        self.version_var.set("Carregando...")
        pid = hit["project_id"]
        self._bg(lambda: modrinth.get_versions(pid), lambda vs: self._show_versions(pid, vs))

    def _show_versions(self, pid: str, versions: list[dict]) -> None:
        hit = self._selected_hit()
        if not hit or hit["project_id"] != pid:
            return
        self.versions = versions
        labels = [f"{v['version_number']}  —  MC {', '.join(v['game_versions'])}  "
                  f"[{', '.join(v['loaders'])}]  {v['version_type']}" for v in versions]
        self.version_box["values"] = labels
        if labels:
            self.version_box.current(0)
            self.install_btn.configure(state="normal")
        else:
            self.version_var.set("Sem versões")

    def open_page(self) -> None:
        hit = self._selected_hit()
        if hit:
            webbrowser.open(f"https://modrinth.com/modpack/{hit['slug']}")

    def install(self) -> None:
        hit = self._selected_hit()
        idx = self.version_box.current()
        if not hit or idx < 0 or idx >= len(self.versions):
            return
        version = self.versions[idx]
        name = simpledialog.askstring("Instalar", "Nome da instância:",
                                      initialvalue=instances.unique_name(hit["title"]), parent=self)
        if not name:
            return
        self.destroy()
        self.app.run_task(f"Instalando {hit['title']} {version['version_number']}...",
                          lambda: modrinth.install_pack(hit["project_id"], version["id"], name,
                                                        self.app.log, self.app.set_progress),
                          lambda inst: self.app.refresh_instances(str(inst.dir)))


class NewInstanceDialog(Dialog):
    def __init__(self, app: App) -> None:
        super().__init__(app, "Nova instância")
        self.resizable(False, False)
        grid = self.body
        self.name = tk.StringVar(value="Nova instância")
        self.mc = tk.StringVar()
        self.loader = tk.StringVar(value="fabric")
        self.loader_version = tk.StringVar()
        self.snapshots = tk.BooleanVar(value=False)
        ttk.Label(grid, text="Nome:").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(grid, textvariable=self.name, width=34).grid(row=0, column=1, sticky="we")
        ttk.Label(grid, text="Minecraft:").grid(row=1, column=0, sticky="w", pady=3)
        self.mc_box = ttk.Combobox(grid, textvariable=self.mc, width=32)
        self.mc_box.grid(row=1, column=1, sticky="we")
        self.mc_box.bind("<<ComboboxSelected>>", lambda e: self.load_loader_versions())
        ttk.Checkbutton(grid, text="Snapshots", variable=self.snapshots,
                        command=self.load_mc_versions).grid(row=1, column=2, padx=4)
        ttk.Label(grid, text="Loader:").grid(row=2, column=0, sticky="w", pady=3)
        box = ttk.Combobox(grid, textvariable=self.loader, values=loaders.LOADERS, state="readonly", width=32)
        box.grid(row=2, column=1, sticky="we")
        box.bind("<<ComboboxSelected>>", lambda e: self.load_loader_versions())
        ttk.Label(grid, text="Versão do loader:").grid(row=3, column=0, sticky="w", pady=3)
        self.lv_box = ttk.Combobox(grid, textvariable=self.loader_version, width=32)
        self.lv_box.grid(row=3, column=1, sticky="we")
        ttk.Button(grid, text="Criar", command=self.create).grid(row=4, column=1, sticky="e", pady=(10, 0))
        self.load_mc_versions()

    def _bg(self, fn, done) -> None:
        def worker():
            try:
                result = fn()
            except Exception as e:
                self.app.log(f"Erro: {e}")
                result = []
            self.app.call(lambda: self.winfo_exists() and done(result))
        threading.Thread(target=worker, daemon=True).start()

    def load_mc_versions(self) -> None:
        snaps = self.snapshots.get()

        def done(versions):
            self.mc_box["values"] = versions
            if versions and self.mc.get() not in versions:
                self.mc.set(versions[0])
            self.load_loader_versions()
        self._bg(lambda: minecraft.list_versions(snaps), done)

    def load_loader_versions(self) -> None:
        loader, mc = self.loader.get(), self.mc.get()
        if loader == "vanilla" or not mc:
            self.lv_box["values"] = []
            self.loader_version.set("")
            return
        self.loader_version.set("Carregando...")

        def done(versions):
            if (loader, mc) != (self.loader.get(), self.mc.get()):
                return
            self.lv_box["values"] = versions
            self.loader_version.set(versions[0] if versions else "")
        self._bg(lambda: loaders.list_versions(loader, mc), done)

    def create(self) -> None:
        name, mc, loader = self.name.get().strip(), self.mc.get().strip(), self.loader.get()
        lv = self.loader_version.get().strip()
        if not name or not mc:
            messagebox.showwarning("Nova instância", "Preencha nome e versão.", parent=self)
            return
        if loader != "vanilla" and (not lv or lv == "Carregando..."):
            messagebox.showwarning("Nova instância", f"Nenhuma versão do {loader} para {mc}.", parent=self)
            return
        inst = instances.create(name, mc, loader, lv if loader != "vanilla" else None)
        self.destroy()
        self.app.refresh_instances(str(inst.dir))


class ModsDialog(Dialog):
    def __init__(self, app: App, inst: Instance) -> None:
        super().__init__(app, f"Mods — {inst.name}", "620x480")
        self.inst = inst
        self.tree = ttk.Treeview(self.body, columns=("ativo", "origem"), show="tree headings")
        self.tree.heading("#0", text="Arquivo")
        self.tree.heading("ativo", text="Ativo")
        self.tree.heading("origem", text="Origem")
        self.tree.column("#0", width=400)
        self.tree.column("ativo", width=60, anchor="center")
        self.tree.column("origem", width=90, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.toggle())
        bar = ttk.Frame(self.body)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="Ativar/Desativar", command=self.toggle).pack(side="left")
        ttk.Button(bar, text="Adicionar do Modrinth", command=self.add).pack(side="left", padx=4)
        ttk.Button(bar, text="Abrir pasta", command=lambda: open_folder(inst.mods_dir)).pack(side="left")
        ttk.Button(bar, text="Recarregar", command=self.refresh).pack(side="right")
        ttk.Label(self.body, text="Dica: duplo clique ativa/desativa. Mods desativados continuam "
                                  "desativados após atualizar o modpack.", foreground="gray").pack(anchor="w")
        self.refresh()

    def refresh(self) -> None:
        self.inst = instances.load(self.inst.dir)
        self.tree.delete(*self.tree.get_children())
        for m in instances.list_mods(self.inst):
            self.tree.insert("", "end", iid=m["file"], text=m["file"].removesuffix(".disabled"),
                             values=("✔" if m["enabled"] else "✘", "modpack" if m["from_pack"] else "manual"))

    def toggle(self) -> None:
        for iid in self.tree.selection():
            instances.set_mod_enabled(self.inst, iid, iid.endswith(".disabled"))
        self.refresh()
        self.app.show_details()

    def add(self) -> None:
        slug = simpledialog.askstring("Adicionar", "Slug ou ID do projeto no Modrinth\n"
                                                   "(mod, resource pack ou shader):", parent=self)
        if slug:
            self.app.run_task(f"Adicionando {slug}...",
                              lambda: modrinth.add_project(self.inst, slug.strip(), self.app.log),
                              lambda _: self.winfo_exists() and self.refresh())


class InstanceSettingsDialog(Dialog):
    def __init__(self, app: App, inst: Instance) -> None:
        super().__init__(app, f"Configurações — {inst.name}")
        self.resizable(False, False)
        self.inst = inst
        g = self.body
        self.name = tk.StringVar(value=inst.name)
        self.memory = tk.IntVar(value=inst.effective_memory)
        self.java = tk.StringVar(value=inst.java_path)
        self.jvm = tk.StringVar(value=inst.jvm_args)
        self.width = tk.IntVar(value=inst.width)
        self.height = tk.IntVar(value=inst.height)
        rows = [("Nome:", ttk.Entry(g, textvariable=self.name, width=40)),
                ("Memória (MB):", ttk.Spinbox(g, from_=1024, to=65536, increment=512, textvariable=self.memory)),
                ("Java (vazio = automático):", ttk.Entry(g, textvariable=self.java, width=40)),
                ("Argumentos JVM extras:", ttk.Entry(g, textvariable=self.jvm, width=40)),
                ("Largura da janela (0 = padrão):", ttk.Spinbox(g, from_=0, to=7680, textvariable=self.width)),
                ("Altura da janela:", ttk.Spinbox(g, from_=0, to=4320, textvariable=self.height))]
        for i, (label, widget) in enumerate(rows):
            ttk.Label(g, text=label).grid(row=i, column=0, sticky="w", pady=3)
            widget.grid(row=i, column=1, sticky="we")
        ttk.Button(g, text="…", width=3, command=self.browse_java).grid(row=2, column=2, padx=2)
        ttk.Button(g, text="Salvar", command=self.save).grid(row=len(rows), column=1, sticky="e", pady=(10, 0))

    def browse_java(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Executável do Java")
        if path:
            self.java.set(path)

    def save(self) -> None:
        try:
            memory, width, height = self.memory.get(), self.width.get(), self.height.get()
        except tk.TclError:
            messagebox.showwarning("Configurações", "Valores numéricos inválidos.", parent=self)
            return
        inst = instances.load(self.inst.dir)
        inst.name = self.name.get().strip() or inst.name
        inst.memory_mb, inst.width, inst.height = memory, width, height
        inst.java_path, inst.jvm_args = self.java.get().strip(), self.jvm.get().strip()
        inst.save()
        self.destroy()
        self.app.refresh_instances()


class AccountsDialog(Dialog):
    def __init__(self, app: App) -> None:
        super().__init__(app, "Contas", "460x320")
        self.list = ttk.Treeview(self.body, columns=("tipo",), show="tree headings", selectmode="browse")
        self.list.heading("#0", text="Nome")
        self.list.heading("tipo", text="Tipo")
        self.list.pack(fill="both", expand=True)
        bar = ttk.Frame(self.body)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="Login Microsoft", command=self.login_ms).pack(side="left")
        ttk.Button(bar, text="Conta offline", command=self.add_offline).pack(side="left", padx=4)
        ttk.Button(bar, text="Remover", command=self.remove).pack(side="right")
        ttk.Button(bar, text="Usar esta", command=self.make_default).pack(side="right", padx=4)
        self.refresh()

    def refresh(self) -> None:
        self.list.delete(*self.list.get_children())
        default = auth.get_default()
        for a in auth.list_accounts():
            star = "★ " if default and a["uuid"] == default["uuid"] else ""
            self.list.insert("", "end", iid=a["uuid"], text=star + a["name"],
                             values=("Microsoft" if a["type"] == "msa" else "Offline",))
        self.app.refresh_accounts()

    def add_offline(self) -> None:
        name = simpledialog.askstring("Conta offline", "Nome de jogador:", parent=self)
        if name:
            try:
                auth.add_offline(name.strip())
            except auth.AuthError as e:
                messagebox.showerror("Conta", str(e), parent=self)
            self.refresh()

    def make_default(self) -> None:
        sel = self.list.selection()
        if sel:
            auth.set_default(sel[0])
            self.refresh()

    def remove(self) -> None:
        sel = self.list.selection()
        if sel and messagebox.askyesno("Remover", "Remover esta conta?", parent=self):
            auth.remove(sel[0])
            self.refresh()

    def login_ms(self) -> None:
        cancelled = threading.Event()
        holder: dict = {}

        def show_code(url: str, code: str) -> None:
            def ui():
                win = Dialog(self.app, "Login Microsoft")
                holder["win"] = win
                ttk.Label(win.body, text=f"1. Abra {url}\n2. Digite o código abaixo:").pack(anchor="w")
                entry = ttk.Entry(win.body, font=("TkFixedFont", 18), justify="center")
                entry.insert(0, code)
                entry.configure(state="readonly")
                entry.pack(fill="x", pady=8)
                ttk.Button(win.body, text="Copiar código e abrir navegador",
                           command=lambda: (self.app.clipboard_clear(), self.app.clipboard_append(code),
                                            webbrowser.open(url))).pack(fill="x")
                ttk.Label(win.body, text="Aguardando confirmação...", foreground="gray").pack(pady=(6, 0))
                win.protocol("WM_DELETE_WINDOW", lambda: (cancelled.set(), win.destroy()))
            self.app.call(ui)

        def task():
            try:
                return auth.login_microsoft(show_code, cancelled.is_set)
            finally:
                self.app.call(lambda: holder.get("win") and holder["win"].winfo_exists()
                              and holder["win"].destroy())

        def done(acc):
            messagebox.showinfo("Login", f"Logado como {acc['name']}")
            if self.winfo_exists():
                self.refresh()
            else:
                self.app.refresh_accounts()

        self.app.run_task("Login Microsoft...", task, done)


def main() -> int:
    app = App()
    app.mainloop()
    return 0
