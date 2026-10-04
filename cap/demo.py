"""Preview CAP with made-up data. Touches no bank, Gmail account, Plaid or Keychain.

    uv run demo.py                 # opens a demo window (marked "Demo data")
    open http://127.0.0.1:8791/#autorun   # fills every panel at once

Each panel runs this same file as a fake script (python demo.py --child <task>),
so the demo goes through exactly the same server, progress and rendering path
as the real thing.
"""
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import cap
from server import Task

HERE = Path(__file__).resolve().parent
PORT = 8791


def fake_result(task: str, inp: dict) -> dict:
    today = date.today()
    day = lambda n: (today + timedelta(days=n)).isoformat()
    if task == "balance":
        return {"warn_below": 100.0, "status": "fail", "per_bank": {
            "First Demo Bank": {"checking": 3120.55, "credit": 842.10, "left": 2278.45, "status": "pass"},
            "Example Credit Union": {"checking": 1410.00, "credit": 1349.37, "left": 60.63, "status": "warn"},
            "Sample Savings & Loan": {"checking": 655.20, "credit": 731.80, "left": -76.60, "status": "fail"},
        }}
    if task == "subscriptions":
        sub = lambda m, f, a, where, last, nxt, active, per: {"merchant": m, "frequency": f, "amount": a, "where": where,
            "count": 3, "last": day(last), "next": day(nxt), "active": active, "per_month": per}
        return {"warnings": ["Example Credit Union: only the last ~30 days are loaded so far; results may be incomplete"],
                "history_days": 92, "subscriptions": [
            sub("Demo Streaming+", "monthly", 17.99, "First Demo Bank credit card", -12, 18, True, 18.25),
            sub("Sample Music", "monthly", 11.99, "First Demo Bank credit card", -4, 26, True, 12.17),
            sub("Example Cloud Storage", "monthly", 2.99, "Example Credit Union checking", -20, 10, True, 3.03),
            sub("Placeholder Meal Kit", "weekly", 59.94, "Sample Savings & Loan credit card", -3, 4, True, 260.64),
            sub("Fictional Gym", "monthly", 40.00, "First Demo Bank checking", -45, -15, False, 40.58),
        ]}
    if task == "email":
        return {"days": 7, "found": 64, "new": 38, "dry_run": bool(inp.get("dry_run")), "threshold": 0.7,
                "labelled": {"news": 17, "other": 11, "bank": 6}, "unsure": 4}
    if task == "research":
        paper = lambda t, y, v, a, c, k, s, ab: {"title": t, "url": "https://example.org/paper", "year": y, "venue": v,
            "first_author": a, "citations": c, "kind": k, "similarity": s, "score": 1.0, "abstract": ab}
        lorem = ("Demo abstract. This placeholder stands in for a real paper's abstract so the layout can be previewed "
                 "without contacting OpenAlex. Real runs show the first 600 characters of each paper's abstract here.")
        return {"problem": inp.get("prompt", ""), "used_claude": False, "candidates": 412,
                "saved_to": "results/papers_demo.csv",
                "queries": {"same_domain": ["tenants pay rent late", "rent payment default", "tenant screening"]},
                "papers": [
                    paper("Demo Paper: Predicting Late Rent Payments from Application Data", 2024, "Example Journal of Housing", "A. Placeholder", 41, "same_domain", 0.871, lorem),
                    paper("Demo Paper: Fairness in Automated Tenant Screening", 2023, "Sample Conference on Fairness", "B. Example", 88, "same_domain", 0.858, lorem),
                    paper("Demo Paper: Gradient Boosting for Payment Default Risk", 2022, "Fictional Review of Credit", "C. Sample", 302, "same_domain", 0.844, lorem),
                    paper("Demo Paper: Explainable Credit Scoring with Monotonic Constraints", 2024, None, "D. Demo", 19, "same_domain", 0.832, lorem),
                ]}
    if task == "weather":
        from datetime import datetime
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        hour = lambda n: (now + timedelta(hours=n)).strftime("%Y-%m-%dT%H:%M")
        icons = ["partly", "partly", "cloudy", "cloudy", "rain", "rain", "cloudy", "clear"]
        days = [("partly", "Partly cloudy", 66, 51, 20), ("rain", "Rain", 59, 48, 80), ("cloudy", "Overcast", 61, 47, 30),
                ("clear", "Clear", 68, 50, 0), ("storm", "Thunderstorm", 71, 58, 60)]
        return {
            "place": {"name": inp.get("place", "Example City"), "region": "Demo State", "country": "Demo"},
            "units": {"temp": "°F", "wind": "mph"},
            "current": {"temp": 64, "feels_like": 62, "humidity": 58, "wind": 9, "is_day": True,
                        "summary": "Partly cloudy", "icon": "partly"},
            "today": {"date": day(0), "high": 66, "low": 51, "rain": 20, "summary": "Partly cloudy", "icon": "partly",
                      "sunrise": f"{day(0)}T06:58", "sunset": f"{day(0)}T18:21"},
            "hours": [{"time": hour(n), "temp": 64 - n // 2, "rain": 10 * n, "is_day": (now + timedelta(hours=n)).hour in range(7, 18),
                       "icon": icons[n]} for n in range(8)],
            "days": [{"date": day(i), "icon": ic, "summary": su, "high": hi, "low": lo, "rain": ra}
                     for i, (ic, su, hi, lo, ra) in enumerate(days)],
        }
    raise ValueError(task)


def child(task: str, inp: dict) -> None:
    steps = {
        "balance": ["Reading First Demo Bank", "Reading Example Credit Union", "Reading Sample Savings & Loan"],
        "subscriptions": ["Downloading transactions (1/3)", "Downloading transactions (2/3)", "Downloading transactions (3/3)", "Grouping charges by merchant"],
        "email": ["  fetched 20/64", "  fetched 64/64", "  classified 16/38", "  classified 38/38"],
        "weather": [f"Locating {inp.get('place', '')}", "Fetching forecast"],
        "research": ["same_domain queries: tenants pay rent late; rent payment default", "Searching OpenAlex (1/3)",
                     "Searching OpenAlex (2/3)", "Searching OpenAlex (3/3)", "412 unique candidate papers",
                     "Loading SPECTER2...", "Embedded 37 new papers (375 from cache). Ranking..."],
    }[task]
    for line in steps:
        print(line, file=sys.stderr, flush=True)
        time.sleep(0.35)
    print(json.dumps(fake_result(task, inp)))


def demo_task(task: str) -> Task:
    real = cap.TASKS[task]
    def argv(inp: dict) -> list:
        real.argv(inp)  # same input validation as the real task (builds the real command but never runs it)
        return [sys.executable, str(HERE / "demo.py"), "--child", task, json.dumps(inp)]
    return Task(HERE, argv, 60)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--child"]:
        child(sys.argv[2], json.loads(sys.argv[3]))
    else:
        cap.run({t: demo_task(t) for t in cap.TASKS}, PORT, mode="demo")
