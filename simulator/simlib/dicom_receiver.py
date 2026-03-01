from __future__ import annotations

import datetime
import threading
from typing import Any

from pynetdicom import AE, evt
from pynetdicom.sop_class import (
    CTImageStorage,
    MRImageStorage,
    SecondaryCaptureImageStorage,
    Verification,
)

from .config import STORE_SCP_PORT

RECEIVED_IMAGES: list[dict[str, Any]] = []


def handle_store(event):
    ds = event.dataset
    ds.file_meta = event.file_meta

    patient_name = str(ds.PatientName) if 'PatientName' in ds else 'Unknown'
    patient_id = str(ds.PatientID) if 'PatientID' in ds else ''

    RECEIVED_IMAGES.append(
        {
            'PatientName': patient_name,
            'PatientID': patient_id,
            'StudyInstanceUID': str(ds.StudyInstanceUID) if 'StudyInstanceUID' in ds else 'Unknown',
            'Modality': str(ds.Modality) if 'Modality' in ds else 'OT',
            'Timestamp': datetime.datetime.now().strftime('%H:%M:%S'),
        }
    )

    return 0x0000


def start_store_scp():
    ae = AE(ae_title=b'SIMULATOR')
    ae.add_supported_context(CTImageStorage)
    ae.add_supported_context(MRImageStorage)
    ae.add_supported_context(SecondaryCaptureImageStorage)
    ae.add_supported_context(Verification)

    print(f"Starting DICOM Store SCP on port {STORE_SCP_PORT}...")
    ae.start_server(('', STORE_SCP_PORT), evt_handlers=[(evt.EVT_C_STORE, handle_store)])


_scp_thread_started = False


def ensure_store_scp_thread_started():
    global _scp_thread_started
    if _scp_thread_started:
        return
    scp_thread = threading.Thread(target=start_store_scp, daemon=True)
    scp_thread.start()
    _scp_thread_started = True


def received_images_for_code(code: str) -> list[dict]:
    code = (code or '').strip()
    if code:
        return [
            r
            for r in RECEIVED_IMAGES
            if str((r or {}).get('PatientID', '')).startswith(code + '-')
        ]
    return list(RECEIVED_IMAGES)


def received_study_groups(received: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for img in received or []:
        row = img or {}
        uid = str(row.get('StudyInstanceUID') or 'Unknown').strip() or 'Unknown'
        g = groups.get(uid)
        if not g:
            g = {
                'StudyInstanceUID': uid,
                'PatientName': str(row.get('PatientName') or ''),
                'PatientID': str(row.get('PatientID') or ''),
                'Modalities': set(),
                'Count': 0,
                'LastTimestamp': str(row.get('Timestamp') or ''),
            }
            groups[uid] = g
        g['Count'] += 1
        mod = str(row.get('Modality') or '').strip()
        if mod:
            g['Modalities'].add(mod)
        ts = str(row.get('Timestamp') or '').strip()
        if ts:
            g['LastTimestamp'] = ts

    out = []
    for uid, g in groups.items():
        out.append(
            {
                'StudyInstanceUID': uid,
                'PatientName': g.get('PatientName', ''),
                'PatientID': g.get('PatientID', ''),
                'Modalities': ','.join(sorted(g.get('Modalities') or [])),
                'Count': g.get('Count', 0),
                'LastTimestamp': g.get('LastTimestamp', ''),
            }
        )
    out.sort(key=lambda x: (x.get('PatientName') or '', x.get('StudyInstanceUID') or ''))
    return out


def seed_demo_received_images() -> None:
    if RECEIVED_IMAGES:
        return
    RECEIVED_IMAGES.append(
        {
            'PatientName': 'TEST^DEMO',
            'PatientID': 'DEMO-0001',
            'StudyInstanceUID': '1.2.826.0.1.3680043.10.999.1',
            'Modality': 'CT',
            'Timestamp': '00:00:00',
        }
    )
