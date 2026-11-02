"""Rush Cricket match engine v2 (pure logic, no Discord code).

HOW A BALL WORKS
  Bowler picks WHERE the ball lands on a 3x3 grid: line (off / middle / leg) x length (full / good / short).
  Batter picks a SHOT. Every shot is good for some zones and bad for others, so picking a shot
  is a guess where the ball will land (the mind game). Both choose at the same time.

  contact quality q (0..1) comes from:
    shot fit to the zone (biggest part) + batter vs bowler skill + how "set" the batter is
    + new-ball swing / old-ball reverse swing / spin on a worn pitch / dew
    + bowler "setup" (two balls on one line, then a change of line) + bowler stamina
    + small random part
  Then the OVER PLAN changes the risk:
    batting intent  Defend / Rotate / Attack   (attack = more boundaries, more wickets)
    bowling field   Attacking / Balanced / Defensive
  and PRESSURE (dot-ball streak, required rate) makes mistakes more likely.

  Gap ball: some singles offer the batter "push for 2" (risk of a run out).
  Extras: wides and no-balls (free hit: only a run out can dismiss the batter).

Nothing here talks to Discord: ui.py calls MatchState methods and shows the result.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

LINES = ("off", "middle", "leg")
LENGTHS = ("full", "good", "short")
ZONES = [(ln, lg) for lg in LENGTHS for ln in LINES]          # grid order: full row, good row, short row
ZONE_LABEL = {(ln, lg): f"{ln.title()} {lg.title()}" for ln, lg in ZONES}

# shot -> label, zone fit (missing zone = 0.25), power (boundary size), air (catch risk / six share)
SHOTS = {
    "drive":  {"label": "Drive", "power": 0.80, "air": 0.25,
               "fit": {("off", "full"): 1.0, ("middle", "full"): 0.9, ("off", "good"): 0.6,
                       ("middle", "good"): 0.5, ("leg", "full"): 0.4}},
    "cut":    {"label": "Cut", "power": 0.75, "air": 0.20,
               "fit": {("off", "short"): 1.0, ("off", "good"): 0.7, ("middle", "short"): 0.45}},
    "pull":   {"label": "Pull", "power": 0.90, "air": 0.45,
               "fit": {("middle", "short"): 1.0, ("leg", "short"): 0.95, ("off", "short"): 0.5,
                       ("leg", "good"): 0.45}},
    "flick":  {"label": "Flick", "power": 0.65, "air": 0.20,
               "fit": {("leg", "full"): 1.0, ("leg", "good"): 0.9, ("middle", "full"): 0.65,
                       ("middle", "good"): 0.55}},
    "sweep":  {"label": "Sweep", "power": 0.75, "air": 0.30,
               "fit": {("leg", "full"): 0.95, ("middle", "full"): 0.85, ("leg", "good"): 0.8,
                       ("middle", "good"): 0.55, ("off", "full"): 0.5}},
    "loft":   {"label": "Loft", "power": 1.00, "air": 0.90,
               "fit": {("middle", "full"): 0.9, ("leg", "full"): 0.85, ("off", "full"): 0.8,
                       ("middle", "good"): 0.6, ("leg", "good"): 0.55, ("off", "good"): 0.5}},
    "defend": {"label": "Defend", "power": 0.0, "air": 0.05,
               "fit": {z: 0.85 for z in ZONES if z[1] != "short"} | {("middle", "short"): 0.7,
                                                                     ("off", "short"): 0.7, ("leg", "short"): 0.6}},
    "leave":  {"label": "Leave", "power": 0.0, "air": 0.0, "fit": {}},
}
SHOT_ORDER = ["drive", "cut", "pull", "flick", "sweep", "loft", "defend", "leave"]

INTENTS = {"defend": "Defend", "rotate": "Rotate", "attack": "Attack"}
FIELDS = {"attack": "Attacking", "balanced": "Balanced", "defend": "Defensive"}
INTENT_W = {"defend": 0.55, "rotate": 1.0, "attack": 1.5}     # wicket risk
INTENT_B = {"defend": 0.40, "rotate": 1.00, "attack": 1.40}   # boundary chance
INTENT_R = {"defend": -0.10, "rotate": 0.12, "attack": 0.0}   # running (singles)
FIELD_W = {"attack": 1.25, "balanced": 1.0, "defend": 0.85}
FIELD_B = {"attack": 1.20, "balanced": 1.0, "defend": 0.70}
FIELD_R = {"attack": -0.05, "balanced": 0.0, "defend": 0.15}
PUSH_OK = {"attack": 0.55, "balanced": 0.65, "defend": 0.78}  # chance the second run is safe
PAR_RPO = 8.2


@dataclass
class Bat:
    runs: int = 0
    balls: int = 0
    fours: int = 0
    sixes: int = 0
    out: str | None = None


@dataclass
class Bowl:
    balls: int = 0
    runs: int = 0
    wkts: int = 0
    overs_done: int = 0
    stamina: float = 1.0
    lines: list = field(default_factory=list)   # last lines bowled (for the setup combo)


@dataclass
class Innings:
    bat_team: int
    runs: int = 0
    wkts: int = 0
    balls: int = 0
    extras: int = 0
    striker: int = 0
    non_striker: int = 1
    next_in: int = 2
    bat: dict = field(default_factory=dict)       # xi index -> Bat
    bowl: dict = field(default_factory=dict)      # xi index -> Bowl
    over_log: list = field(default_factory=list)  # symbols of the current over
    overs: list = field(default_factory=list)     # finished overs: (bowler idx, [symbols], runs)
    last_bowler: int | None = None
    fall: list = field(default_factory=list)


class MatchState:
    def __init__(self, team_a: dict, team_b: dict, overs: int = 5, seed: int | None = None):
        self.rng = random.Random(seed)
        self.teams = [team_a, team_b]
        self.overs = max(1, min(20, int(overs)))
        self.max_per_bowler = max(1, math.ceil(self.overs / 5))
        self.night = self.rng.random() < 0.5           # dew in the second innings
        self.inn: list[Innings] = []
        self.target: int | None = None
        self.result: str | None = None
        self.winner: int | None = None
        # over plan
        self.bowler: int | None = None
        self.field = "balanced"
        self.intent = "rotate"
        self.dots = 0
        self.free_hit = False
        self.pending_run: dict | None = None            # gap ball waiting for "push for 2?"
        self.need_plan = True

    # ── setup ─────────────────────────────────────────────────────────────────
    def start(self, batting_first: int) -> None:
        self.inn = [Innings(bat_team=batting_first)]
        self._init_innings(self.inn[0])

    def _init_innings(self, inn: Innings) -> None:
        for i in range(11):
            inn.bat[i] = Bat()
        self.need_plan = True
        self.dots = 0
        self.free_hit = False
        self.intent = "rotate"
        self.field = "balanced"
        self.bowler = None

    @property
    def cur(self) -> Innings:
        return self.inn[-1]

    @property
    def bat_team(self) -> int:
        return self.cur.bat_team

    @property
    def bowl_team(self) -> int:
        return 1 - self.cur.bat_team

    def xi(self, team: int) -> list:
        return self.teams[team]["xi"]

    def striker(self) -> dict:
        return self.xi(self.bat_team)[self.cur.striker]

    def bowler_card(self) -> dict | None:
        return None if self.bowler is None else self.xi(self.bowl_team)[self.bowler]

    def over_text(self) -> str:
        return f"{self.cur.balls // 6}.{self.cur.balls % 6}"

    # ── over plan ─────────────────────────────────────────────────────────────
    def allowed_bowlers(self) -> list[int]:
        inn = self.cur
        out = []
        for i, p in enumerate(self.xi(self.bowl_team)):
            done = inn.bowl.get(i, Bowl()).overs_done
            if i == inn.last_bowler or done >= self.max_per_bowler:
                continue
            out.append(i)
        return out or [i for i in range(11) if i != inn.last_bowler]

    def set_plan(self, bowler: int, fld: str, intent: str) -> str | None:
        if bowler not in self.allowed_bowlers():
            return "That bowler can't bowl this over."
        self.bowler = bowler
        self.field = fld if fld in FIELDS else "balanced"
        self.intent = intent if intent in INTENTS else "rotate"
        self.cur.bowl.setdefault(bowler, Bowl())
        self.need_plan = False
        return None

    # ── maths helpers ─────────────────────────────────────────────────────────
    def _bowl_skill(self, card: dict, st: Bowl) -> float:
        base = card["bowl"] if card.get("bowl_type") else min(card["bowl"], 35)
        return base * (0.85 + 0.15 * st.stamina)

    def _fit(self, shot: str, zone: tuple, btype: str | None) -> float:
        f = SHOTS[shot]["fit"].get(zone, 0.25 if shot not in ("defend", "leave") else 0.4)
        if shot == "sweep" and btype == "pace":
            f *= 0.6
        if shot == "cut" and btype == "spin" and zone[1] == "short":
            f = min(1.0, f + 0.1)
        return f

    def crr(self) -> float:
        b = self.cur.balls
        return self.cur.runs * 6 / b if b else 0.0

    def rrr(self) -> float | None:
        if self.target is None:
            return None
        left = self.overs * 6 - self.cur.balls
        need = self.target - self.cur.runs
        return need * 6 / left if left > 0 else 99.0

    # ── one ball ──────────────────────────────────────────────────────────────
    def bowl_ball(self, zone: tuple, shot: str) -> dict:
        """Play one ball. Returns a result dict for the UI (see _result)."""
        assert not self.need_plan and self.pending_run is None and self.result is None
        inn = self.cur
        bcard = self.bowler_card()
        st = inn.bowl[self.bowler]
        bat_i = inn.striker
        batter = self.xi(self.bat_team)[bat_i]
        bs = inn.bat[bat_i]
        btype = bcard.get("bowl_type") or "pace"
        rng = self.rng
        notes = []

        # extras first
        wide_p = 0.010 + (0.03 if (btype == "pace" and zone[0] == "leg") else 0) + \
            (0.015 if zone == ("off", "short") else 0) + (0.02 if not bcard.get("bowl_type") else 0)
        nb_p = 0.010 if btype == "pace" else 0.003
        r = rng.random()
        if r < wide_p:
            return self._extra("Wd", zone, shot, bcard, batter)
        no_ball = r < wide_p + nb_p
        free_hit_now = self.free_hit
        self.free_hit = False

        if shot == "leave":
            return self._leave(zone, bcard, batter, no_ball, free_hit_now)

        # contact quality
        fit = self._fit(shot, zone, btype)
        skill = (batter["bat"] - self._bowl_skill(bcard, st)) / 100
        set_b = -0.08 if bs.balls < 4 else min(bs.balls, 24) / 24 * 0.12
        q = 0.18 + fit * 0.65 + skill * 0.35 + set_b
        over_no = inn.balls // 6
        if btype == "pace" and over_no < 4 and zone[1] in ("full", "good"):
            q -= 0.05
            notes.append("swing")
        if btype == "pace" and over_no >= max(3, int(self.overs * 0.75)) and zone[1] == "full":
            q -= 0.04
            notes.append("reverse")
        if btype == "spin" and (len(self.inn) == 2 or over_no >= self.overs / 2):
            q -= 0.04
            notes.append("turn")
        if self.night and len(self.inn) == 2:
            q += 0.03 if btype == "spin" else 0.01
        setup = len(st.lines) >= 2 and st.lines[-1] == st.lines[-2] and zone[0] != st.lines[-1]
        if setup:
            q -= 0.08
            notes.append("setup")
        q += rng.gauss(0, 0.11)
        q = max(0.0, min(1.0, q))

        # wicket?
        rrr = self.rrr()
        gap = max(0.0, (rrr - self.crr())) if rrr is not None else 0.0
        pressure = 1 + 0.04 * min(self.dots, 6) + 0.04 * min(gap, 4)
        air = SHOTS[shot]["air"]
        w = (0.032 + max(0.0, 0.52 - q) * 0.6) * INTENT_W[self.intent] * FIELD_W[self.field] * pressure * (0.8 + air * 0.5)
        if shot == "defend":
            w *= 0.45
        if not free_hit_now and not no_ball and rng.random() < w:
            how = self._dismissal(zone, shot, btype, q)
            return self._wicket(how, zone, shot, bcard, batter, notes)

        # runs
        if shot == "defend":
            b_p = 0.0
        else:
            b_p = max(0.0, q - 0.38) * SHOTS[shot]["power"] * 1.85 * INTENT_B[self.intent] * FIELD_B[self.field]
        r = rng.random()
        if r < b_p:
            six = rng.random() < air * 0.6 + (0.1 if shot == "pull" else 0)
            runs = 6 if six else 4
        else:
            run_p = 0.46 + q * 0.3 + INTENT_R[self.intent] + FIELD_R[self.field]
            if shot == "defend":
                run_p *= 0.45
            if rng.random() < run_p:
                x = rng.random()
                runs = 1 if (x < 0.76 or shot == "defend") else (2 if x < 0.96 else 3)
            else:
                runs = 0
        gap_ball = runs == 1 and shot != "defend" and rng.random() < 0.45
        return self._runs(runs, zone, shot, bcard, batter, notes, no_ball, gap_ball)

    def _dismissal(self, zone, shot, btype, q) -> str:
        rng = self.rng
        if shot in ("loft", "pull", "sweep") and rng.random() < 0.75:
            return "CAUGHT"
        if zone[0] in ("middle", "leg") and zone[1] in ("full", "good") and q < 0.4:
            return rng.choice(["BOWLED", "LBW", "LBW"]) if btype == "pace" else rng.choice(["BOWLED", "LBW", "STUMPED"])
        if zone[0] == "off":
            return "CAUGHT"
        return rng.choice(["CAUGHT", "BOWLED", "LBW"])

    # ── outcome bookkeeping ───────────────────────────────────────────────────
    def _leave(self, zone, bcard, batter, no_ball, free_hit_now) -> dict:
        inn, st = self.cur, self.cur.bowl[self.bowler]
        if zone[0] == "middle" and zone[1] != "short" and not no_ball and not free_hit_now and self.rng.random() < 0.35:
            return self._wicket(self.rng.choice(["BOWLED", "LBW"]), zone, "leave", bcard, batter, [])
        return self._runs(0, zone, "leave", bcard, batter, [], no_ball, False)

    def _extra(self, kind, zone, shot, bcard, batter) -> dict:
        inn, st = self.cur, self.cur.bowl[self.bowler]
        inn.runs += 1
        inn.extras += 1
        st.runs += 1
        inn.over_log.append("Wd")
        res = self._result("Wd", zone, shot, bcard, batter, runs=0, extra=1, wicket=None, notes=[])
        self._check_end()
        return res

    def _runs(self, runs, zone, shot, bcard, batter, notes, no_ball, gap_ball) -> dict:
        inn, st = self.cur, self.cur.bowl[self.bowler]
        bs = inn.bat[inn.striker]
        if no_ball:
            inn.runs += 1
            inn.extras += 1
            st.runs += 1
            self.free_hit = True
        bs.runs += runs
        bs.fours += runs == 4
        bs.sixes += runs == 6
        inn.runs += runs
        st.runs += runs
        if not no_ball:
            bs.balls += 1
            st.balls += 1
            inn.balls += 1
        st.lines.append(zone[0])
        self.dots = self.dots + 1 if runs == 0 and not no_ball else 0
        sym = ("NB" + (str(runs) if runs else "")) if no_ball else ("•" if runs == 0 else str(runs))
        inn.over_log.append(sym)
        res = self._result("NB" if no_ball else str(runs), zone, shot, bcard, batter, runs=runs,
                           extra=1 if no_ball else 0, wicket=None, notes=notes)
        if gap_ball and self.target_left() > 1:
            self.pending_run = {"result": res}
            res["pending_run"] = True
            return res
        self._after_ball(runs)
        return res

    def target_left(self) -> int:
        return 99 if self.target is None else self.target - self.cur.runs

    def resolve_run(self, push: bool) -> dict:
        """Gap ball: take the safe single (push=False) or push for 2."""
        assert self.pending_run is not None
        inn = self.cur
        self.pending_run = None
        bs = inn.bat[inn.striker]
        st = inn.bowl[self.bowler]
        if not push:
            self._after_ball(1)
            return {"event": "1", "text": "They settle for the single."}
        r = self.rng.random()
        ok = PUSH_OK[self.field]
        if r < ok:
            bs.runs += 1
            inn.runs += 1
            st.runs += 1
            inn.over_log[-1] = "2"
            self._after_ball(2)
            return {"event": "2", "text": "They push hard and make it back for two."}
        if r < ok + 0.4 * (1 - ok):
            # the batter who was running to the danger end is out (the striker, simple model)
            name = self.xi(self.bat_team)[inn.striker]["name"]
            inn.over_log[-1] = "1W"
            self._fall(inn.striker, "RUN OUT")
            self._after_ball(1, wicket=True)
            return {"event": "W", "text": f"Direct hit while coming back for two. {name} is RUN OUT."}
        self._after_ball(1)
        return {"event": "1", "text": "Sharp throw, they turn back. Just the one."}

    def _fall(self, idx: int, how: str) -> None:
        inn = self.cur
        inn.bat[idx].out = how
        inn.wkts += 1
        inn.fall.append((inn.runs, inn.wkts, idx))
        if inn.next_in <= 10:
            if idx == inn.striker:
                inn.striker = inn.next_in
            else:
                inn.non_striker = inn.next_in
            inn.next_in += 1

    def _wicket(self, how, zone, shot, bcard, batter, notes) -> dict:
        inn, st = self.cur, self.cur.bowl[self.bowler]
        bs = inn.bat[inn.striker]
        bs.balls += 1
        st.balls += 1
        inn.balls += 1
        st.wkts += how != "RUN OUT"
        st.lines.append(zone[0])
        self.dots = 0
        inn.over_log.append("W")
        res = self._result("W", zone, shot, bcard, batter, runs=0, extra=0, wicket=how, notes=notes)
        self._fall(inn.striker, how)
        self._after_ball(0, wicket=True)
        return res

    def _after_ball(self, runs: int, wicket: bool = False) -> None:
        inn = self.cur
        if runs % 2 == 1:
            inn.striker, inn.non_striker = inn.non_striker, inn.striker
        if self._check_end():
            return
        if inn.balls % 6 == 0 and inn.balls > 0 and inn.over_log and not self._over_closed():
            self._end_over()

    def _over_closed(self) -> bool:
        return getattr(self, "_closed_at", -1) == self.cur.balls

    def _end_over(self) -> None:
        inn = self.cur
        st = inn.bowl[self.bowler]
        st.overs_done += 1
        st.stamina = max(0.4, st.stamina - (0.07 if (self.bowler_card().get("bowl_type") == "pace") else 0.03))
        inn.overs.append((self.bowler, list(inn.over_log), self._over_runs()))
        inn.over_log = []
        inn.last_bowler = self.bowler
        inn.striker, inn.non_striker = inn.non_striker, inn.striker
        self._closed_at = inn.balls
        self.need_plan = True
        self.bowler = None

    def _over_runs(self) -> int:
        total = 0
        for s in self.cur.over_log:
            if s in ("•", "W"):
                continue
            if s == "Wd":
                total += 1
            elif s.startswith("NB"):
                total += 1 + (int(s[2:]) if s[2:] else 0)
            elif s.endswith("W"):
                total += int(s[:-1] or 0)
            else:
                total += int(s)
        return total

    def _check_end(self) -> bool:
        inn = self.cur
        chased = self.target is not None and inn.runs >= self.target
        done = inn.wkts >= 10 or inn.balls >= self.overs * 6 or chased
        if not done:
            return False
        if inn.over_log:
            if self.bowler is not None:
                inn.bowl[self.bowler].overs_done += 1 if inn.balls % 6 == 0 else 0
            inn.overs.append((self.bowler, list(inn.over_log), self._over_runs()))
            inn.over_log = []
        if len(self.inn) == 1:
            self.target = inn.runs + 1
            self.inn.append(Innings(bat_team=1 - inn.bat_team))
            self._init_innings(self.inn[-1])
            self.innings_break = True
            return True
        a, b = self.inn[0], self.inn[1]
        if b.runs >= self.target:
            self.winner = b.bat_team
            self.result = f"{self.teams[b.bat_team]['name']} won by {10 - b.wkts} wicket{'s' if 10 - b.wkts != 1 else ''}"
        elif b.runs == self.target - 1:
            self.winner = None
            self.result = "Match tied"
        else:
            self.winner = a.bat_team
            m = self.target - 1 - b.runs
            self.result = f"{self.teams[a.bat_team]['name']} won by {m} run{'s' if m != 1 else ''}"
        self.need_plan = False
        return True

    # ── result + commentary ───────────────────────────────────────────────────
    def _result(self, event, zone, shot, bcard, batter, runs, extra, wicket, notes) -> dict:
        return {
            "event": event, "zone": zone, "shot": shot, "runs": runs, "extra": extra, "wicket": wicket,
            "bowler": bcard["name"], "batter": batter["name"], "notes": notes,
            "ball": self.over_text(), "free_hit": self.free_hit,
            "text": commentary(event, zone, shot, bcard, batter, wicket, notes, self.rng),
            "pending_run": False,
        }

    # ── win probability (team 0) ──────────────────────────────────────────────
    def win_prob(self) -> float:
        if self.result:
            return 1.0 if self.winner == 0 else (0.0 if self.winner == 1 else 0.5)
        inn = self.cur
        balls_left = self.overs * 6 - inn.balls
        wl = 10 - inn.wkts
        if self.target is None:
            rr = (self.crr() * inn.balls + PAR_RPO * 6 * 2) / (inn.balls + 12)
            proj = inn.runs + rr * balls_left / 6 * (0.55 + 0.45 * wl / 10)
            par = PAR_RPO * self.overs
            p_bat = 1 / (1 + math.exp(-(proj - par) / (self.overs * 1.7 + 4)))
        else:
            need = self.target - inn.runs
            if need <= 0:
                p_bat = 1.0
            elif wl <= 0 or balls_left <= 0:
                p_bat = 0.0
            else:
                res = balls_left / 6 * PAR_RPO * (0.35 + 0.65 * wl / 10)
                p_bat = 1 / (1 + math.exp(-(res - need) / (3 + math.sqrt(balls_left) * 1.3)))
        return p_bat if self.bat_team == 0 else 1 - p_bat


# ── AI ───────────────────────────────────────────────────────────────────────

PACE_PRIOR = {("off", "good"): 3.0, ("off", "full"): 2.2, ("middle", "full"): 2.0, ("middle", "good"): 1.6,
              ("middle", "short"): 1.4, ("off", "short"): 0.9, ("leg", "full"): 0.7, ("leg", "good"): 0.6,
              ("leg", "short"): 0.6}
SPIN_PRIOR = {("off", "good"): 3.0, ("middle", "good"): 2.6, ("off", "full"): 1.8, ("middle", "full"): 1.6,
              ("leg", "good"): 1.0, ("leg", "full"): 0.9, ("off", "short"): 0.4, ("middle", "short"): 0.3,
              ("leg", "short"): 0.2}


def ai_zone(m: MatchState) -> tuple:
    card = m.bowler_card()
    prior = SPIN_PRIOR if card.get("bowl_type") == "spin" else PACE_PRIOR
    st = m.cur.bowl[m.bowler]
    w = dict(prior)
    if len(st.lines) >= 2 and st.lines[-1] == st.lines[-2] and m.rng.random() < 0.5:   # try the setup
        for z in w:
            if z[0] != st.lines[-1]:
                w[z] *= 2.2
    zs = list(w)
    return m.rng.choices(zs, weights=[w[z] for z in zs])[0]


def ai_shot(m: MatchState) -> str:
    card = m.bowler_card()
    btype = card.get("bowl_type") or "pace"
    prior = SPIN_PRIOR if btype == "spin" else PACE_PRIOR
    tot = sum(prior.values())
    best, scores = None, {}
    for s in SHOT_ORDER[:-1]:
        exp = sum(prior[z] / tot * m._fit(s, z, btype) for z in ZONES)
        bonus = SHOTS[s]["power"] * (0.25 if m.intent == "attack" else 0.1 if m.intent == "rotate" else -0.1)
        scores[s] = exp + bonus + m.rng.gauss(0, 0.12)
    return max(scores, key=scores.get)


def ai_plan(m: MatchState, side: str) -> tuple:
    """side = 'bowl' -> (bowler, field); side = 'bat' -> intent."""
    over_no = m.cur.balls // 6
    if side == "bowl":
        inn = m.cur
        opts = m.allowed_bowlers()
        xi = m.xi(m.bowl_team)

        def score(i):
            st = inn.bowl.get(i, Bowl())
            return xi[i]["bowl"] * (0.85 + 0.15 * st.stamina) + m.rng.random() * 6
        bowler = max(opts, key=score)
        rrr = m.rrr()
        if over_no < 2 or inn.wkts >= 7:
            fld = "attack"
        elif (rrr is not None and rrr > 10) or over_no >= m.overs - 2:
            fld = "defend"
        else:
            fld = "balanced"
        return bowler, fld
    rrr = m.rrr()
    if rrr is not None:
        return "attack" if rrr > m.crr() + 1.5 or rrr > 10 else ("defend" if m.cur.wkts >= 7 and rrr < 7 else "rotate")
    if over_no >= m.overs - 2 and m.cur.wkts < 8:
        return "attack"
    return "defend" if m.cur.wkts >= 6 else "rotate"


def ai_push(m: MatchState) -> bool:
    rrr = m.rrr()
    return (rrr is not None and rrr > 9) or m.field == "defend"


# ── commentary (no emoji) ────────────────────────────────────────────────────

def _surname(n: str) -> str:
    return n.split()[-1]


def commentary(event, zone, shot, bcard, batter, wicket, notes, rng) -> str:
    b, k = _surname(bcard["name"]), _surname(batter["name"])
    where = f"{zone[1]} on {zone[0]}" if zone else ""
    lbl = SHOTS[shot]["label"].lower() if shot in SHOTS else shot
    if event == "Wd":
        return rng.choice([f"{b} strays down the leg side. Wide.", f"Too wide from {b}. Extra run."])
    if event == "W":
        lines = {
            "BOWLED": [f"{b} goes {where} and {k} misses the {lbl}. BOWLED.",
                       f"Through the gate. {k} is BOWLED by {b}."],
            "LBW": [f"{k} plays across the line, struck in front. LBW.",
                    f"Trapped on the crease, the finger goes up. LBW."],
            "CAUGHT": [f"{k} goes for the {lbl}, it flies high and is taken. CAUGHT.",
                       f"Edge from {k} and the keeper makes no mistake. CAUGHT."],
            "STUMPED": [f"{k} dances down, misses, and the bails are off. STUMPED."],
        }
        txt = rng.choice(lines.get(wicket, [f"{k} is out."]))
        if "setup" in notes:
            txt += f" {b} set that one up."
        return txt
    runs = int(event) if event.isdigit() else 0
    if event == "NB":
        return f"No ball from {b}. Free hit next."
    if runs == 6:
        return rng.choice([f"{k} picks the {where} ball and lofts it into the stands. SIX.",
                           f"Huge {lbl} from {k}. That has gone all the way. SIX."])
    if runs == 4:
        return rng.choice([f"{k} times the {lbl} beautifully, races to the rope. FOUR.",
                           f"Gap found. {k}'s {lbl} beats the fielder. FOUR."])
    if runs in (2, 3):
        return f"{k} works it into the gap, they come back for {runs}."
    if runs == 1:
        return rng.choice([f"{k} nudges it and takes a single.", f"Soft hands from {k}, quick single."])
    if shot == "leave":
        return f"{k} shoulders arms. Left alone."
    extra = {"swing": " It swung late.", "reverse": " Reversing now.", "turn": " Big turn off the surface."}
    tail = next((extra[n] for n in notes if n in extra), "")
    return rng.choice([f"{b} lands it {where}, {k} can't get it away. Dot.",
                       f"Good ball from {b}. {k} defends."]) + tail
