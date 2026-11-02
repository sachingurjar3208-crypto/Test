"""Rush Cricket - MATCH SYSTEM TEST BOT (only the new match system).

Setup: copy .env.example to .env, put your bot token in it, then
    pip install -r requirements.txt
    python bot.py

Commands (prefix from .env, default none, like the main bot):
    rcstart [team name]   get your 11 players (same XI rules as rcstarterpack)
    rcxi [@user]          see a team
    rcmp @user [overs]    challenge a player (1-20 overs, default 5)
    rcbot [overs]         play against the bot
    rcquit                leave your match (the other side wins)
    rchelp                how the new match works
"""
from __future__ import annotations

import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

import players as P
import ui as U

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
PREFIX = os.getenv("PREFIX", "")
MAX_OVERS = max(1, min(20, int(os.getenv("MAX_OVERS", "20") or 20)))
DEFAULT_OVERS = max(1, min(MAX_OVERS, int(os.getenv("DEFAULT_OVERS", "5") or 5)))
ROLE_NAME = {"BAT": "Batter", "WK": "Keeper", "AR": "All-rounder", "BOWL": "Bowler"}

intents = discord.Intents.default()
intents.message_content = True
intents.members = False
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None, case_insensitive=True)


def team_text(team: dict) -> str:
    rows = [f"{'#':>2}  {'PLAYER':<20}{'ROLE':<12}{'BAT':>4}{'BOWL':>5}  TYPE"]
    for i, p in enumerate(team["xi"], 1):
        t = (p["bowl_type"] or "-").title()
        rows.append(f"{i:>2}  {p['name'][:19]:<20}{ROLE_NAME[p['role']]:<12}{p['bat']:>4}{p['bowl']:>5}  {t}")
    return "```\n" + "\n".join(rows) + "\n```"


def _overs(n) -> int:
    try:
        return max(1, min(MAX_OVERS, int(n)))
    except (TypeError, ValueError):
        return DEFAULT_OVERS


@bot.event
async def on_ready():
    print(f"Match test bot ready: {bot.user}  (prefix '{PREFIX}')")


@bot.command(name="rcstart")
async def rcstart(ctx: commands.Context, *, team_name: str = ""):
    if ctx.author.id in U.IN_MATCH:
        await ctx.send("Finish your match first.")
        return
    name = (team_name.strip() or f"{ctx.author.display_name} XI")[:24]
    team = P.create_team(ctx.author.id, name)
    await ctx.send(f"**{team['name']}** is ready. Your 11 players:\n{team_text(team)}"
                   f"Play: `{PREFIX}rcbot` (vs bot) or `{PREFIX}rcmp @user`. Type `{PREFIX}rcstart` again for a new random XI.")


@bot.command(name="rcxi")
async def rcxi(ctx: commands.Context, member: discord.Member | None = None):
    who = member or ctx.author
    team = P.get_team(who.id)
    if not team:
        await ctx.send(f"{who.display_name} has no team yet. Type `{PREFIX}rcstart`.")
        return
    await ctx.send(f"**{team['name']}**\n{team_text(team)}")


async def _can_play(ctx, user) -> str | None:
    if user.id in U.IN_MATCH:
        return f"{user.display_name} is already in a match."
    if not P.get_team(user.id):
        return f"{user.display_name} has no team yet. Type `{PREFIX}rcstart` first."
    return None


@bot.command(name="rcbot")
async def rcbot(ctx: commands.Context, overs: str = ""):
    if ctx.channel.id in U.ACTIVE:
        await ctx.send("A match is already running in this channel.")
        return
    err = await _can_play(ctx, ctx.author)
    if err:
        await ctx.send(err)
        return
    match = U.Match(ctx.channel, P.get_team(ctx.author.id), P.bot_team(), ctx.author, None, _overs(overs or DEFAULT_OVERS))
    await match.start()


class Challenge(discord.ui.View):
    def __init__(self, ctx, target, overs):
        super().__init__(timeout=45)
        self.ctx, self.target, self.overs = ctx, target, overs
        self.message = None

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("This challenge is not for you.", ephemeral=True)
            return
        for u in (self.ctx.author, self.target):
            err = await _can_play(self.ctx, u)
            if err:
                await interaction.response.edit_message(content=err, view=None)
                return
        if self.ctx.channel.id in U.ACTIVE:
            await interaction.response.edit_message(content="A match is already running in this channel.", view=None)
            return
        self.stop()
        await interaction.response.edit_message(content=f"Challenge accepted. {self.overs} overs a side.", view=None)
        match = U.Match(self.ctx.channel, P.get_team(self.ctx.author.id), P.get_team(self.target.id),
                        self.ctx.author, self.target, self.overs)
        await match.start()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button):
        if interaction.user.id not in (self.target.id, self.ctx.author.id):
            await interaction.response.send_message("This challenge is not for you.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(content="Challenge declined.", view=None)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="Challenge expired.", view=None)
            except discord.HTTPException:
                pass


@bot.command(name="rcmp")
async def rcmp(ctx: commands.Context, member: discord.Member, overs: str = ""):
    if member.bot or member.id == ctx.author.id:
        await ctx.send("Challenge another real player.")
        return
    for u in (ctx.author, member):
        err = await _can_play(ctx, u)
        if err:
            await ctx.send(err)
            return
    n = _overs(overs or DEFAULT_OVERS)
    view = Challenge(ctx, member, n)
    view.message = await ctx.send(f"{member.mention}, **{ctx.author.display_name}** challenges you to a {n}-over match.",
                                  view=view)


@bot.command(name="rcquit")
async def rcquit(ctx: commands.Context):
    match = U.IN_MATCH.get(ctx.author.id)
    if not match:
        await ctx.send("You are not in a match.")
        return
    await match.forfeit(match.side_of(ctx.author.id))
    await ctx.send("You left the match.")


HELP = """**NEW MATCH SYSTEM (test)**
```
EVERY OVER
  Bowling side  pick the bowler + field (Attacking / Balanced / Defensive)
  Batting side  pick the intent (Defend / Rotate / Attack)

EVERY BALL (both choose at the same time, nobody sees the other)
  Bowler  where the ball lands: line Off/Middle/Leg x length Full/Good/Short
  Batter  a shot: Drive Cut Pull Flick Sweep Loft Defend Leave
          each shot is good for some zones, bad for others. Guess right = good contact

THINGS THAT CHANGE THE BALL
  New batter is weak for the first balls, a SET batter times it better
  New ball swings (pace, first 4 overs), old ball reverses at the death
  Spin turns more in the 2nd innings, dew at night helps the batting side
  Setup: two balls on one line, then change the line = more wicket chance
  Pressure: dot balls in a row and a high required rate cause mistakes
  Bowlers get tired, nobody bowls two overs in a row
  Gap ball: Take 1 or Push for 2 (run out risk)
```
One live message for the whole match, a TV scoreboard after every over, win probability bar.
Do nothing for a while and the bot plays that choice for you."""


@bot.command(name="rchelp")
async def rchelp(ctx: commands.Context):
    await ctx.send(HELP)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, (commands.CommandNotFound,)):
        return
    if isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument, commands.MemberNotFound)):
        await ctx.send(f"Usage: `{PREFIX}rcmp @user [overs]`, `{PREFIX}rcbot [overs]`, `{PREFIX}rchelp`")
        return
    print(f"[error] {type(error).__name__}: {error}")


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Put your bot token in .env (DISCORD_TOKEN=...). See .env.example")
    bot.run(TOKEN)
