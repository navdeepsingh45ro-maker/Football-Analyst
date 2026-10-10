"""Errors the app raises on purpose, each with a message that is safe to show.

Services raise these instead of FastAPI's HTTPException, so the business logic
does not depend on the web framework. main.py turns them into JSON responses:

    NotFound  -> 404   the thing asked for does not exist
    Conflict  -> 409   it would clash with existing data (duplicate, still in use)
    Invalid   -> 422   the request itself is wrong
    Unavailable -> 503 an optional feature is not set up (e.g. no AI key)
"""


class AppError(Exception):
    status_code = 400

    def __init__(self, detail: str, **extra):
        super().__init__(detail)
        self.detail = detail
        # Extra structured facts for the frontend, e.g. what blocks a deletion.
        self.extra = extra


class NotFound(AppError):
    status_code = 404


class Conflict(AppError):
    status_code = 409


class Invalid(AppError):
    status_code = 422


class Unavailable(AppError):
    status_code = 503
