# C.A.P.

One window for all your projects. CAP greets you, then shows a panel for each project, each with a button that runs it and displays the result:

| Panel | Runs | What it shows |
|---|---|---|
| Financial integrity | `balance-check/check.py --json` | Checking left after cards at each bank: PASS, WARN (under $100) or FAIL |
| Subscriptions | `balance-check/subscriptions.py --json` | Recurring charges and an estimated monthly total |
| Mail triage | `email-classifier/gmail_labeler.py --json` | How many emails got each `Classifier/…` label (tick **Preview only** to change nothing) |
| Research | `research/find_papers.py --json "<your prompt>"` | Top papers from OpenAlex, ranked by SPECTER2 |
| Activity | | Live progress from whatever is running |

The top bar also shows the weather (`weather.py`, from Open-Meteo): temperature, conditions and today's high/low. Hover over it for rain chance, humidity, wind, sunrise and sunset.

## Run it

```bash
cd ~/Projects/cap
uv run cap.py
```

This opens CAP in its own Chrome app window. Close the window and CAP shuts itself down a couple of minutes later, or press Ctrl-C in the terminal. Only that window can use CAP; to get a new window, quit CAP and start it again. To see it with made-up data first (no banks, Gmail or Keychain involved):

```bash
uv run demo.py
```

CAP has no dependencies beyond the Python standard library. Each panel runs the project with that project's own `.venv`, exactly as if you ran it in a terminal, so each project's setup still applies (Plaid keys in the Keychain, the Gmail sign-in, the trained email model, the research `.env`).

Mail triage opens a browser to sign in to Google when its login is missing or expired (about weekly while the Google app is in Testing mode).

## Settings

At the top of `cap.py`:
- `NAME`: how CAP greets you.
- `PORT`: 8790 (the demo uses 8791).
- `TASKS`: the panels' commands. Add a project by adding a `Task` here and a panel in `static/index.html` plus a renderer in `static/app.js`.

The speaker button in the top-right corner turns the voice on or off, and CAP remembers your choice.

For weather, click the weather readout in the top bar and type your city once (e.g. `Boston, MA`). CAP remembers it, loads it at start-up, says the conditions after its greeting, and refreshes quietly every 30 minutes. Switch to Celsius by changing `TEMP_UNIT` and `WIND_UNIT` at the top of `weather.py`.

## Privacy and safety

- **Local only.** The server listens on `127.0.0.1`, so nothing else on your network can reach it.
- **Only CAP's own window can use it.** Every request needs a random token created when CAP starts. The token is handed out once, to the window `cap.py` opens with a single-use launch link. Any other request for the page (another app or user account on this Mac, a second tab, a website) gets a locked page without it. Requests from other origins or hostnames are refused, which also blocks DNS-rebinding attacks.
- **Fixed commands only.** Panels can only run the commands above. Your research prompt is passed as a single argument and never goes through a shell.
- **Nothing is saved.** Results stay in memory and are sent with `Cache-Control: no-store`. Nothing is logged to the terminal or written to disk. The one exception is research, which saves its ranked CSV to `research/results/` like the notebook does.
- **On-device voice only.** CAP speaks with your Mac's built-in voices, never an online voice that would send the text to a server. Spoken summaries never include amounts or bank names.
- **Only research and weather leave your Mac, by design.** Your research prompt is sent to OpenAlex (and to Claude if an Anthropic API key is set). For weather, only the city you type and its coordinates go to Open-Meteo (no account or key); CAP never uses your device's location. Nothing else CAP shows is sent anywhere.
- **Separate browser profile.** The app window uses its own Chrome profile (`~/Library/Application Support/CAP/chrome`), so extensions in your normal browser can't read the page.
