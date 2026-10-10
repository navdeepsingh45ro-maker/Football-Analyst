"""Small helpers used by several services."""
from typing import TypeVar

from sqlalchemy.orm import Session

from errors import NotFound

T = TypeVar("T")


def get_or_404(db: Session, model: type[T], record_id: int, label: str) -> T:
    """Load one row by id, or raise NotFound with a readable message."""
    row = db.get(model, record_id)
    if row is None:
        raise NotFound(f"{label} {record_id} does not exist")
    return row


def like_pattern(search_text: str) -> str:
    """Turn what the user typed into a safe "contains" pattern for SQL LIKE.

    % and _ are wildcards in LIKE. Escaping them means a search for "50%" looks
    for those three characters instead of matching everything. Use together
    with `.like(pattern, escape="\\\\")`.
    """
    escaped = search_text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
