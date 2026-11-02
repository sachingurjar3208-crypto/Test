"""What the match looks like.

    live_text(m, lines)  -> text for the ONE live match message (edited every ball)
    over_card(m)         -> PNG bytes: TV-style scoreboard shown after every over
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import engine as E

FONTS = Path(__file__).with_name("fonts")
W, H = 1200, 470
NAVY1, NAVY2 = (12, 18, 40), (24, 34, 72)
GOLD = (240, 198, 96)
WHITE = (240, 244, 255)
DIM = (150, 165, 205)
COL_A, COL_B = (64, 140, 255), (255, 92, 92)
CHIP = {"4": (52, 120, 255), "6": (150, 70, 230), "W": (230, 60, 60), "•": (70, 80, 110),
        "Wd": (220, 170, 40), "NB": (220, 170, 40)}


def _f(size: int, bold: bool = True):
    try:
        return ImageFont.truetype(str(FONTS / ("display_bold.ttf" if bold else "label.ttf")), size)
    except Exception:
        return ImageFont.load_default()


_SAFE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .")


def _ff(text: str, size: int, bold: bool = True):
    """display_bold.ttf has no / % - * etc., so text with those uses label.ttf."""
    return _f(size, bold and set(text) <= _SAFE)


def _bar(p: float, width: int = 14) -> str:
    n = max(0, min(width, round(p * width)))
    return "█" * n + "░" * (width - n)


def short(name: str, n: int = 12) -> str:
    return name if len(name) <= n else name.split()[-1][:n]


# ── live message text ────────────────────────────────────────────────────────

def live_text(m: E.MatchState, lines: list[str]) -> str:
    """Scoreboard block (monospace) + the last commentary lines (normal text)."""
    if not m.inn:
        return "\n".join(lines)
    inn = m.cur
    ta, tb = m.teams[m.bat_team]["name"], m.teams[m.bowl_team]["name"]
    xi = m.xi(m.bat_team)
    rows = [f"{ta[:16]:<16} {inn.runs}/{inn.wkts}  ({m.over_text()} ov)  RR {m.crr():.2f}"]
    if m.target is not None:
        need = m.target - inn.runs
        left = m.overs * 6 - inn.balls
        rr = m.rrr()
        rows.append(f"Need {max(0, need)} from {left} balls  RRR {rr:.2f}" if rr is not None and need > 0
                    else f"Target {m.target}")
    else:
        rows.append(f"1st innings  ·  {m.overs} overs a side  ·  vs {tb[:14]}")
    rows.append("")
    for idx, star in ((inn.striker, "*"), (inn.non_striker, " ")):
        if idx <= 10 and inn.bat[idx].out is None:
            b = inn.bat[idx]
            rows.append(f"{short(xi[idx]['name']) + star:<14} {b.runs:>3} ({b.balls})")
    if m.bowler is not None:
        st = inn.bowl[m.bowler]
        bn = m.xi(m.bowl_team)[m.bowler]["name"]
        rows.append(f"{short(bn):<14} {st.balls // 6}.{st.balls % 6}-{st.runs}-{st.wkts}")
    rows.append("")
    rows.append("This over: " + ("  ".join(inn.over_log) if inn.over_log else "-"))
    if m.bowler is not None:
        rows.append(f"Field {E.FIELDS[m.field]}  ·  Intent {E.INTENTS[m.intent]}" + ("  ·  FREE HIT" if m.free_hit else ""))
    p = m.win_prob()
    rows.append(f"{short(m.teams[0]['name'], 10):<10} {round(p * 100):>3}% {_bar(p)} {round((1 - p) * 100):>3}% "
                f"{short(m.teams[1]['name'], 10)}")
    block = "```\n" + "\n".join(rows) + "\n```"
    return block + ("\n" + "\n".join(lines) if lines else "")


# ── over-end TV scoreboard ───────────────────────────────────────────────────

def over_card(m: E.MatchState, inn_index: int | None = None) -> bytes:
    """Scoreboard of an innings after its last finished over (default: the current innings,
    or the first one during the innings break)."""
    inn = m.inn[inn_index if inn_index is not None else -1]
    if inn_index is None and not inn.overs and len(m.inn) == 2:
        inn = m.inn[0]
    bt, wt = inn.bat_team, 1 - inn.bat_team
    img = Image.new("RGB", (W, H), NAVY1)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line((0, y, W, y), fill=tuple(int(NAVY1[i] + (NAVY2[i] - NAVY1[i]) * t) for i in range(3)))
    team_col = COL_A if bt == 0 else COL_B

    # top band
    d.rectangle((0, 0, W, 110), fill=(8, 12, 28))
    d.rectangle((0, 0, 14, 110), fill=team_col)
    d.text((40, 30), m.teams[bt]["name"].upper()[:22], font=_ff(m.teams[bt]["name"].upper()[:22], 40), fill=WHITE)
    balls = inn.balls
    d.text((40, 76), f"{balls // 6}.{balls % 6} OVERS  ·  RR {inn.runs * 6 / balls if balls else 0:.2f}",
           font=_f(24, False), fill=DIM)
    score = f"{inn.runs}/{inn.wkts}"
    d.text((W - 40, 56), score, font=_ff(score, 84), fill=GOLD, anchor="rm")
    if m.target is not None and inn is m.inn[-1] and len(m.inn) == 2:
        need = m.target - inn.runs
        left = m.overs * 6 - inn.balls
        txt = f"NEED {max(0, need)} FROM {left}" if need > 0 else "TARGET REACHED"
    else:
        txt = f"vs {m.teams[wt]['name'].upper()[:18]}"
    d.text((W - 40 - d.textlength(score, font=_ff(score, 84)) - 30, 56), txt, font=_f(26, False), fill=WHITE, anchor="rm")

    # batters (the two still in, else the last two)
    xi_b, xi_w = m.xi(bt), m.xi(wt)
    live = [i for i in (inn.striker, inn.non_striker) if i <= 10 and inn.bat[i].out is None]
    y = 140
    d.text((40, y), "BATTING", font=_f(22, False), fill=DIM)
    y += 34
    for i in live[:2]:
        b = inn.bat[i]
        star = "*" if i == inn.striker else ""
        d.text((40, y), xi_b[i]["name"].upper() + star, font=_ff(xi_b[i]["name"].upper() + star, 34), fill=WHITE)
        d.text((560, y), f"{b.runs}", font=_ff(f"{b.runs}", 34), fill=GOLD, anchor="ra")
        d.text((575, y + 6), f"({b.balls})  4s {b.fours}  6s {b.sixes}", font=_f(22, False), fill=DIM)
        y += 48

    # last bowler + this over
    y = 140
    d.text((700, y), "BOWLING", font=_f(22, False), fill=DIM)
    last = inn.overs[-1] if inn.overs else None
    if last and last[0] is not None:
        bi, syms, oruns = last
        st = inn.bowl[bi]
        d.text((700, y + 34), xi_w[bi]["name"].upper(), font=_ff(xi_w[bi]["name"].upper(), 34), fill=WHITE)
        d.text((W - 40, y + 34), f"{st.balls // 6}.{st.balls % 6}-{st.runs}-{st.wkts}", font=_ff(f"{st.balls // 6}.{st.balls % 6}-{st.runs}-{st.wkts}", 34), fill=GOLD, anchor="ra")
        d.text((700, y + 100), f"OVER {len(inn.overs)}  ·  {oruns} RUN{'S' if oruns != 1 else ''}", font=_f(22, False), fill=DIM)
        x = 700
        for s in syms:
            col = CHIP.get(s, CHIP.get(s[:2], (110, 120, 150))) if s not in ("1", "2", "3") else (120, 130, 160)
            if s.endswith("W") and s != "W":
                col = CHIP["W"]
            r = 26
            d.ellipse((x, y + 136, x + 2 * r, y + 136 + 2 * r), fill=col)
            d.text((x + r, y + 136 + r), s, font=_ff(s, 24 if len(s) < 3 else 18), fill=WHITE, anchor="mm")
            x += 2 * r + 12

    # win probability
    p = m.win_prob()
    by = H - 92
    d.text((40, by), "WIN PROBABILITY", font=_f(22, False), fill=DIM)
    bx0, bx1, bh = 40, W - 40, 26
    split = bx0 + (bx1 - bx0) * p
    d.rounded_rectangle((bx0, by + 34, bx1, by + 34 + bh), 13, fill=COL_B)
    if p > 0.01:
        d.rounded_rectangle((bx0, by + 34, max(bx0 + 26, split), by + 34 + bh), 13, fill=COL_A)
    d.text((bx0 + 12, by + 34 + bh / 2), f"{m.teams[0]['name'][:16].upper()}  {round(p * 100)}%",
           font=_f(20, False), fill=WHITE, anchor="lm")
    d.text((bx1 - 12, by + 34 + bh / 2), f"{round((1 - p) * 100)}%  {m.teams[1]['name'][:16].upper()}",
           font=_f(20, False), fill=WHITE, anchor="rm")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
