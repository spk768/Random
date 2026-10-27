import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packlauncher import curseforge, instances, net, settings  # noqa: E402
from packlauncher.modrinth import PackError  # noqa: E402

CONTENT = {"jei.jar": b"jei", "create.jar": b"create", "faithful.zip": b"rp", "blocked.jar": b"nope"}
FILES = {
    1: {"id": 1, "fileName": "jei.jar", "downloadUrl": "https://edge.forgecdn.net/files/0/1/jei.jar"},
    2: {"id": 2, "fileName": "create.jar", "downloadUrl": "https://edge.forgecdn.net/files/0/2/create.jar"},
    3: {"id": 3, "fileName": "faithful.zip", "downloadUrl": "https://edge.forgecdn.net/files/0/3/faithful.zip"},
    4: {"id": 4, "fileName": "blocked.jar", "downloadUrl": None},
}
for f in FILES.values():
    f["hashes"] = [{"algo": 1, "value": hashlib.sha1(CONTENT[f["fileName"]]).hexdigest()}]
MODS = {10: {"id": 10, "name": "JEI", "classId": 6}, 20: {"id": 20, "name": "Create", "classId": 6},
        30: {"id": 30, "name": "Faithful", "classId": 12},
        40: {"id": 40, "name": "Blocked Mod", "classId": 6, "links": {"websiteUrl": "https://cf/blocked"}}}


def fake_call(path, payload=None, **params):
    if path == "/mods/files":
        return {"data": [FILES[i] for i in payload["fileIds"] if i in FILES]}
    if path == "/mods":
        return {"data": [MODS[i] for i in payload["modIds"] if i in MODS]}
    raise AssertionError(path)


def fake_download_many(downloads, workers=8, progress=None):
    errors = []
    for d in downloads:
        name = d.dest.name.removesuffix(".disabled")
        if name == "blocked.jar":  # nenhuma URL funciona
            errors.append(name)
            continue
        d.dest.parent.mkdir(parents=True, exist_ok=True)
        d.dest.write_bytes(CONTENT[name])
    if errors:
        raise net.DownloadError(", ".join(errors))


def make_pack(path, files, loader="forge-47.2.0", overrides=None):
    manifest = {"manifestType": "minecraftModpack", "manifestVersion": 1, "name": "CF Pack", "version": "1.0",
                "minecraft": {"version": "1.20.1", "modLoaders": [{"id": loader, "primary": True}]},
                "files": [{"projectID": p, "fileID": f, "required": True} for p, f in files],
                "overrides": "overrides"}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for rel, data in (overrides or {}).items():
            zf.writestr(f"overrides/{rel}", data)
    return path


class CurseForgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"PACKLAUNCHER_HOME": str(self.tmp)})
        self.env.start()
        self.patches = [mock.patch.object(curseforge, "_call", fake_call),
                        mock.patch.object(net, "download_many", fake_download_many)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_import_and_update(self):
        pack = make_pack(self.tmp / "p.zip", [(10, 1), (20, 2), (30, 3), (40, 4)],
                         overrides={"config/a.toml": "x", "options.txt": "fov:70"})
        self.assertTrue(curseforge.is_curseforge_pack(pack))
        inst = curseforge.import_pack(pack, log=lambda m: None)
        g = inst.game_dir
        self.assertEqual((inst.minecraft, inst.loader, inst.loader_version), ("1.20.1", "forge", "47.2.0"))
        self.assertTrue((g / "mods/jei.jar").exists())
        self.assertTrue((g / "resourcepacks/faithful.zip").exists())
        self.assertEqual((g / "config/a.toml").read_text(), "x")
        self.assertEqual([m["name"] for m in inst.pack["missing"]], ["Blocked Mod"])
        self.assertEqual(inst.pack["missing"][0]["url"], "https://cf/blocked")

        instances.set_mod_enabled(inst, "create.jar", False)
        (g / "options.txt").write_text("fov:100")
        v2 = make_pack(self.tmp / "p2.zip", [(20, 2)], loader="neoforge-21.1.1", overrides={"options.txt": "fov:70"})
        curseforge.apply_pack(v2, inst, log=lambda m: None)
        self.assertFalse((g / "mods/jei.jar").exists())
        self.assertTrue((g / "mods/create.jar.disabled").exists())
        self.assertEqual((g / "options.txt").read_text(), "fov:100")
        self.assertEqual(inst.loader, "neoforge")
        self.assertEqual(inst.pack["missing"], [])

    def test_rejects_unsafe_override(self):
        pack = make_pack(self.tmp / "bad.zip", [], overrides={"../../evil.txt": "x"})
        with self.assertRaises(PackError):
            curseforge.import_pack(pack, log=lambda m: None)
        self.assertEqual(instances.list_all(), [])

    def test_requirements_and_urls(self):
        self.assertEqual(curseforge.pack_requirements({"minecraft": {"version": "1.12.2", "modLoaders": []}}),
                         ("1.12.2", "vanilla", None))
        urls = curseforge._urls({"id": 4567890, "fileName": "a b.jar", "downloadUrl": None})
        self.assertEqual(urls[0], "https://edge.forgecdn.net/files/4567/890/a%20b.jar")

    def test_api_key_config(self):
        self.patches[0].stop()
        try:
            with self.assertRaises(PackError):
                curseforge.search("x")
            settings.set("curseforge_api_url", "https://proxy.example/")
            seen = {}

            def fake_get(url, headers=None):
                seen["url"], seen["headers"] = url, headers
                return {"data": [], "pagination": {"totalCount": 0}}
            with mock.patch.object(net, "get_json", fake_get):
                curseforge.search("create", loader="fabric")
                self.assertTrue(seen["url"].startswith("https://proxy.example/v1/mods/search?"))
                self.assertIn("modLoaderType=4", seen["url"])
                self.assertNotIn("x-api-key", seen["headers"])
                settings.set("curseforge_api_key", "segredo")
                curseforge.search("create")
                self.assertEqual(seen["headers"]["x-api-key"], "segredo")
        finally:
            self.patches[0].start()


if __name__ == "__main__":
    unittest.main()
