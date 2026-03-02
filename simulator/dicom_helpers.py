from __future__ import annotations

from io import BytesIO
from typing import Optional

import pydicom
from pydicom.tag import Tag

try:
    from simlib import dicom_utils
except ModuleNotFoundError:
    from .simlib import dicom_utils


def _parse_dicom_tag(tag_text: str, keyword_text: str) -> Optional[Tag]:
    return dicom_utils.parse_dicom_tag(tag_text, keyword_text)


def _value_for_vr(vr: str, raw_value: str):
    return dicom_utils.value_for_vr(vr, raw_value)


def _ensure_new_sop_instance_uid(ds: pydicom.dataset.Dataset) -> None:
    dicom_utils.ensure_new_sop_instance_uid(ds)


def _render_dicom_png(dicom_bytes: bytes) -> bytes:
    return dicom_utils.render_dicom_png(dicom_bytes)


def _dicom_tags_for_table(dicom_bytes: bytes) -> list:
    ds = pydicom.dcmread(BytesIO(dicom_bytes), force=True)
    rows = []

    for elem in ds.iterall():
        try:
            if elem.tag == (0x7FE0, 0x0010):
                continue  # PixelData
            tag_hex = f"({elem.tag.group:04X},{elem.tag.element:04X})"
            name = getattr(elem, 'name', '') or ''
            vr = getattr(elem, 'VR', '') or ''

            if vr == 'SQ':
                value = f"Sequence ({len(elem.value) if elem.value is not None else 0})"
            else:
                v = elem.value
                if isinstance(v, (bytes, bytearray, memoryview)):
                    value = f"<binary {len(v)} bytes>"
                else:
                    value = str(v)

            if len(value) > 240:
                value = value[:240] + "…"

            rows.append({
                'tag': tag_hex,
                'name': name,
                'vr': vr,
                'value': value,
            })
        except Exception:
            continue

    return rows
