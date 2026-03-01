from __future__ import annotations

import re
from io import BytesIO
from typing import Optional

import pydicom
from pydicom.datadict import dictionary_VR, tag_for_keyword
from pydicom.tag import Tag
from pydicom.uid import generate_uid

_DICOM_TAG_RE = re.compile(r"\(?\s*([0-9a-fA-F]{4})\s*,\s*([0-9a-fA-F]{4})\s*\)?")
_DICOM_TAG_HEX8_RE = re.compile(r"^\s*([0-9a-fA-F]{8})\s*$")


def parse_dicom_tag(tag_text: str, keyword_text: str) -> Optional[Tag]:
    tag_text = (tag_text or '').strip()
    keyword_text = (keyword_text or '').strip()

    if keyword_text and not tag_text:
        t = tag_for_keyword(keyword_text)
        if t is None:
            return None
        return Tag(t)

    if not tag_text:
        return None

    m = _DICOM_TAG_RE.search(tag_text)
    if m:
        return Tag(int(m.group(1), 16), int(m.group(2), 16))

    m2 = _DICOM_TAG_HEX8_RE.match(tag_text)
    if m2:
        raw = m2.group(1)
        return Tag(int(raw[:4], 16), int(raw[4:], 16))

    return None


def vr_for_tag(tag: Tag) -> str:
    try:
        return dictionary_VR(tag) or ''
    except Exception:
        return ''


def value_for_vr(vr: str, raw_value: str):
    """Best-effort conversion: supports multi-value with backslash separators."""
    vr = (vr or '').strip().upper()
    raw_value = '' if raw_value is None else str(raw_value)

    if vr == 'SQ':
        raise ValueError('SQ (Sequence) wird im Editor nicht unterstützt.')

    if '\\' in raw_value:
        parts = [p for p in raw_value.split('\\')]
        return parts
    return raw_value


def ensure_new_sop_instance_uid(ds: pydicom.dataset.Dataset) -> None:
    """Avoid Orthanc duplicate-instance behavior by generating a new SOPInstanceUID."""
    new_uid = generate_uid()
    try:
        ds.SOPInstanceUID = new_uid
    except Exception:
        pass

    try:
        if getattr(ds, 'file_meta', None) is not None:
            if hasattr(ds.file_meta, 'MediaStorageSOPInstanceUID'):
                ds.file_meta.MediaStorageSOPInstanceUID = new_uid
    except Exception:
        pass


def render_dicom_png(dicom_bytes: bytes) -> bytes:
    """Best-effort PNG renderer for teaching demos."""
    import numpy as np
    from PIL import Image

    ds = pydicom.dcmread(BytesIO(dicom_bytes), force=True)
    arr = ds.pixel_array

    if arr is None:
        raise ValueError('Keine Pixel-Daten')

    # Multi-frame: take first frame
    if hasattr(arr, 'ndim') and arr.ndim == 3 and arr.shape[0] not in (3, 4):
        arr = arr[0]

    # RGB/RGBA
    if hasattr(arr, 'ndim') and arr.ndim == 3 and arr.shape[-1] in (3, 4):
        img = Image.fromarray(arr.astype('uint8'))
    else:
        a = arr.astype('float32')
        amin = float(np.min(a))
        amax = float(np.max(a))
        if amax <= amin:
            amax = amin + 1.0
        norm = (a - amin) / (amax - amin)
        img8 = (norm * 255.0).clip(0, 255).astype('uint8')
        img = Image.fromarray(img8)

    out = BytesIO()
    img.save(out, format='PNG')
    return out.getvalue()
