from __future__ import annotations

from typing import Optional

import requests

from .config import ORTHANC_HTTP_URL


def orthanc_get_json(path: str, *, params: Optional[dict] = None):
    url = f"{ORTHANC_HTTP_URL}{path}"
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def orthanc_get_bytes(path: str, *, params: Optional[dict] = None) -> bytes:
    url = f"{ORTHANC_HTTP_URL}{path}"
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.content


def orthanc_post_json(path: str, payload: dict):
    url = f"{ORTHANC_HTTP_URL}{path}"
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()
    return r.json()


def orthanc_post_dicom_instance(dicom_bytes: bytes) -> dict:
    """Upload a DICOM file to Orthanc via REST API and return Orthanc's JSON response."""
    url = f"{ORTHANC_HTTP_URL}/instances"
    r = requests.post(
        url,
        data=dicom_bytes,
        headers={"Content-Type": "application/dicom"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
