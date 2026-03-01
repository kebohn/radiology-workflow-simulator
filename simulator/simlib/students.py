from __future__ import annotations

from typing import Optional

from flask import session

from .util import normalize_student_code
from . import storage


def get_student_code() -> str:
    return normalize_student_code(session.get('student_code'))


def prefix_for_student(value: Optional[str]) -> str:
    value = (value or '').strip()
    code = get_student_code()
    if not value:
        return value
    if not code:
        return value
    prefix = f"{code}-"
    if value.startswith(prefix):
        return value
    return f"{code}-{value}"


def student_code_allowed(code: str) -> bool:
    """If sessions.json contains codes, only allow those; otherwise allow all."""
    code = normalize_student_code(code)
    if not code:
        return False
    allowed = storage.load_session_codes()
    if not allowed:
        return True
    return code in allowed
