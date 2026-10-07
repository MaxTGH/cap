"""C.A.P.: one window for all your projects.

    uv run cap.py               # start CAP and open its window
    uv run cap.py --no-window   # just start the server (open the printed URL yourself)

Each panel runs one of your projects with that project's own Python, exactly as
if you typed the command in a terminal, and shows the result. Nothing is saved
to disk. CAP shuts itself down a couple of minutes after its window closes
(or press Ctrl-C).
"""
import argparse
import errno
import re
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from server import CAP, Task, make_server

NAME = "Max"  # how CAP greets you
PORT = 8790
HERE = Path(__file__).resolve().parent
PROJECTS = HERE.parent  # ~/Projects
IDLE_EXIT = 150  # seconds without a ping from the window (and nothing running) before CAP quits
CHROME = Path("/Applications/Google Chrome.app")


def python(project: str, *args: str) -> list:
    return [str(PROJECTS / project / ".venv" / "bin" / "python"), *args]


def research_prompt(inp: dict) -> str:
    prompt = " ".join(str(inp.get("prompt", "")).split())
    if not 3 <= len(prompt) <= 1000:
        raise ValueError("Describe what you want to research in 3 to 1000 characters.")
    return prompt


def weather_place(inp: dict) -> str:
    place = " ".join(str(inp.get("place", "")).split())
    if not re.fullmatch(r"[^\W\d_][\w .,'()-]{1,99}", place):
        raise ValueError("Enter a city name, like Boston or Boston, MA.")
    return place


TASKS = {
    "balance": Task(PROJECTS / "balance-check", lambda inp: python("balance-check", "check.py", "--json"), 120),
    "subscriptions": Task(PROJECTS / "balance-check", lambda inp: python("balance-check", "subscriptions.py", "--json"), 300),
    "email": Task(PROJECTS / "email-classifier",
                  lambda inp: python("email-classifier", "gmail_labeler.py", "--json") + (["--dry-run"] if inp.get("dry_run") else []),
                  1800),
    # "--" so a prompt starting with "-" is never read as an option.
    "research": Task(PROJECTS / "research", lambda inp: python("research", "find_papers.py", "--json", "--", research_prompt(inp)), 1200),
    # Runs with CAP's own Python; sends only the city name and its coordinates to Open-Meteo.
    "weather": Task(HERE, lambda inp: [sys.executable, str(HERE / "weather.py"), "--json", "--", weather_place(inp)], 30),
}


def open_window(url: str) -> None:
    """A Chrome app window (no tabs or address bar) with its own profile, so it feels like an app
    and your normal browser's extensions can't see the page. Falls back to the default browser."""
    if not CHROME.exists():
        webbrowser.open(url)
        return
    profile = Path.home() / "Library" / "Application Support" / "CAP" / "chrome"
    subprocess.Popen(["open", "-na", str(CHROME), "--args", f"--app={url}", f"--user-data-dir={profile}",
                      "--no-first-run", "--no-default-browser-check", "--window-size=1500,960",
                      "--autoplay-policy=no-user-gesture-required",  # lets CAP speak its greeting
                      "--disable-background-timer-throttling"])     # keeps pings going when minimized


def run(tasks: dict, port: int, mode: str = "live") -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-window", action="store_true", help="don't open a window")
    args, _ = ap.parse_known_args()

    url = f"http://127.0.0.1:{port}/"
    app = CAP(tasks, NAME, mode)
    try:
        server = make_server(app, port)
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            raise
        # A second window couldn't be authorized (the launch code is single-use), so don't open one.
        print("CAP is already running in its own window. To get a fresh window, quit that CAP "
              "(Ctrl-C in its terminal, or close its window and wait a couple of minutes) and start it again.")
        return

    threading.Thread(target=server.serve_forever, daemon=True).start()
    launch_url = f"{url}?launch={app.launch_code}"
    label = "CAP (demo data)" if mode == "demo" else "CAP"
    if args.no_window:
        print(f"{label} is online. Open this link once to use it (it only works one time):\n  {launch_url}\n(Ctrl-C to quit)", flush=True)
    else:
        print(f"{label} is online in its own window. (Ctrl-C to quit)", flush=True)
        open_window(launch_url)
    try:
        while True:
            time.sleep(5)
            if app.last_ping and time.time() - app.last_ping > IDLE_EXIT and not app.busy():
                print("Window closed. CAP signing off.")
                break
    except KeyboardInterrupt:
        print("\nCAP signing off.")
    server.shutdown()


if __name__ == "__main__":
    run(TASKS, PORT)
