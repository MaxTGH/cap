"""CAP's local web server: serves the dashboard and runs your project scripts.

Safety model:
- Binds to 127.0.0.1, so only this Mac can reach it.
- Every /api call needs a random token made at launch. The token is put into
  the page exactly once, for the window cap.py opens with a one-time launch
  code; any later request for the page (another program on this Mac, a second
  tab, a website) gets a page without it. Other websites can't read the page
  anyway (no CORS headers).
- Requests with a foreign Host or Origin header are refused (blocks DNS rebinding).
- Panels can only run the fixed commands in TASKS; user text is passed as a
  single argument, never through a shell.
- Results and logs live in memory only, are sent with Cache-Control: no-store,
  and are never written to disk or printed to the terminal.
"""
import hmac
import html
import json
import os
import re
import secrets
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

STATIC = Path(__file__).resolve().parent / "static"
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
MAX_JOBS = 30          # finished jobs kept in memory for the page to read
MAX_LOG_LINES = 300    # per job
MAX_BODY = 10_000      # bytes accepted on POST
NOISE = re.compile(r"it/s\]|s/it\]|^\s*warnings\.warn")  # progress bars and warning echoes from libraries


@dataclass
class Task:
    cwd: Path
    argv: Callable[[dict], list]  # builds the command from the panel's input; raises ValueError on bad input
    timeout: int                  # seconds before the script is stopped


@dataclass
class Job:
    task: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "running"  # running | done | error
    log: list = field(default_factory=list)
    result: object = None
    error: str | None = None
    started: float = field(default_factory=time.time)
    finished: float | None = None


class CAP:
    def __init__(self, tasks: dict, name: str, mode: str = "live"):
        self.tasks, self.name, self.mode = tasks, name, mode
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)
        self.launch_code = secrets.token_urlsafe(16)  # in the URL cap.py opens; good for one page load
        self.launch_used = False
        self.last_ping: float | None = None

    def busy(self) -> bool:
        return any(j.status == "running" for j in self.jobs.values())

    def start(self, task_id: str, inp: dict) -> Job:
        task = self.tasks[task_id]  # KeyError -> unknown task
        argv = task.argv(inp)       # ValueError -> bad input
        with self.lock:
            if any(j.task == task_id and j.status == "running" for j in self.jobs.values()):
                raise RuntimeError("That module is already running.")
            job = Job(task_id)
            self.jobs[job.id] = job
            for old in list(self.jobs)[:-MAX_JOBS]:  # dicts keep insertion order: drop the oldest
                del self.jobs[old]
        threading.Thread(target=self._run, args=(job, task, argv), daemon=True).start()
        return job

    def _run(self, job: Job, task: Task, argv: list) -> None:
        try:
            # text=True gives universal newlines, so "\r" progress updates arrive as separate lines.
            proc = subprocess.Popen(argv, cwd=task.cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, env={**os.environ, "PYTHONUNBUFFERED": "1"})
        except OSError as e:
            job.error, job.status, job.finished = f"Couldn't start {argv[0]}: {e.strerror}", "error", time.time()
            return
        timed_out = threading.Event()

        def stop():
            timed_out.set()
            proc.kill()

        timer = threading.Timer(task.timeout, stop)
        timer.start()
        stdout = []
        reader = threading.Thread(target=lambda: stdout.extend(proc.stdout), daemon=True)
        reader.start()
        for line in proc.stderr:
            line = line.rstrip()
            if line and not NOISE.search(line):
                job.log.append(line[:400])
                del job.log[:-MAX_LOG_LINES]
        proc.wait()
        reader.join()
        timer.cancel()
        proc.stdout.close()
        proc.stderr.close()

        # Scripts print one line of JSON last. Exit code 1 can still carry a result (balance FAIL).
        last = next((l for l in reversed(stdout) if l.strip()), "")
        try:
            job.result, job.status = json.loads(last), "done"
        except json.JSONDecodeError:
            if timed_out.is_set():
                job.error = f"Stopped after {task.timeout // 60} minutes without finishing."
            else:
                tail = [l for l in job.log if l.strip()][-3:]
                job.error = "\n".join(tail) or f"Exited with code {proc.returncode} and no result."
            job.status = "error"
        job.finished = time.time()

    def job_view(self, job: Job, since: int) -> dict:
        return {"id": job.id, "task": job.task, "status": job.status, "log": job.log[since:],
                "next": len(job.log), "result": job.result, "error": job.error,
                "elapsed": round((job.finished or time.time()) - job.started, 1)}


def make_handler(app: CAP, port: int):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {f"http://{h}" for h in hosts}

    class Handler(BaseHTTPRequestHandler):
        server_version = "CAP"
        sys_version = ""

        def log_message(self, *_):
            pass  # keep requests (and anything in them) out of the terminal

        def send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            for k, v in {"Content-Type": ctype, "Content-Length": str(len(body)), "Cache-Control": "no-store",
                         "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", **(extra or {})}.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, code: int, obj) -> None:
            self.send(code, json.dumps(obj).encode(), "application/json")

        def allowed(self, api: bool) -> bool:
            origin = self.headers.get("Origin")
            if self.headers.get("Host") not in hosts or (origin and origin not in origins):
                self.send_json(403, {"error": "Forbidden"})
                return False
            if api and not hmac.compare_digest(self.headers.get("X-CAP-Token", ""), app.token):
                self.send_json(403, {"error": "Missing or wrong token. Reload the page."})
                return False
            return True

        def do_GET(self):
            url = urlparse(self.path)
            if not self.allowed(api=url.path.startswith("/api/")):
                return
            if url.path == "/":
                code = parse_qs(url.query).get("launch", [""])[0]
                with app.lock:
                    first_launch = not app.launch_used and hmac.compare_digest(code, app.launch_code)
                    app.launch_used = app.launch_used or first_launch
                page = (STATIC / "index.html").read_text()
                # Reloads of the authorized window keep working: the page saved the token in sessionStorage.
                page = page.replace("{{TOKEN}}", app.token if first_launch else "").replace("{{NAME}}", html.escape(app.name)).replace("{{MODE}}", app.mode)
                self.send(200, page.encode(), STATIC_TYPES[".html"], {"Content-Security-Policy": CSP})
            elif url.path.startswith("/static/"):
                f = (STATIC / url.path.removeprefix("/static/")).resolve()
                if f.parent != STATIC or f.suffix not in STATIC_TYPES or not f.is_file() or f.name == "index.html":
                    return self.send_json(404, {"error": "Not found"})
                self.send(200, f.read_bytes(), STATIC_TYPES[f.suffix])
            elif url.path == "/api/ping":
                app.last_ping = time.time()
                self.send_json(200, {"ok": True})
            elif url.path.startswith("/api/jobs/"):
                job = app.jobs.get(url.path.removeprefix("/api/jobs/"))
                if not job:
                    return self.send_json(404, {"error": "Unknown job"})
                try:
                    since = max(0, int(parse_qs(url.query).get("since", ["0"])[0]))
                except ValueError:
                    since = 0
                self.send_json(200, app.job_view(job, since))
            else:
                self.send_json(404, {"error": "Not found"})

        def do_POST(self):
            url = urlparse(self.path)
            if not self.allowed(api=True):
                return
            if url.path != "/api/run":
                return self.send_json(404, {"error": "Not found"})
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                length = MAX_BODY + 1
            if not 0 < length <= MAX_BODY:
                return self.send_json(413, {"error": "Request too large"})
            try:
                body = json.loads(self.rfile.read(length))
                task_id, inp = str(body["task"]), body.get("input") or {}
                if not isinstance(inp, dict):
                    raise ValueError("input must be an object")
                job = app.start(task_id, inp)
            except KeyError:
                return self.send_json(404, {"error": "Unknown module"})
            except (ValueError, json.JSONDecodeError) as e:
                return self.send_json(400, {"error": str(e)})
            except RuntimeError as e:
                return self.send_json(409, {"error": str(e)})
            self.send_json(202, {"id": job.id})

    return Handler


def make_server(app: CAP, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, port))
    server.daemon_threads = True
    return server
