import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packlauncher import gui, instances  # noqa: E402


class GuiServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"PACKLAUNCHER_HOME": str(self.tmp)})
        self.env.start()
        self.server, self.app = gui.serve(0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def req(self, path, body=None, token=True, host=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Token"] = self.app.token
        if host:
            headers["Host"] = host
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers)
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, resp.read()

    def status(self, *args, **kw):
        try:
            return self.req(*args, **kw)[0]
        except urllib.error.HTTPError as e:
            return e.code

    def test_static_and_security(self):
        code, body = self.req("/", token=False)
        self.assertEqual(code, 200)
        self.assertIn(b"PackLauncher", body)
        self.assertEqual(self.status("/app.js", token=False), 200)
        self.assertEqual(self.status("/api/state", token=False), 401)
        self.assertEqual(self.status("/api/state", host="evil.example"), 403)
        self.assertEqual(self.status("/../gui.py", token=False), 404)
        self.assertEqual(self.status("/api/instances/..%2F..%2Fetc"), 404)

    def test_instance_flow(self):
        self.assertEqual(self.status("/api/accounts/offline", {"name": "Steve"}), 200)
        code, body = self.req("/api/instances", {"name": "Teste", "minecraft": "1.21.1", "loader": "fabric",
                                                 "loader_version": "0.16.5"})
        inst_id = json.loads(body)["id"]
        state = json.loads(self.req("/api/state")[1])
        self.assertEqual(state["accounts"][0]["name"], "Steve")
        self.assertEqual([i["name"] for i in state["instances"]], ["Teste"])

        inst = instances.find("Teste")
        inst.mods_dir.mkdir(parents=True)
        (inst.mods_dir / "a.jar").write_bytes(b"x")
        self.req(f"/api/instances/{inst_id}/mods/toggle", {"file": "a.jar", "enabled": False})
        detail = json.loads(self.req(f"/api/instances/{inst_id}")[1])
        self.assertEqual(detail["mods"], [{"file": "a.jar.disabled", "enabled": False, "from_pack": False, "size": 1}])

        self.req(f"/api/instances/{inst_id}/settings", {"name": "Renomeada", "memory_mb": 6144})
        self.assertEqual(instances.find("Renomeada").memory_mb, 6144)

        code, body = self.req(f"/api/instances/{inst_id}/export?version=2.0")
        self.assertEqual(code, 200)
        self.assertEqual(body[:2], b"PK")

        self.assertEqual(self.status(f"/api/instances/{inst_id}/delete", {}), 200)
        self.assertEqual(json.loads(self.req("/api/state")[1])["instances"], [])

    def test_launch_requires_account(self):
        _, body = self.req("/api/instances", {"name": "X", "minecraft": "1.21.1"})
        inst_id = json.loads(body)["id"]
        self.assertEqual(self.status(f"/api/instances/{inst_id}/launch", {}), 409)


if __name__ == "__main__":
    unittest.main()
