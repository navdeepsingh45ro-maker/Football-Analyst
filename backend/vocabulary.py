"""The suggested lists the app offers: positions, observation categories, movement types, ...

IMPORTANT: most of these are SUGGESTIONS, not limits. You can type your own
category, movement or outcome and it is stored exactly as written. The lists
exist so that common entries are spelled the same way every time, which is what
makes counting them across matches meaningful.

The few lists that ARE enforced (a value outside them is rejected) say so below.
"""

# ── Players ──────────────────────────────────────────────────────────────────
POSITIONS = ["GK", "RB", "RWB", "CB", "LB", "LWB", "DM", "CM", "AM", "RM", "LM", "RW", "LW", "SS", "CF", "ST"]

# Used only to warn when a comparison mixes very different roles.
POSITION_GROUPS = {
    "GK": "Goalkeeper",
    "RB": "Defender", "RWB": "Defender", "CB": "Defender", "LB": "Defender", "LWB": "Defender",
    "DM": "Midfielder", "CM": "Midfielder", "AM": "Midfielder", "RM": "Midfielder", "LM": "Midfielder",
    "RW": "Forward", "LW": "Forward", "SS": "Forward", "CF": "Forward", "ST": "Forward",
}

PREFERRED_FEET = ["left", "right", "both"]  # enforced

# ── Scouting assessments ─────────────────────────────────────────────────────
# Enforced: ratings are structured data, so the attribute keys are fixed.
RATING_ATTRIBUTES = {
    "decision_making": "Decision-making",
    "off_ball_movement": "Movement off the ball",
    "spatial_awareness": "Awareness of space",
    "first_touch": "First touch",
    "passing": "Passing",
    "finishing": "Finishing",
    "dribbling": "Dribbling",
    "defensive_contribution": "Defensive contribution",
    "pressing": "Pressing behaviour",
}

RATING_MIN, RATING_MAX = 1, 5
RATING_SCALE = {
    1: "Clear weakness",
    2: "Below the level",
    3: "Adequate for the level",
    4: "A strength",
    5: "Outstanding",
}
RATING_SCALE_NOTE = (
    "Ratings are YOUR subjective judgement on a 1-5 scale, relative to the level you watched the "
    "player at. They are opinions recorded on a date, not measurements."
)

# ── Observations ─────────────────────────────────────────────────────────────
OBSERVATION_CATEGORIES = [
    "Off-ball movement", "Positioning", "Space exploitation", "Receiving orientation", "First touch",
    "Passing decisions", "Finishing", "Pressing", "Defensive positioning", "Transition behaviour",
    "Chance creation", "Decision-making", "Other",
]

MOVEMENT_CATEGORIES = [
    "Diagonal run", "Run behind the defensive line", "Near-post movement", "Far-post movement",
    "Checking towards the ball", "Dropping between the lines", "Channel run", "Curved run",
    "Pressing movement", "Recovery run", "Rotation with a teammate",
]

OUTCOMES = [
    "Received the ball", "Not found by the pass", "Created space for a teammate", "Shot", "Goal",
    "Chance created", "Retained possession", "Lost possession", "Won the ball", "Foul won", "Offside",
    "No direct outcome", "Other",
]

# Outcomes that count as "ended in a shot or chance" in the pattern reports.
SHOT_OR_CHANCE_OUTCOMES = ["Shot", "Goal", "Chance created"]

CONFIDENCE_LEVELS = ["low", "medium", "high"]  # enforced
PLAYER_ROLES = ["primary", "involved"]  # enforced: how a player relates to an observation

# ── Tactical diagrams ────────────────────────────────────────────────────────
ZONE_TYPES = [
    "Space behind the defensive line", "Space between defenders", "Half-space", "Central channel",
    "Wide channel", "Space between midfield and defence", "Passing lane", "Potential receiving zone", "Other",
]

ANNOTATION_LAYERS = ["frame", "pitch"]  # enforced

# Enforced: kind -> (fewest points, most points) that define the shape.
ANNOTATION_KINDS = {
    "subject": (1, 1),      # the player being studied
    "attacker": (1, 1),     # attacking player / teammate
    "defender": (1, 1),     # defending player / opponent
    "goalkeeper": (1, 1),
    "ball": (1, 1),
    "movement": (2, 3),     # run: start, end, optional bend point for a curved run
    "pass": (2, 2),         # passing direction: from, to
    "line": (2, 2),         # plain straight line
    "zone": (2, 2),         # highlighted rectangle: two opposite corners
    "angle": (3, 3),        # first point, corner (vertex), third point
    "text": (1, 1),
}

# ── Pitch ────────────────────────────────────────────────────────────────────
# Metres. 105 x 68 is the size UEFA and FIFA recommend for top-level matches;
# real pitches vary, which is one reason every distance in the app is an estimate.
PITCH_LENGTH_M = 105.0
PITCH_WIDTH_M = 68.0
# How far outside the touchlines a marker may sit (a player off the pitch, a throw-in).
PITCH_MARGIN_M = 5.0

# ── Videos ───────────────────────────────────────────────────────────────────
VIDEO_KINDS = ["local_file", "direct_url", "youtube", "external_link"]  # enforced

# ── Coaching notebook ────────────────────────────────────────────────────────
NOTE_TYPES = [
    "Tactical concept", "Lesson from a match", "Coaching principle", "Question for future analysis",
    "Player comparison", "Striker movement principle", "Finishing observation", "Positioning exercise",
    "Match reflection", "Development goal", "Other",
]
NOTE_STATUSES = ["open", "done"]  # enforced; only meaningful for questions and goals


def canonical(value: str | None, suggestions: list[str]) -> str | None:
    """Tidy a free-text choice so the same thing is always stored the same way.

    Trims and collapses spaces, and if the text matches a suggestion apart from
    upper/lower case it becomes the suggestion's spelling:

        canonical("  diagonal   run ", MOVEMENT_CATEGORIES) -> "Diagonal run"
        canonical("Blindside run", MOVEMENT_CATEGORIES)     -> "Blindside run"  (custom, kept)
        canonical("   ", ...)                               -> None
    """
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    if not cleaned:
        return None
    for suggestion in suggestions:
        if suggestion.casefold() == cleaned.casefold():
            return suggestion
    return cleaned
