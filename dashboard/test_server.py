"""Security and behavior tests for CAP's server, using a harmless fake module.

    uv run python -m unittest test_server -v

Starts a real server on a free local port and talks to it over HTTP. No bank,
Gmail or Keychain access.
"""
import http.client
import json
import re
import socket
import sys
import threading
import time
import unittest
from pathlib import Path

from server import CAP, Task, make_server

HERE = Path(__file__).resolve().parent
FAKE = "import json, sys; print('step 1', file=sys.stderr); print(json.dumps({'echo': sys.argv[-1]}))"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        tasks = {"echo": Task(HERE, lambda inp: [sys.executable, "-c", FAKE, "--", str(inp.get("text", ""))], 10)}
        self.app = CAP(tasks, "Tester")
        self.server = make_server(self.app, self.port)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read().decode()
        conn.close()
        return resp.status, dict(resp.getheaders()), data

    def page_token(self, path="/"):
        status, _, page = self.request("GET", path)
        self.assertEqual(status, 200)
        return re.search(r'name="cap-token" content="([^"]*)"', page).group(1)

    def auth(self, token=None):
        return {"X-CAP-Token": token or self.app.token}

    def run_job(self, text):
        status, _, body = self.request("POST", "/api/run", {"task": "echo", "input": {"text": text}}, self.auth())
        self.assertEqual(status, 202)
        job_id = json.loads(body)["id"]
        for _ in range(100):
            _, _, body = self.request("GET", f"/api/jobs/{job_id}", headers=self.auth())
            job = json.loads(body)
            if job["status"] != "running":
                return job
            time.sleep(0.05)
        self.fail("job never finished")

    # --- the launch link and token ---

    def test_token_only_given_once_with_launch_code(self):
        self.assertEqual(self.page_token("/"), "")                      # plain page: locked
        self.assertEqual(self.page_token("/?launch=guess"), "")          # wrong code: locked
        self.assertEqual(self.page_token(f"/?launch={self.app.launch_code}"), self.app.token)
        self.assertEqual(self.page_token(f"/?launch={self.app.launch_code}"), "")  # single use

    def test_api_requires_token(self):
        for headers in ({}, {"X-CAP-Token": "wrong"}):
            status, _, _ = self.request("POST", "/api/run", {"task": "echo"}, headers)
            self.assertEqual(status, 403)
            status, _, _ = self.request("GET", "/api/ping", headers=headers)
            self.assertEqual(status, 403)

    # --- requests from elsewhere ---

    def test_foreign_host_refused(self):  # DNS rebinding
        status, _, _ = self.request("GET", "/", headers={"Host": f"evil.example:{self.port}"})
        self.assertEqual(status, 403)

    def test_foreign_origin_refused(self):  # another website posting to the API
        headers = {**self.auth(), "Origin": "https://evil.example"}
        status, _, _ = self.request("POST", "/api/run", {"task": "echo"}, headers)
        self.assertEqual(status, 403)

    def test_static_files_cannot_escape_folder(self):
        for path in ("/static/../server.py", "/static/..%2Fserver.py", "/static/index.html"):
            status, _, _ = self.request("GET", path)
            self.assertEqual(status, 404, path)

    # --- headers ---

    def test_security_headers(self):
        _, headers, _ = self.request("GET", "/")
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        _, headers, _ = self.request("GET", "/api/ping", headers=self.auth())
        self.assertEqual(headers["Cache-Control"], "no-store")

    # --- running modules ---

    def test_job_streams_progress_and_returns_json(self):
        job = self.run_job("hello")
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["log"], ["step 1"])
        self.assertEqual(job["result"], {"echo": "hello"})

    def test_input_is_one_argument_not_a_shell_command(self):
        job = self.run_job("x; echo pwned $(whoami)")
        self.assertEqual(job["result"], {"echo": "x; echo pwned $(whoami)"})

    def test_unknown_module_and_bad_input(self):
        status, _, _ = self.request("POST", "/api/run", {"task": "nope"}, self.auth())
        self.assertEqual(status, 404)
        status, _, _ = self.request("POST", "/api/run", {"task": "echo", "input": "not an object"}, self.auth())
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
