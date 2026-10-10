"""Every database table, in one import.

Importing this package registers all models on Base.metadata, which is what
Alembic and the tests look at. A brand-new model file must be imported here,
otherwise its table is invisible to migrations.
"""
from models.assessment_model import ASSESSMENT_SECTIONS, AssessmentRating, ScoutingAssessment
from models.match_model import Match, MatchAppearance, VideoReference
from models.notebook_model import (
    CoachingNote,
    TrainingIdea,
    coaching_note_observations,
    training_idea_observations,
)
from models.observation_model import Observation, ObservationPlayer
from models.player_model import Player
from models.reference_model import Competition, Season, Team
from models.snapshot_model import Annotation, TacticalSnapshot
from models.statistic_model import STAT_FIELDS, PlayerStatistic

__all__ = [
    "ASSESSMENT_SECTIONS", "STAT_FIELDS",
    "Annotation", "AssessmentRating", "CoachingNote", "Competition", "Match", "MatchAppearance",
    "Observation", "ObservationPlayer", "Player", "PlayerStatistic", "ScoutingAssessment", "Season",
    "TacticalSnapshot", "Team", "TrainingIdea", "VideoReference",
    "coaching_note_observations", "training_idea_observations",
]
