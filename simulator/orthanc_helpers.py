from __future__ import annotations

from typing import Optional

try:
    from simlib import orthanc_rest
except ModuleNotFoundError:
    from .simlib import orthanc_rest


def _orthanc_get_json(path: str, *, params: Optional[dict] = None):
    return orthanc_rest.orthanc_get_json(path, params=params)


def _orthanc_get_bytes(path: str, *, params: Optional[dict] = None) -> bytes:
    return orthanc_rest.orthanc_get_bytes(path, params=params)


def _orthanc_post_json(path: str, payload: dict):
    return orthanc_rest.orthanc_post_json(path, payload)


def _orthanc_post_dicom_instance(dicom_bytes: bytes) -> dict:
    return orthanc_rest.orthanc_post_dicom_instance(dicom_bytes)


def _study_visible_for_student(study_obj: dict, student_code: str) -> bool:
    if not student_code:
        return False
    prefix = f"{student_code}-"
    for section in ("PatientMainDicomTags", "MainDicomTags"):
        tags = study_obj.get(section) or {}
        pid = str(tags.get("PatientID") or "")
        if pid.startswith(prefix):
            return True
    return False
