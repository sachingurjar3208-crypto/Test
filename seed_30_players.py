"""Adds 30 players to the card database, built to match the Playing XI rules
in squad_logic.ROLE_LIMITS (WK 1-2, BAT 3-4, AR 2-3, BOWL 2-4, and at least
4 bowler-capable players).

Pool: 3 WK, 10 BAT, 7 AR, 10 BOWL = 30  -> several different legal XIs can be
picked from it. Bowling types are only the ones the match engine knows
(card_narratives.BOWLING_TYPES). Safe to re-run: existing names are skipped.

Run with:  python3 seed_30_players.py
"""
import card_db
import card_countries
import squad_logic as sl
from card_narratives import BOWLING_TYPES

SEED_USER_ID = 999999999

# name, role, bat, bowl, bowling_type, country, batting_hand
PLAYERS = [
    # ── Wicketkeepers (3) ──
    ("Arjun Keeper",     "WK",   84, 10, None,           "India",        "R"),
    ("Liam Gloves",      "WK",   80, 8,  None,           "Australia",    "L"),
    ("Dewald Stumps",    "WK",   76, 6,  None,           "South Africa", "R"),
    # ── Batters (10) ──
    ("Rohan Opener",     "BAT",  90, 18, None,           "India",        "R"),
    ("Jake Striker",     "BAT",  88, 15, None,           "England",      "R"),
    ("Steve Anchor",     "BAT",  86, 12, None,           "Australia",    "R"),
    ("Babar Classic",    "BAT",  85, 14, None,           "Pakistan",     "R"),
    ("Kane Timer",       "BAT",  83, 20, None,           "New Zealand",  "L"),
    ("Dilshan Flick",    "BAT",  80, 16, None,           "Sri Lanka",    "L"),
    ("Quinn Finisher",   "BAT",  78, 10, None,           "West Indies",  "R"),
    ("Tamim Pull",       "BAT",  74, 12, None,           "Bangladesh",   "L"),
    ("Harry Drive",      "BAT",  71, 10, None,           "England",      "R"),
    ("Aman Gully",       "BAT",  66, 8,  None,           "India",        "R"),
    # ── All-rounders (7) ──
    ("Hardik Power",     "AR",   80, 78, "Fast",         "India",        "R"),
    ("Ben Swing",        "AR",   78, 80, "Medium Pacer", "England",      "L"),
    ("Mitch Hustle",     "AR",   76, 77, "Medium Pacer", "Australia",    "R"),
    ("Shadab Twirl",     "AR",   72, 76, "Leg Spin",     "Pakistan",     "R"),
    ("Ravi Spinner",     "AR",   73, 75, "Orthodox",     "India",        "L"),
    ("Wanindu Wrist",    "AR",   68, 72, "Leg Spin",     "Sri Lanka",    "R"),
    ("Jason Island",     "AR",   65, 66, "Off Spin",     "West Indies",  "R"),
    # ── Bowlers (10) ──
    ("Jasprit Yorker",   "BOWL", 20, 90, "Fast",         "India",        "R"),
    ("Pat Thunder",      "BOWL", 18, 88, "Fast",         "Australia",    "R"),
    ("Kagiso Bounce",    "BOWL", 15, 87, "Fast",         "South Africa", "R"),
    ("Trent Seamer",     "BOWL", 22, 84, "Medium Pacer", "New Zealand",  "R"),
    ("Shaheen Arc",      "BOWL", 12, 83, "Fast",         "Pakistan",     "L"),
    ("Rashid Googly",    "BOWL", 25, 85, "Leg Spin",     "Pakistan",     "R"),
    ("Muttiah Doosra",   "BOWL", 10, 82, "Off Spin",     "Sri Lanka",    "R"),
    ("Axar Straight",    "BOWL", 24, 79, "Orthodox",     "India",        "L"),
    ("Mustafizur Cutter","BOWL", 8,  76, "Medium Pacer", "Bangladesh",   "L"),
    ("Sunil Mystery",    "BOWL", 12, 70, "Off Spin",     "West Indies",  "R"),
]

assert len(PLAYERS) == 30


def main():
    card_db.init_card_db()
    created = skipped = 0
    for name, role, bat, bowl, btype, country, hand in PLAYERS:
        assert btype is None or btype in BOWLING_TYPES, (name, btype)
        if card_db.card_exists(name):
            skipped += 1
            print(f"  (already exists) {name}")
            continue
        resolved = card_countries.resolve_country(country)
        c_name, c_emoji = resolved if resolved else (country, "🏳️")
        # same OVR idea as the other seed scripts, weighted to the role's main skill
        if role in ("BAT", "WK"):
            ovr = bat
        elif role == "BOWL":
            ovr = bowl
        else:
            ovr = round((bat + bowl) / 2) + 2
        card_db.create_card(
            playername=name,
            displayname=name.split()[-1],
            foreground_link="https://example.com/placeholder.png",
            background="default",
            ovr=ovr, bat=bat, bowl=bowl,
            country=c_name, country_emoji=c_emoji,
            created_by=SEED_USER_ID,
            role=role, batting_hand=hand, bowling_type=btype,
        )
        created += 1
        print(f"  created {name} ({role}, ovr {ovr})")
    print(f"\nDone: {created} created, {skipped} skipped.")

    # Sanity check: the best auto-XI from this pool must satisfy the rules.
    pool = [card_db.get_card(n.strip().lower()) for n, *_ in PLAYERS]
    xi = sl.best_xi(pool)
    counts = sl.xi_role_counts(xi)
    bowlers = sum(1 for c in xi if card_db.effective_bowling_type(c))
    ok = all((lo <= counts[r] <= hi) for r, (lo, hi) in sl.ROLE_LIMITS.items()) \
        and bowlers >= sl.MIN_BOWLERS and len(xi) == 11
    print(f"Auto-XI from the 30: {counts}, bowler-capable={bowlers} -> "
          f"{'LEGAL' if ok else 'NOT LEGAL'}")


if __name__ == "__main__":
    main()
