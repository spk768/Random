import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packlauncher import (auth, cli, instances, launch, loaders, minecraft, modrinth,  # noqa: E402
                          net, rules)


class TempHome(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"PACKLAUNCHER_HOME": str(self.tmp)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


def write_version(vid, data):
    path = minecraft.version_json_path(vid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


VANILLA = {
    "id": "1.20.1", "type": "release", "mainClass": "net.minecraft.client.main.Main",
    "assetIndex": {"id": "5", "url": "https://x/5.json", "sha1": "a"},
    "downloads": {"client": {"url": "https://x/client.jar", "sha1": "c"}},
    "javaVersion": {"majorVersion": 17},
    "libraries": [
        {"name": "org.lwjgl:lwjgl:3.3.1",
         "downloads": {"artifact": {"path": "org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1.jar", "url": "https://l/a.jar"}}},
        {"name": "org.ow2.asm:asm:9.1",
         "downloads": {"artifact": {"path": "org/ow2/asm/asm/9.1/asm-9.1.jar", "url": "https://l/asm.jar"}}},
        {"name": "only:windows:1", "rules": [{"action": "allow", "os": {"name": "windows"}}],
         "downloads": {"artifact": {"path": "only/windows.jar", "url": "https://l/w.jar"}}},
    ],
    "arguments": {
        "game": ["--username", "${auth_player_name}", "--gameDir", "${game_directory}",
                 {"rules": [{"action": "allow", "features": {"has_custom_resolution": True}}],
                  "value": ["--width", "${resolution_width}", "--height", "${resolution_height}"]},
                 {"rules": [{"action": "allow", "features": {"is_demo_user": True}}], "value": "--demo"}],
        "jvm": ["-Djava.library.path=${natives_directory}", "-cp", "${classpath}"],
    },
}

FABRIC = {
    "id": "fabric-loader-0.15.0-1.20.1", "inheritsFrom": "1.20.1",
    "mainClass": "net.fabricmc.loader.impl.launch.knot.KnotClient",
    "arguments": {"game": [], "jvm": ["-DFabricMcEmu= net.minecraft.client.main.Main "]},
    "libraries": [
        {"name": "org.ow2.asm:asm:9.6", "url": "https://maven.fabricmc.net/"},
        {"name": "net.fabricmc:fabric-loader:0.15.0", "url": "https://maven.fabricmc.net/"},
    ],
}


class RulesTest(unittest.TestCase):
    def test_rules(self):
        self.assertTrue(rules.allows(None))
        this_os = rules.os_name()
        self.assertTrue(rules.allows([{"action": "allow", "os": {"name": this_os}}]))
        self.assertFalse(rules.allows([{"action": "allow", "os": {"name": "plan9"}}]))
        self.assertFalse(rules.allows([{"action": "allow"}, {"action": "disallow", "os": {"name": this_os}}]))
        feat = [{"action": "allow", "features": {"has_custom_resolution": True}}]
        self.assertFalse(rules.allows(feat))
        self.assertTrue(rules.allows(feat, {"has_custom_resolution": True}))


class MinecraftTest(TempHome):
    def test_maven_path(self):
        self.assertEqual(minecraft.maven_path("a.b:c:1.0"), "a/b/c/1.0/c-1.0.jar")
        self.assertEqual(minecraft.maven_path("a.b:c:1.0:natives-linux"), "a/b/c/1.0/c-1.0-natives-linux.jar")
        self.assertEqual(minecraft.maven_path("a:c:1@zip"), "a/c/1/c-1.zip")

    def test_merge_and_libraries(self):
        write_version("1.20.1", VANILLA)
        write_version(FABRIC["id"], FABRIC)
        v = minecraft.resolve_version(FABRIC["id"])
        self.assertEqual(v["id"], FABRIC["id"])
        self.assertEqual(v["mainClass"], FABRIC["mainClass"])
        self.assertEqual(v["_vanilla"], "1.20.1")
        self.assertIn("client", v["downloads"])
        names = [lib["name"] for lib in v["libraries"]]
        self.assertIn("org.ow2.asm:asm:9.6", names)
        self.assertNotIn("org.ow2.asm:asm:9.1", names)  # o loader sobrescreve
        self.assertEqual(len(v["arguments"]["jvm"]), 4)
        files = minecraft.library_files(v)
        urls = [f.download.urls[0] for f in files]
        self.assertIn("https://maven.fabricmc.net/net/fabricmc/fabric-loader/0.15.0/fabric-loader-0.15.0.jar", urls)
        if rules.os_name() != "windows":
            self.assertNotIn("https://l/w.jar", urls)
        self.assertEqual(minecraft.client_jar_path(v).name, f"{FABRIC['id']}.jar")

    def test_legacy_natives(self):
        v = {"id": "1.8.9", "libraries": [{
            "name": "org.lwjgl.lwjgl:lwjgl-platform:2.9.4",
            "natives": {"linux": "natives-linux", "windows": "natives-windows-${arch}", "osx": "natives-osx"},
            "downloads": {"classifiers": {
                c: {"path": f"p/{c}.jar", "url": f"https://l/{c}.jar"}
                for c in ("natives-linux", "natives-windows-64", "natives-windows-32", "natives-osx")}},
        }]}
        files = minecraft.library_files(v)
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].extract)
        self.assertFalse(files[0].classpath)

    def test_build_arguments(self):
        ctx = {"auth_player_name": "Steve", "game_directory": "/g", "natives_directory": "/n",
               "classpath": "a:b", "resolution_width": "800", "resolution_height": "600"}
        jvm, game = minecraft.build_arguments(VANILLA, ctx, {"has_custom_resolution": True})
        self.assertEqual(game, ["--username", "Steve", "--gameDir", "/g", "--width", "800", "--height", "600"])
        self.assertEqual(jvm, ["-Djava.library.path=/n", "-cp", "a:b"])
        legacy = {"minecraftArguments": "--username ${auth_player_name} --tweakClass X"}
        jvm, game = minecraft.build_arguments(legacy, ctx, {})
        self.assertEqual(game, ["--username", "Steve", "--tweakClass", "X"])
        self.assertIn("-cp", jvm)


class LaunchTest(TempHome):
    def test_build_command(self):
        write_version("1.20.1", VANILLA)
        write_version(FABRIC["id"], FABRIC)
        inst = instances.create("Teste", "1.20.1", "fabric", "0.15.0", memory_mb=3072, width=1280, height=720,
                                jvm_args="-XX:+UseG1GC")
        v = minecraft.resolve_version(FABRIC["id"])
        acc = {"type": "offline", "name": "Steve", "uuid": auth.offline_uuid("Steve")}
        with mock.patch.object(minecraft, "asset_index", return_value={"objects": {}}):
            cmd = launch.build_command(inst, v, acc, "java")
        self.assertEqual(cmd[:4], ["java", "-Xms512M", "-Xmx3072M", "-XX:+UseG1GC"])
        main = cmd.index(FABRIC["mainClass"])
        cp = cmd[cmd.index("-cp") + 1].split(os.pathsep)
        self.assertTrue(cp[-1].endswith(f"{FABRIC['id']}.jar"))
        self.assertTrue(any("fabric-loader-0.15.0.jar" in p for p in cp))
        self.assertLess(cmd.index("-cp"), main)
        self.assertIn("--width", cmd[main:])
        self.assertIn(str(inst.game_dir), cmd)
        self.assertNotIn("--demo", cmd)


def make_mrpack(path, files, overrides=None, deps=None, client_overrides=None):
    index = {"formatVersion": 1, "game": "minecraft", "versionId": "1.0", "name": "Pack",
             "files": files, "dependencies": deps or {"minecraft": "1.20.1", "fabric-loader": "0.15.0"}}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps(index))
        for rel, content in (overrides or {}).items():
            zf.writestr(f"overrides/{rel}", content)
        for rel, content in (client_overrides or {}).items():
            zf.writestr(f"client-overrides/{rel}", content)
    return path


def pack_file(rel, content, env=None, url=None):
    return {"path": rel, "hashes": {"sha1": hashlib.sha1(content).hexdigest(),
                                    "sha512": hashlib.sha512(content).hexdigest()},
            "downloads": [url or f"https://cdn.modrinth.com/data/x/{rel.rsplit('/', 1)[-1]}"],
            "fileSize": len(content), **({"env": env} if env else {})}


class FakeNet:
    """Substitui downloads de rede por conteúdo em memória, verificando hash."""

    def __init__(self, contents):
        self.contents = contents  # nome do arquivo -> bytes

    def download_many(self, downloads, workers=8, progress=None):
        for d in downloads:
            if d.is_valid():
                continue
            data = self.contents[d.urls[0].rsplit("/", 1)[-1]]
            assert hashlib.sha512(data).hexdigest() == d.sha512
            d.dest.parent.mkdir(parents=True, exist_ok=True)
            d.dest.write_bytes(data)


class MrpackTest(TempHome):
    def install(self, mrpack, inst=None, fake=None, **kw):
        inst = inst or instances.create("Pack", "1.20.1")
        with mock.patch.object(net, "download_many", fake.download_many):
            modrinth.apply_mrpack(mrpack, inst, log=lambda m: None, **kw)
        return inst

    def test_install_and_update(self):
        a, b, c, opt = b"mod-a", b"mod-b", b"mod-c", b"optional"
        fake = FakeNet({"a.jar": a, "b.jar": b, "c.jar": c, "opt.jar": opt, "srv.jar": b"s"})
        v1 = make_mrpack(self.tmp / "v1.mrpack", [
            pack_file("mods/a.jar", a), pack_file("mods/b.jar", b),
            pack_file("mods/srv.jar", b"s", env={"client": "unsupported", "server": "required"}),
            pack_file("mods/opt.jar", opt, env={"client": "optional", "server": "optional"}),
        ], overrides={"config/a.toml": "x=1", "options.txt": "fov:70"},
            client_overrides={"config/a.toml": "x=2"})
        inst = self.install(v1, fake=fake, include_optional=lambda f: False)
        g = inst.game_dir
        self.assertEqual((g / "mods/a.jar").read_bytes(), a)
        self.assertFalse((g / "mods/srv.jar").exists())
        self.assertFalse((g / "mods/opt.jar").exists())
        self.assertEqual((g / "config/a.toml").read_text(), "x=2")  # client-overrides vencem
        self.assertEqual((inst.loader, inst.loader_version), ("fabric", "0.15.0"))
        self.assertEqual(inst.pack["files"], ["mods/a.jar", "mods/b.jar"])

        # usuário desativa um mod e altera options.txt
        instances.set_mod_enabled(inst, "b.jar", False)
        (g / "options.txt").write_text("fov:100")

        v2 = make_mrpack(self.tmp / "v2.mrpack", [pack_file("mods/b.jar", b), pack_file("mods/c.jar", c)],
                         overrides={"options.txt": "fov:70"},
                         deps={"minecraft": "1.20.1", "fabric-loader": "0.16.0"})
        inst.version_id = "fabric-loader-0.15.0-1.20.1"
        inst = self.install(v2, inst=inst, fake=fake)
        self.assertFalse((g / "mods/a.jar").exists())  # removido do pack
        self.assertTrue((g / "mods/b.jar.disabled").exists())  # continua desativado
        self.assertFalse((g / "mods/b.jar").exists())
        self.assertTrue((g / "mods/c.jar").exists())
        self.assertEqual((g / "options.txt").read_text(), "fov:100")  # preservado
        self.assertIsNone(inst.version_id)  # loader mudou -> reinstala
        self.assertEqual(inst.loader_version, "0.16.0")

    def test_rejects_unsafe(self):
        fake = FakeNet({"evil.jar": b"x"})
        bad_path = make_mrpack(self.tmp / "bad.mrpack", [pack_file("../evil.jar", b"x")])
        with self.assertRaises(modrinth.PackError):
            self.install(bad_path, fake=fake)
        bad_url = make_mrpack(self.tmp / "url.mrpack",
                              [pack_file("mods/evil.jar", b"x", url="https://evil.example/evil.jar")])
        with self.assertRaises(modrinth.PackError):
            self.install(bad_url, fake=fake)
        bad_override = make_mrpack(self.tmp / "ov.mrpack", [], overrides={"../../x.txt": "x"})
        with self.assertRaises(modrinth.PackError):
            self.install(bad_override, fake=fake)

    def test_import_creates_instance(self):
        fake = FakeNet({"a.jar": b"a"})
        mrpack = make_mrpack(self.tmp / "p.mrpack", [pack_file("mods/a.jar", b"a")],
                             deps={"minecraft": "1.21.1", "neoforge": "21.1.77"})
        with mock.patch.object(net, "download_many", fake.download_many):
            inst = modrinth.import_mrpack(mrpack, log=lambda m: None)
        self.assertEqual((inst.name, inst.minecraft, inst.loader), ("Pack", "1.21.1", "neoforge"))
        self.assertEqual(instances.find("Pack").dir, inst.dir)

    def test_export(self):
        inst = instances.create("Exp", "1.20.1", "fabric", "0.15.0")
        g = inst.game_dir
        (g / "mods").mkdir()
        (g / "mods/known.jar").write_bytes(b"known")
        (g / "mods/custom.jar").write_bytes(b"custom")
        (g / "mods/off.jar.disabled").write_bytes(b"off")
        (g / "config").mkdir()
        (g / "config/x.toml").write_text("a")
        sha1 = hashlib.sha1(b"known").hexdigest()
        found = {sha1: {"files": [{"hashes": {"sha1": sha1}, "url": "https://cdn.modrinth.com/k.jar"}]}}
        out = self.tmp / "out.mrpack"
        with mock.patch.object(net, "post_json", return_value=found):
            modrinth.export_mrpack(inst, out, "2.0", log=lambda m: None)
        index = modrinth.read_index(out)
        self.assertEqual(index["dependencies"], {"minecraft": "1.20.1", "fabric-loader": "0.15.0"})
        self.assertEqual([f["path"] for f in index["files"]], ["mods/known.jar"])
        names = zipfile.ZipFile(out).namelist()
        self.assertIn("overrides/mods/custom.jar", names)
        self.assertIn("overrides/config/x.toml", names)
        self.assertNotIn("overrides/mods/off.jar.disabled", names)


class NetTest(TempHome):
    def test_download_file_url_and_hash(self):
        src = self.tmp / "src.bin"
        src.write_bytes(b"hello")
        dest = self.tmp / "out" / "f.bin"
        good = net.Download(src.as_uri(), dest, sha1=hashlib.sha1(b"hello").hexdigest(), size=5)
        self.assertTrue(net.download(good))
        self.assertFalse(net.download(good))  # já válido
        bad = net.Download(src.as_uri(), self.tmp / "out" / "g.bin", sha1="0" * 40)
        with self.assertRaises(net.DownloadError):
            net.download(bad)
        self.assertFalse((self.tmp / "out" / "g.bin").exists())


class MiscTest(TempHome):
    def test_offline_uuid(self):
        # Valor de UUID.nameUUIDFromBytes("OfflinePlayer:Notch") em Java
        self.assertEqual(auth.offline_uuid("Notch"), "b50ad385-829d-3141-a216-7e7d7539ba7f")

    def test_accounts(self):
        auth.add_offline("Steve")
        auth.add_offline("Alex")
        self.assertEqual(auth.get_default()["name"], "Steve")
        auth.set_default(auth.find("alex")["uuid"])
        self.assertEqual(auth.get_default()["name"], "Alex")
        auth.remove(auth.find("Alex")["uuid"])
        self.assertEqual(auth.get_default()["name"], "Steve")
        with self.assertRaises(auth.AuthError):
            auth.add_offline("no spaces")

    def test_neoforge_mapping(self):
        self.assertEqual(loaders.neoforge_mc_version("21.1.77"), "1.21.1")
        self.assertEqual(loaders.neoforge_mc_version("21.0.3-beta"), "1.21")
        self.assertEqual(loaders.neoforge_mc_version("20.4.237"), "1.20.4")

    def test_instances_and_mods(self):
        a = instances.create("Meu Pack", "1.20.1")
        b = instances.create("Meu Pack", "1.20.1")
        self.assertEqual(b.name, "Meu Pack (2)")
        self.assertNotEqual(a.dir, b.dir)
        a.mods_dir.mkdir(parents=True)
        (a.mods_dir / "x.jar").write_bytes(b"")
        self.assertEqual(instances.set_mod_enabled(a, "x.jar", False), "x.jar.disabled")
        self.assertEqual([m["enabled"] for m in instances.list_mods(a)], [False])

    def test_cli(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main(["account", "offline", "Steve"]), 0)
            self.assertEqual(cli.main(["create", "Vanilla", "--mc", "1.21.1"]), 0)
            self.assertEqual(cli.main(["list"]), 0)
        self.assertIn("Vanilla", out.getvalue())
        self.assertIn("Steve", out.getvalue())
        with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(cli.main(["launch", "NaoExiste"]), 1)


if __name__ == "__main__":
    unittest.main()
