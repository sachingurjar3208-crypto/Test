"""Player pool, starter XI and a tiny JSON store (test bot only).

Every player: name, role (BAT / WK / AR / BOWL), bat (0-100), bowl (0-100),
bowl_type ("pace" / "spin" / None), hand ("R" / "L").

rcstart gives a user 11 random players that follow the XI rules of the main bot:
    WK 1, BAT 5, AR 2, BOWL 3   (at least 1 pace + 1 spin bowling option)
Batting order: BAT, WK, AR, BOWL (best batter first).
"""
from __future__ import annotations

import json
import random
import threading
from pathlib import Path

DATA_FILE = Path(__file__).with_name("data") / "teams.json"
_LOCK = threading.Lock()

# name, role, bat, bowl, bowl_type, hand
POOL = [
    # batters
    ("Shubman Gill", "BAT", 91, 10, None, "R"), ("Shreyas Iyer", "BAT", 89, 15, None, "R"),
    ("Yashasvi Jaiswal", "BAT", 88, 12, None, "L"), ("Suryakumar Yadav", "BAT", 90, 10, None, "R"),
    ("Tilak Varma", "BAT", 86, 35, "spin", "L"), ("Rinku Singh", "BAT", 84, 10, None, "L"),
    ("Rajat Patidar", "BAT", 83, 8, None, "R"), ("Abhishek Sharma", "BAT", 85, 40, "spin", "L"),
    ("Babar Azam", "BAT", 88, 8, None, "R"), ("Joe Root", "BAT", 89, 38, "spin", "R"),
    ("Travis Head", "BAT", 88, 30, "spin", "L"), ("Kane Williamson", "BAT", 87, 20, "spin", "R"),
    ("Harry Brook", "BAT", 86, 10, None, "R"), ("David Miller", "BAT", 84, 5, None, "L"),
    # keepers
    ("Rishabh Pant", "WK", 88, 5, None, "L"), ("KL Rahul", "WK", 86, 5, None, "R"),
    ("Ishan Kishan", "WK", 84, 5, None, "L"), ("Jos Buttler", "WK", 89, 5, None, "R"),
    ("Mohammad Rizwan", "WK", 85, 5, None, "R"), ("Heinrich Klaasen", "WK", 87, 5, None, "R"),
    # all-rounders
    ("Hardik Pandya", "AR", 85, 82, "pace", "R"), ("Ravindra Jadeja", "AR", 82, 86, "spin", "L"),
    ("Axar Patel", "AR", 78, 84, "spin", "L"), ("Shivam Dube", "AR", 82, 70, "pace", "L"),
    ("Washington Sundar", "AR", 74, 80, "spin", "L"), ("Glenn Maxwell", "AR", 84, 74, "spin", "R"),
    ("Ben Stokes", "AR", 84, 80, "pace", "L"), ("Marcus Stoinis", "AR", 80, 74, "pace", "R"),
    ("Rashid Khan", "AR", 62, 92, "spin", "R"), ("Sikandar Raza", "AR", 80, 82, "spin", "R"),
    # bowlers
    ("Jasprit Bumrah", "BOWL", 25, 96, "pace", "R"), ("Mohammed Siraj", "BOWL", 20, 87, "pace", "R"),
    ("Arshdeep Singh", "BOWL", 22, 88, "pace", "L"), ("Kuldeep Yadav", "BOWL", 25, 89, "spin", "L"),
    ("Varun Chakravarthy", "BOWL", 15, 87, "spin", "R"), ("Harshal Patel", "BOWL", 35, 84, "pace", "R"),
    ("Mitchell Starc", "BOWL", 35, 91, "pace", "L"), ("Pat Cummins", "BOWL", 50, 90, "pace", "R"),
    ("Jofra Archer", "BOWL", 30, 90, "pace", "R"), ("Adam Zampa", "BOWL", 20, 86, "spin", "R"),
    ("Trent Boult", "BOWL", 25, 88, "pace", "L"), ("Noor Ahmad", "BOWL", 15, 86, "spin", "L"),
    ("Shaheen Afridi", "BOWL", 30, 89, "pace", "L"), ("Kartik Tyagi", "BOWL", 15, 80, "pace", "R"),
]
NEED = {"BAT": 5, "WK": 1, "AR": 2, "BOWL": 3}
ORDER = {"BAT": 0, "WK": 1, "AR": 2, "BOWL": 3}


def _row(t) -> dict:
    name, role, bat, bowl, btype, hand = t
    return {"name": name, "role": role, "bat": bat, "bowl": bowl, "bowl_type": btype, "hand": hand,
            "ovr": round(bat * 0.9 + bowl * 0.1) if role in ("BAT", "WK") else
                   round(bowl * 0.9 + bat * 0.1) if role == "BOWL" else round((bat + bowl) / 2)}


ALL = [_row(t) for t in POOL]


def random_xi(rng: random.Random | None = None) -> list[dict]:
    """11 players following NEED, with at least one pace AND one spin option. Batting order."""
    rng = rng or random.Random()
    for _ in range(200):
        xi = []
        for role, n in NEED.items():
            xi += rng.sample([p for p in ALL if p["role"] == role], n)
        types = {p["bowl_type"] for p in xi if p["role"] in ("AR", "BOWL")}
        if {"pace", "spin"} <= types:
            break
    xi.sort(key=lambda p: (ORDER[p["role"]], -p["bat"]))
    return [dict(p) for p in xi]


def _load() -> dict:
    try:
        return json.loads(DATA_FILE.read_text("utf-8"))
    except Exception:
        return {}


def get_team(user_id: int) -> dict | None:
    with _LOCK:
        return _load().get(str(user_id))


def create_team(user_id: int, name: str) -> dict:
    """Give the user a starter XI (replaces an old one)."""
    with _LOCK:
        data = _load()
        team = {"name": name[:24], "xi": random_xi()}
        data[str(user_id)] = team
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(json.dumps(data, indent=1), "utf-8")
        return team


def bot_team(name: str = "RUSH AI XI") -> dict:
    return {"name": name, "xi": random_xi()}
