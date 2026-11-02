"""The ONE live match message and its buttons.

Phases (the same message is edited the whole match):
  toss   toss winner picks Bat / Bowl
  plan   start of every over: bowling side picks the bowler + field, batting side the intent
  ball   bowler picks line + length (3x3 grid), batter picks a shot, at the same time
  run    gap ball: batter picks "Take 1" or "Push for 2"
  done   result + final scoreboard

A side played by the bot (rcbot) chooses instantly. A human who does nothing for
IDLE_SECONDS gets an automatic choice, so a match never gets stuck.
"""
from __future__ import annotations

import asyncio
import io
import os

import discord
from discord import ui

import engine as E
import render as R

IDLE_SECONDS = int(os.getenv("IDLE_SECONDS", "60") or 60)
COLOR = 0xF0C660

ACTIVE: dict[int, "Match"] = {}        # channel id -> match
IN_MATCH: dict[int, "Match"] = {}      # user id -> match


class Match:
    def __init__(self, channel, team_a: dict, team_b: dict, user_a, user_b, overs: int):
        self.channel = channel
        self.m = E.MatchState(team_a, team_b, overs)
        self.users = [user_a, user_b]          # discord.Member or None (= the bot plays this side)
        self.message: discord.Message | None = None
        self.phase = "toss"
        self.toss_winner = self.m.rng.randrange(2)
        self.lines: list[str] = []
        self.zone = None
        self.shot = None
        self.plan = {"bowler": None, "field": "balanced", "intent": "rotate"}
        self.lock = asyncio.Lock()
        self.idle_task: asyncio.Task | None = None
        self.card_bytes: bytes | None = None
        self.new_card = False
        self.ended = False

    # ── helpers ───────────────────────────────────────────────────────────────
    def side_of(self, user_id: int) -> int | None:
        for i, u in enumerate(self.users):
            if u is not None and u.id == user_id:
                return i
        return None

    def human(self, side: int) -> bool:
        return self.users[side] is not None

    def name(self, side: int) -> str:
        return self.m.teams[side]["name"]

    def mention(self, side: int) -> str:
        u = self.users[side]
        return u.mention if u is not None else f"**{self.name(side)}** (bot)"

    # ── message building ─────────────────────────────────────────────────────
    def embed(self) -> discord.Embed:
        m = self.m
        e = discord.Embed(title=f"{self.name(0)}  vs  {self.name(1)}  ·  {m.overs} over{'s' if m.overs != 1 else ''}",
                          color=COLOR)
        if self.phase == "toss":
            e.description = (f"{self.mention(self.toss_winner)} won the toss. Bat or bowl first?\n"
                             + ("Dew expected later (night match): spinners get less help in the 2nd innings."
                                if m.night else "Day match: the pitch will turn more in the 2nd innings."))
        else:
            e.description = R.live_text(m, self.lines[-(5 if self.phase == 'done' else 3):])
        if self.card_bytes:
            e.set_image(url="attachment://over.png")
        e.set_footer(text=self.prompt())
        return e

    def prompt(self) -> str:
        m = self.m
        if self.phase == "plan":
            bw, bt = m.bowl_team, m.bat_team
            return (f"Over {m.cur.balls // 6 + 1}: {self.name(bw)} pick the bowler + field and press Start. "
                    f"{self.name(bt)} pick your intent.")
        if self.phase == "ball":
            bw = "ready" if self.zone else "choosing"
            bt = "ready" if self.shot else "choosing"
            return f"Bowler ({self.name(m.bowl_team)}): {bw}   |   Batter ({self.name(m.bat_team)}): {bt}"
        if self.phase == "run":
            return f"{self.name(m.bat_team)}: gap ball. Take the single or push for two?"
        if self.phase == "done":
            return m.result or "Match over"
        return "Toss"

    def view(self) -> ui.View:
        v = ui.View(timeout=1800)
        m = self.m
        if self.phase == "toss":
            v.add_item(_Btn(self, "Bat first", "toss_bat", discord.ButtonStyle.success, 0))
            v.add_item(_Btn(self, "Bowl first", "toss_bowl", discord.ButtonStyle.primary, 0))
        elif self.phase == "plan":
            bw_human, bt_human = self.human(m.bowl_team), self.human(m.bat_team)
            if bw_human:
                xi = m.xi(m.bowl_team)
                opts = []
                for i in m.allowed_bowlers():
                    p = xi[i]
                    st = m.cur.bowl.get(i)
                    done = st.overs_done if st else 0
                    kind = (p.get("bowl_type") or "part-time").title()
                    opts.append(discord.SelectOption(
                        label=f"{p['name']} · {p['bowl']}"[:100], value=str(i),
                        description=f"{kind} · overs {done}/{m.max_per_bowler}"[:100],
                        default=self.plan["bowler"] == i))
                v.add_item(_BowlerSelect(self, opts[:25]))
                for key, lbl in E.FIELDS.items():
                    style = discord.ButtonStyle.primary if self.plan["field"] == key else discord.ButtonStyle.secondary
                    v.add_item(_Btn(self, f"Field: {lbl}", f"field_{key}", style, 1))
            if bt_human:
                for key, lbl in E.INTENTS.items():
                    style = discord.ButtonStyle.success if self.plan["intent"] == key else discord.ButtonStyle.secondary
                    v.add_item(_Btn(self, f"Intent: {lbl}", f"intent_{key}", style, 2))
            label = "Start over" if bw_human else "Play over"
            v.add_item(_Btn(self, label, "start", discord.ButtonStyle.danger, 3,
                            disabled=bw_human and self.plan["bowler"] is None))
        elif self.phase == "ball":
            if self.human(m.bowl_team):
                for r, length in enumerate(E.LENGTHS):
                    for line in E.LINES:
                        z = (line, length)
                        v.add_item(_Btn(self, E.ZONE_LABEL[z], f"zone_{line}_{length}",
                                        discord.ButtonStyle.primary, r, disabled=self.zone is not None))
            if self.human(m.bat_team):
                for i, s in enumerate(E.SHOT_ORDER):
                    v.add_item(_Btn(self, E.SHOTS[s]["label"], f"shot_{s}", discord.ButtonStyle.success
                                    if s not in ("defend", "leave") else discord.ButtonStyle.secondary,
                                    3 + i // 4, disabled=self.shot is not None))
        elif self.phase == "run":
            v.add_item(_Btn(self, "Take 1", "run_1", discord.ButtonStyle.secondary, 0))
            v.add_item(_Btn(self, f"Push for 2 ({E.FIELDS[m.field]} field)", "run_2", discord.ButtonStyle.danger, 0))
        return v

    async def render(self, interaction: discord.Interaction | None = None) -> None:
        """Edit the live message (through the interaction when there is one)."""
        kw = {"embed": self.embed(), "view": None if self.phase == "done" else self.view()}
        if self.new_card and self.card_bytes:
            kw["attachments"] = [discord.File(io.BytesIO(self.card_bytes), filename="over.png")]
            self.new_card = False
        try:
            if interaction is not None and not interaction.response.is_done():
                await interaction.response.edit_message(**kw)
            elif self.message is not None:
                await self.message.edit(**kw)
        except discord.HTTPException as e:
            print(f"[match] edit failed: {e}")
        self._arm_idle()

    async def start(self) -> None:
        self.message = await self.channel.send(embed=self.embed(), view=self.view())
        for u in self.users:
            if u is not None:
                IN_MATCH[u.id] = self
        ACTIVE[self.channel.id] = self
        if not self.human(self.toss_winner):
            await self._toss(self.m.rng.random() < 0.5)
            await self.render()
        else:
            self._arm_idle()

    # ── idle / bot turns ──────────────────────────────────────────────────────
    def _arm_idle(self) -> None:
        if self.idle_task is not None:
            self.idle_task.cancel()
        if self.phase != "done":
            self.idle_task = asyncio.create_task(self._idle())

    async def _idle(self) -> None:
        try:
            await asyncio.sleep(IDLE_SECONDS)
        except asyncio.CancelledError:
            return
        async with self.lock:
            if self.ended:
                return
            self.lines.append("No answer in time, an automatic choice was made.")
            await self._auto_all()
        await self.render()

    async def _auto_all(self) -> None:
        """Fill every missing choice of the current phase automatically, then move on."""
        m = self.m
        if self.phase == "toss":
            await self._toss(True)
        elif self.phase == "plan":
            if self.plan["bowler"] is None or self.plan["bowler"] not in m.allowed_bowlers():
                self.plan["bowler"], self.plan["field"] = E.ai_plan(m, "bowl")
            await self._start_over()
        elif self.phase == "ball":
            if self.zone is None:
                self.zone = E.ai_zone(m)
            if self.shot is None:
                self.shot = E.ai_shot(m)
            await self._play_ball()
        elif self.phase == "run":
            await self._run(False)

    # ── phase actions ─────────────────────────────────────────────────────────
    async def _toss(self, bat: bool) -> None:
        first = self.toss_winner if bat else 1 - self.toss_winner
        self.m.start(first)
        self.lines.append(f"{self.name(self.toss_winner)} won the toss and chose to {'bat' if bat else 'bowl'} first.")
        await self._enter_plan()

    async def _enter_plan(self) -> None:
        m = self.m
        self.phase = "plan"
        self.plan = {"bowler": None, "field": m.field, "intent": m.intent}
        if not self.human(m.bowl_team):
            self.plan["bowler"], self.plan["field"] = E.ai_plan(m, "bowl")
        if not self.human(m.bat_team):
            self.plan["intent"] = E.ai_plan(m, "bat")
            if not self.human(m.bowl_team):
                await self._start_over()

    async def _start_over(self) -> None:
        m = self.m
        if not self.human(m.bat_team):
            self.plan["intent"] = E.ai_plan(m, "bat")
        err = m.set_plan(self.plan["bowler"], self.plan["field"], self.plan["intent"])
        if err:
            self.plan["bowler"], self.plan["field"] = E.ai_plan(m, "bowl")
            m.set_plan(self.plan["bowler"], self.plan["field"], self.plan["intent"])
        b = m.bowler_card()
        self.lines.append(f"Over {m.cur.balls // 6 + 1}: {b['name']} to bowl. Field {E.FIELDS[m.field]}, "
                          f"batting intent {E.INTENTS[m.intent]}.")
        await self._enter_ball()

    async def _enter_ball(self) -> None:
        m = self.m
        self.phase = "ball"
        self.zone = None if self.human(m.bowl_team) else E.ai_zone(m)
        self.shot = None if self.human(m.bat_team) else E.ai_shot(m)

    async def _play_ball(self) -> None:
        m = self.m
        inn_before, overs_before = len(m.inn), len(m.cur.overs)
        res = m.bowl_ball(self.zone, self.shot)
        zl = E.ZONE_LABEL[self.zone]
        shot = E.SHOTS[self.shot]["label"]
        self.lines.append(f"{res['ball']}  {zl} · {shot}  —  {res['text']}")
        if m.pending_run:
            if self.human(m.bat_team):
                self.phase = "run"
                return
            r = m.resolve_run(E.ai_push(m))
            self.lines.append(r["text"])
        await self._after(inn_before, overs_before)

    async def _run(self, push: bool) -> None:
        m = self.m
        inn_before, overs_before = len(m.inn), len(m.cur.overs)
        r = m.resolve_run(push)
        self.lines.append(r["text"])
        await self._after(inn_before, overs_before)

    async def _after(self, inn_before: int, overs_before: int) -> None:
        m = self.m
        over_done = len(m.inn) != inn_before or len(m.inn[inn_before - 1].overs) != overs_before
        if over_done:
            idx = inn_before - 1
            self.card_bytes = await asyncio.to_thread(R.over_card, m, idx)
            self.new_card = True
        if m.result:
            self.phase = "done"
            for inn in m.inn:
                self.lines.append(f"{self.name(inn.bat_team)}: {inn.runs}/{inn.wkts} ({inn.balls // 6}.{inn.balls % 6} ov)")
            self.lines.append(f"RESULT: {m.result}.")
            await self.finish()
            return
        if len(m.inn) != inn_before:
            inn1 = m.inn[0]
            self.lines.append(f"Innings break. {self.name(inn1.bat_team)} made {inn1.runs}/{inn1.wkts}. "
                              f"Target {m.target}.")
        if m.need_plan:
            await self._enter_plan()
        else:
            await self._enter_ball()

    async def finish(self) -> None:
        self.ended = True
        self.phase = "done"
        if self.idle_task is not None and self.idle_task is not asyncio.current_task():
            self.idle_task.cancel()
        for u in self.users:
            if u is not None and IN_MATCH.get(u.id) is self:
                IN_MATCH.pop(u.id, None)
        if ACTIVE.get(self.channel.id) is self:
            ACTIVE.pop(self.channel.id, None)

    async def forfeit(self, side: int) -> None:
        async with self.lock:
            if self.ended:
                return
            other = 1 - side
            self.m.result = f"{self.name(other)} won ({self.name(side)} left the match)"
            self.m.winner = other
            self.lines.append(f"RESULT: {self.m.result}.")
            await self.finish()
        await self.render()

    # ── button handling ───────────────────────────────────────────────────────
    async def handle(self, interaction: discord.Interaction, action: str, value: str | None = None) -> None:
        async with self.lock:
            if self.ended:
                await interaction.response.send_message("This match is over.", ephemeral=True)
                return
            side = self.side_of(interaction.user.id)
            m = self.m
            if side is None:
                await interaction.response.send_message("You are not playing this match.", ephemeral=True)
                return
            deny = None
            if action.startswith("toss"):
                if side != self.toss_winner or self.phase != "toss":
                    deny = "Only the toss winner can choose."
                else:
                    await self._toss(action == "toss_bat")
            elif self.phase == "plan" and (action.startswith("field") or action == "bowler"):
                if side != m.bowl_team:
                    deny = "Only the bowling side sets the bowler and field."
                elif action == "bowler":
                    self.plan["bowler"] = int(value)
                else:
                    self.plan["field"] = action.split("_", 1)[1]
            elif self.phase == "plan" and action.startswith("intent"):
                if side != m.bat_team:
                    deny = "Only the batting side sets the intent."
                else:
                    self.plan["intent"] = action.split("_", 1)[1]
            elif self.phase == "plan" and action == "start":
                starter = m.bowl_team if self.human(m.bowl_team) else m.bat_team
                if side != starter:
                    deny = "The other side starts the over."
                elif self.plan["bowler"] is None:
                    deny = "Pick a bowler first."
                else:
                    await self._start_over()
            elif self.phase == "ball" and action.startswith("zone"):
                if side != m.bowl_team:
                    deny = "You are batting: pick a shot."
                elif self.zone is None:
                    _, line, length = action.split("_")
                    self.zone = (line, length)
            elif self.phase == "ball" and action.startswith("shot"):
                if side != m.bat_team:
                    deny = "You are bowling: pick where to bowl."
                elif self.shot is None:
                    self.shot = action.split("_", 1)[1]
            elif self.phase == "run" and action.startswith("run"):
                if side != m.bat_team:
                    deny = "The batting side decides the run."
                else:
                    await self._run(action == "run_2")
            else:
                deny = "That button is from an older step."
            if deny:
                await interaction.response.send_message(deny, ephemeral=True)
                return
            if self.phase == "ball" and self.zone is not None and self.shot is not None:
                await self._play_ball()
            await self.render(interaction)


class _Btn(ui.Button):
    def __init__(self, match: Match, label: str, action: str, style, row: int, disabled: bool = False):
        super().__init__(label=label[:80], style=style, row=row, disabled=disabled,
                         custom_id=f"m{id(match)}_{action}")
        self.match, self.action = match, action

    async def callback(self, interaction: discord.Interaction):
        await self.match.handle(interaction, self.action)


class _BowlerSelect(ui.Select):
    def __init__(self, match: Match, options):
        super().__init__(placeholder="Pick the bowler for this over", options=options, row=0,
                         custom_id=f"m{id(match)}_bowler")
        self.match = match

    async def callback(self, interaction: discord.Interaction):
        await self.match.handle(interaction, "bowler", self.values[0])
