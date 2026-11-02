RUSH CRICKET - NAYA MATCH SYSTEM (TEST BOT)
===========================================

Ye ek ALAG chhota bot hai, sirf naye match system ko test karne ke liye.
Main bot (Ss-main) ko ye bilkul nahi chhoota. Apna data data/teams.json mein rakhta hai.

SETUP (VPS ya apne PC par)
  1. Discord Developer Portal par ek NAYA bot banao (test ke liye), token copy karo.
     Bot page par "Message Content Intent" ON karo.
  2. Is folder mein:  cp .env.example .env   aur .env mein DISCORD_TOKEN= ke aage token daalo.
     Agar same server mein main bot bhi hai to PREFIX=! rakho (warna dono rcmp sunenge).
  3. pip install -r requirements.txt
  4. python bot.py
  5. Bot ko apne test server mein invite karo (scopes: bot, permissions: Send Messages,
     Embed Links, Attach Files, Read Message History).

COMMANDS
  rcstart [naam]     11 players milte hain (WK 1, BAT 5, AR 2, BOWL 3 - rcstarterpack jaise)
  rcxi [@user]       team dekho
  rcbot [overs]      bot ke khilaf match
  rcmp @user [overs] doosre player ke saath match
  rcquit             match chhodo
  rchelp             naya match kaise khelte hain

FILES
  bot.py      commands + .env
  ui.py       ek hi live message, buttons, phases (toss / over plan / ball / run)
  engine.py   match ka saara logic (ball ka result, AI, win probability)
  render.py   live scoreboard text + over ke baad TV jaisi scoreboard image
  players.py  players ki list + starter XI + data/teams.json
  fonts/      image ke fonts
