"""Scouting assessments: adding them, and comparing your opinion over time."""
from sqlalchemy import select
from sqlalchemy.orm import Session

import vocabulary
from models import AssessmentRating, Player, ScoutingAssessment
from schemas.assessment_schema import AssessmentIn
from services.common import get_or_404


def _apply(db: Session, assessment: ScoutingAssessment, data: AssessmentIn) -> None:
    for field, value in data.model_dump(exclude={"ratings"}).items():
        setattr(assessment, field, value)
    # Replace the ratings. The old rows must be deleted BEFORE the new ones are
    # inserted, otherwise re-rating "passing" would briefly be a second "passing"
    # row and break the one-rating-per-attribute rule. Hence clear + flush first.
    if assessment.ratings:
        assessment.ratings.clear()
        db.flush()
    assessment.ratings = [AssessmentRating(**rating.model_dump()) for rating in data.ratings]


def create_assessment(db: Session, player_id: int, data: AssessmentIn) -> ScoutingAssessment:
    """Add a NEW dated assessment. Earlier assessments are never modified by this."""
    get_or_404(db, Player, player_id, "Player")
    assessment = ScoutingAssessment(player_id=player_id)
    db.add(assessment)
    _apply(db, assessment, data)
    db.commit()
    return assessment


def update_assessment(db: Session, assessment_id: int, data: AssessmentIn) -> ScoutingAssessment:
    """Correct an existing assessment (a typo, a wrong date). For a changed opinion, add a new one."""
    assessment = get_or_404(db, ScoutingAssessment, assessment_id, "Assessment")
    _apply(db, assessment, data)
    db.commit()
    return assessment


def list_assessments(db: Session, player_id: int) -> list[ScoutingAssessment]:
    """A player's assessments, newest first."""
    get_or_404(db, Player, player_id, "Player")
    return list(db.scalars(select(ScoutingAssessment).where(ScoutingAssessment.player_id == player_id)
                           .order_by(ScoutingAssessment.assessed_on.desc(), ScoutingAssessment.id.desc())))


def delete_assessment(db: Session, assessment_id: int) -> None:
    db.delete(get_or_404(db, ScoutingAssessment, assessment_id, "Assessment"))
    db.commit()


def rating_history(db: Session, player_id: int) -> dict:
    """Each rated attribute across all of a player's assessments, oldest first.

    `change` is simply latest minus first. It describes how YOUR opinion moved;
    it is not a measurement of how the player developed.
    """
    get_or_404(db, Player, player_id, "Player")
    assessments = list(db.scalars(select(ScoutingAssessment).where(ScoutingAssessment.player_id == player_id)
                                  .order_by(ScoutingAssessment.assessed_on, ScoutingAssessment.id)))
    trends = []
    for attribute, label in vocabulary.RATING_ATTRIBUTES.items():
        points = []
        for assessment in assessments:
            rating = next((r.rating for r in assessment.ratings if r.attribute == attribute), None)
            points.append({"assessment_id": assessment.id, "assessed_on": assessment.assessed_on, "rating": rating})
        known = [point["rating"] for point in points if point["rating"] is not None]
        trends.append({
            "attribute": attribute, "label": label, "points": points,
            "first_rating": known[0] if known else None,
            "latest_rating": known[-1] if known else None,
            "change": known[-1] - known[0] if len(known) >= 2 else None,
        })
    return {"assessment_count": len(assessments), "scale_note": vocabulary.RATING_SCALE_NOTE, "trends": trends}
