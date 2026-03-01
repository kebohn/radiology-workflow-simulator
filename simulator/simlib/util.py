from __future__ import annotations

from typing import Optional

from .config import SAFE_FILENAME_RE, STUDENT_CODE_RE


def normalize_student_code(raw: Optional[str]) -> str:
    if not raw:
        return ''
    code = str(raw).strip()
    code = STUDENT_CODE_RE.sub('', code)
    code = code[:24]
    return code


def safe_filename_component(value: str) -> str:
    """Return a filesystem-safe component (no slashes), suitable for filenames."""
    v = (value or '').strip()
    v = v.replace('/', '-').replace('\\', '-')
    v = SAFE_FILENAME_RE.sub('_', v)
    v = v[:64]
    return v or 'item'
