from flask import Flask, render_template, request, make_response, jsonify, session, redirect, url_for, abort
import os
import datetime
import tempfile
import zipfile
import shutil
import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import generate_uid
from pynetdicom import AE, debug_logger, sop_class, evt
import random
import threading
import hashlib
import re
import json
import secrets
import hmac
from typing import Optional
from io import BytesIO

import requests
import bcrypt

from pydicom.tag import Tag
from pydicom.datadict import tag_for_keyword, dictionary_VR

app = Flask(__name__)

# IMPORTANT (central server): Set a stable secret via env so sessions survive restarts.
app.secret_key = (os.environ.get('FLASK_SECRET_KEY') or 'dev-insecure-change-me')

# Real CT studies can be large. If you hit HTTP 413 (Request Entity Too Large),
# increase this value.
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1 GiB

# --- LIS Simulation ---

STUDENT_CODE_RE = re.compile(r"[^A-Za-z0-9_-]")
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_.-]")


def normalize_student_code(raw: Optional[str]) -> str:
    if not raw:
        return ""
    code = str(raw).strip()
    code = STUDENT_CODE_RE.sub("", code)
    code = code[:24]
    return code

DATA_DIR = os.environ.get('DATA_DIR', '/app/data')
SESSIONS_FILE = os.path.join(DATA_DIR, 'sessions.json')
_SESSIONS_LOCK = threading.Lock()


def _ensure_data_dir() -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        # If this fails, we still want the app to start; session codes just won't persist.
        pass


def _load_session_codes() -> list:
    _ensure_data_dir()
    with _SESSIONS_LOCK:
        try:
            if not os.path.exists(SESSIONS_FILE):
                return []
            with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            codes = payload.get('codes', []) if isinstance(payload, dict) else []
            if not isinstance(codes, list):
                return []
            cleaned = []
            seen = set()
            for c in codes:
                cc = normalize_student_code(str(c))
                if cc and cc not in seen:
                    seen.add(cc)
                    cleaned.append(cc)
            return cleaned
        except Exception:
            return []


def _save_session_codes(codes: list) -> None:
    _ensure_data_dir()
    cleaned = []
    seen = set()
    for c in codes or []:
        cc = normalize_student_code(str(c))
        if cc and cc not in seen:
            seen.add(cc)
            cleaned.append(cc)

    payload = {
        'generated_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'count': len(cleaned),
        'codes': cleaned,
    }

    with _SESSIONS_LOCK:
        try:
            tmp = SESSIONS_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp, SESSIONS_FILE)
        except Exception:
            pass


def _generate_session_codes(n: int) -> list:
    n = max(1, min(int(n or 20), 200))
    out = []
    seen = set()
    while len(out) < n:
        # Example: SUS-3FA9C1 (easy to read, hard to guess)
        suffix = secrets.token_hex(3).upper()
        code = normalize_student_code(f"SUS-{suffix}")
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _admin_user() -> str:
    return (os.environ.get('ADMIN_USER') or 'admin').strip() or 'admin'


def _admin_passhash() -> str:
    # Prefer dedicated admin passhash; fallback to Orthanc proxy hash so one secret can be used.
    return (
        (os.environ.get('ADMIN_PASSHASH') or '').strip()
        or (os.environ.get('ORTHANC_PROXY_PASSHASH') or '').strip()
    )


def _admin_password() -> str:
    # Legacy plaintext fallback; prefer _admin_passhash().
    return (os.environ.get('ADMIN_PASSWORD') or '').strip()


def _admin_enabled() -> bool:
    return bool(_admin_passhash() or _admin_password())


def _is_admin() -> bool:
    return bool(session.get('is_admin'))


def _require_admin():
    if not _admin_enabled():
        return render_template('admin.html', admin_enabled=False, is_admin=False, msg="Admin ist nicht aktiviert (ADMIN_PASSHASH fehlt).")
    if not _is_admin():
        return render_template('admin.html', admin_enabled=True, is_admin=False)
    return None


def _maybe_auto_generate_sessions() -> None:
    raw = (os.environ.get('AUTO_GENERATE_SESSIONS') or '').strip()
    if not raw:
        return
    try:
        n = int(raw)
    except Exception:
        n = 20
    if n <= 0:
        return
    existing = _load_session_codes()
    if existing:
        return
    codes = _generate_session_codes(n)
    _save_session_codes(codes)


_maybe_auto_generate_sessions()


def get_student_code() -> str:
    return normalize_student_code(session.get('student_code'))


def _student_code_allowed(code: str) -> bool:
    # If codes were generated (sessions.json exists and is non-empty), only allow those.
    allowed = _load_session_codes()
    if not allowed:
        return True
    return code in allowed


def prefix_for_student(value: Optional[str]) -> str:
    value = (value or "").strip()
    code = get_student_code()
    if not value:
        return value
    if not code:
        return value
    prefix = f"{code}-"
    if value.startswith(prefix):
        return value
    return f"{code}-{value}"


def safe_filename_component(value: str) -> str:
    """Return a filesystem-safe component (no slashes), suitable for filenames."""
    v = (value or "").strip()
    v = v.replace("/", "-").replace("\\", "-")
    v = SAFE_FILENAME_RE.sub("_", v)
    v = v[:64]
    return v or "item"


# --- Simple KIS patient registry (per SuS-code) ---

_PATIENTS_LOCK = threading.Lock()


_REPORTS_LOCK = threading.Lock()


def _patients_file_for_code(code: str) -> str:
    safe = safe_filename_component(code or "")
    if not safe or safe == "item":
        safe = "default"
    return os.path.join(DATA_DIR, f"patients_{safe}.json")


def _load_patients(code: str) -> list:
    _ensure_data_dir()
    path = _patients_file_for_code(code)
    with _PATIENTS_LOCK:
        try:
            if not os.path.exists(path):
                return []
            with open(path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            patients = payload.get('patients', []) if isinstance(payload, dict) else []
            return patients if isinstance(patients, list) else []
        except Exception:
            return []


def _save_patients(code: str, patients: list) -> None:
    _ensure_data_dir()
    path = _patients_file_for_code(code)
    payload = {
        'updated_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'count': len(patients or []),
        'patients': patients or [],
    }
    with _PATIENTS_LOCK:
        try:
            tmp = path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            pass


def _patient_exists(code: str, pid: str) -> bool:
    pid = (pid or '').strip()
    if not pid:
        return False
    for p in _load_patients(code):
        if str((p or {}).get('pid') or '') == pid:
            return True
    return False


def _upsert_patient(code: str, name: str, pid: str) -> None:
    name = (name or '').strip()
    pid = (pid or '').strip()
    if not name or not pid:
        return

    patients = _load_patients(code)
    now = datetime.datetime.now().isoformat(timespec='seconds')
    updated = False
    for p in patients:
        if str((p or {}).get('pid') or '') == pid:
            p['name'] = name
            p['updated_at'] = now
            updated = True
            break
    if not updated:
        patients.append({'pid': pid, 'name': name, 'created_at': now})

    patients = patients[-50:]
    _save_patients(code, patients)


def _hl7_timestamp() -> str:
    return datetime.datetime.now().strftime('%Y%m%d%H%M%S')


def _hl7_msg_control_id(prefix: str = 'MSG') -> str:
    return f"{prefix}{random.randint(100000, 999999)}"


def _hl7_sanitize_field(text: str) -> str:
    """Keep HL7 fields single-line and avoid separator characters.

    This is intentionally minimal for demo purposes.
    """
    s = '' if text is None else str(text)
    s = s.replace('\r', ' ').replace('\n', ' ').strip()
    # Avoid breaking HL7 field structure.
    s = s.replace('|', '/').replace('~', '-').replace('\\', '/')
    return s


def build_hl7_oru_report(*, pid: str, patient_name: str, study_uid: str, report_text: str) -> str:
    """Return a simple HL7 v2.x ORU^R01 message (Workstation -> RIS) representing a report."""
    ts = _hl7_timestamp()
    msg_id = _hl7_msg_control_id('ORU')
    pid = (pid or 'UNKNOWN').strip()
    patient_name = _hl7_sanitize_field(patient_name or '^') or '^'
    study_uid = _hl7_sanitize_field(study_uid or '')
    report_text = _hl7_sanitize_field(report_text or '')
    if not report_text:
        report_text = 'Kein Text.'

    return (
        f"MSH|^~\\&|WORKSTATION|RAD|RIS|RADIO|{ts}||ORU^R01|{msg_id}|P|2.3\r"
        f"PID|1||{pid}||{patient_name}\r"
        f"OBR|1|||RPT^Radiology Report\r"
        f"OBX|1|TX|RPT||{report_text}|||||F\r"
        f"OBX|2|ST|STUDYUID||{study_uid}|||||F"
    )


def _reports_file_for_code(code: str) -> str:
    safe = safe_filename_component(code or "")
    if not safe or safe == "item":
        safe = "default"
    return os.path.join(DATA_DIR, f"reports_{safe}.json")


def _load_reports(code: str) -> list:
    _ensure_data_dir()
    path = _reports_file_for_code(code)
    with _REPORTS_LOCK:
        try:
            if not os.path.exists(path):
                return []
            with open(path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            reports = payload.get('reports', []) if isinstance(payload, dict) else []
            return reports if isinstance(reports, list) else []
        except Exception:
            return []


def _save_reports(code: str, reports: list) -> None:
    _ensure_data_dir()
    path = _reports_file_for_code(code)
    payload = {
        'updated_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'count': len(reports or []),
        'reports': reports or [],
    }
    with _REPORTS_LOCK:
        try:
            tmp = path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            pass


def _reports_index_by_pid(code: str) -> dict:
    """Return a mapping pid -> {count, last_at} for quick RIS status display on dashboard."""
    out: dict[str, dict] = {}
    if not code:
        return out
    for r in _load_reports(code):
        rr = r or {}
        pid = str(rr.get('PatientID') or '').strip()
        if not pid:
            continue
        created_at = str(rr.get('created_at') or '').strip()
        cur = out.get(pid) or {'count': 0, 'last_at': ''}
        cur['count'] = int(cur.get('count') or 0) + 1
        if created_at and (not cur.get('last_at') or created_at > str(cur.get('last_at'))):
            cur['last_at'] = created_at
        out[pid] = cur
    return out


def build_hl7_adt_a04(pid: str, name: str) -> str:
    """Return a simple HL7 v2.x ADT^A04 registration message as raw segments."""
    ts = _hl7_timestamp()
    msg_id = _hl7_msg_control_id('ADT')
    pid = (pid or 'UNKNOWN').strip()
    name = (name or '').strip() or '^'
    return (
        f"MSH|^~\\&|KIS|HOSP|RIS|RADIO|{ts}||ADT^A04|{msg_id}|P|2.3\r"
        f"EVN|A04|{ts}\r"
        f"PID|1||{pid}||{name}\r"
        f"PV1|1|O\r"
    )


def build_hl7_qry_q02(pid: str) -> str:
    """Return a simple HL7 v2.x QRY^Q02 message (RIS->LIS lab query)."""
    ts = _hl7_timestamp()
    msg_id = _hl7_msg_control_id('QRY')
    pid = (pid or 'UNKNOWN').strip()
    return (
        f"MSH|^~\\&|RIS|RADIO|LIS|LAB|{ts}||QRY^Q02|{msg_id}|P|2.3\r"
        f"PID|1||{pid}||^\r"
        f"QRD|{ts}|R|I|{msg_id}|||1^RD|{pid}|RES\r"
        f"QRF|MON|||||RCT^Creatinine\r"
    )


def _viewer_moved_studies() -> set[str]:
    """Return StudyInstanceUIDs for which this session has triggered a C-MOVE."""
    raw = session.get('viewer_moved_studies')
    if not isinstance(raw, list):
        return set()
    out: set[str] = set()
    for x in raw:
        if isinstance(x, str) and x.strip():
            out.add(x.strip())
    return out


def _viewer_mark_study_moved(study_uid: str) -> None:
    uid = (study_uid or '').strip()
    if not uid:
        return
    moved = _viewer_moved_studies()
    moved.add(uid)
    # Keep the list bounded.
    session['viewer_moved_studies'] = list(sorted(moved))[-50:]
    session.modified = True


def _received_images_for_code(code: str) -> list[dict]:
    if code:
        return [
            r for r in RECEIVED_IMAGES
            if str((r or {}).get('PatientID', '')).startswith(code + "-")
        ]
    return list(RECEIVED_IMAGES)


def _received_study_groups(received: list[dict]) -> list[dict]:
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
        out.append({
            'StudyInstanceUID': uid,
            'PatientName': g.get('PatientName', ''),
            'PatientID': g.get('PatientID', ''),
            'Modalities': ','.join(sorted(g.get('Modalities') or [])),
            'Count': g.get('Count', 0),
            'LastTimestamp': g.get('LastTimestamp', ''),
        })
    out.sort(key=lambda x: (x.get('PatientName') or '', x.get('StudyInstanceUID') or ''))
    return out


@app.context_processor
def _inject_globals():
    orthanc_public_url = os.environ.get('ORTHANC_PUBLIC_URL', '').strip()
    orthanc_domain = (os.environ.get('ORTHANC_DOMAIN') or '').strip()

    # If Orthanc is exposed via reverse proxy, prefer HTTPS on its hostname.
    # Allow explicit ORTHANC_PUBLIC_URL to override.
    if not orthanc_public_url and orthanc_domain:
        d = orthanc_domain
        if d.startswith('http://'):
            d = d[len('http://'):]
        elif d.startswith('https://'):
            d = d[len('https://'):]
        d = d.strip().strip('/')
        if d:
            orthanc_public_url = f"https://{d}"

    # Convenience for local development: if the simulator is accessed via localhost,
    # show Orthanc links even when ORTHANC_PUBLIC_URL is not set.
    # On central servers (accessed via IP/domain), we keep this empty by default so
    # Orthanc is not accidentally linked publicly.
    if not orthanc_public_url:
        try:
            host = (request.host or '').split(':', 1)[0].lower()
        except Exception:
            host = ''
        if host in {'localhost', '127.0.0.1'}:
            orthanc_public_url = 'http://localhost:8042'

    is_admin = _is_admin()

    # Only show Orthanc link/buttons when admin is logged in.
    if not is_admin:
        orthanc_public_url = ''

    return {
        'student_code': get_student_code(),
        'orthanc_public_url': orthanc_public_url,
        'is_admin': is_admin,
        'admin_user': _admin_user(),
    }


@app.route('/welcome', methods=['GET'])
def welcome():
    code = get_student_code()
    if code:
        return redirect(url_for('index'))
    return render_template('welcome.html')


@app.before_request
def _require_student_code_gate():
    # Force an initial welcome page where SuS must enter a session key.
    # Allow admin and the entry points.
    allowed_endpoints = {
        'welcome',
        'set_student',
        'join',
        'admin_home',
        'admin_login',
        'admin_logout',
        'admin_generate_sessions',
        'static',
    }
    if request.endpoint in allowed_endpoints:
        return None
    if request.path.startswith('/admin'):
        return None
    if get_student_code():
        return None
    return redirect(url_for('welcome'))


@app.route('/set_student', methods=['POST'])
def set_student():
    code = normalize_student_code(request.form.get('student_code'))
    if not code:
        session.pop('student_code', None)
        return redirect(url_for('welcome'))
    if not _student_code_allowed(code):
        return render_template('welcome.html', msg="❌ Ungültiger SuS-Code. Bitte einen der vorgegebenen Codes verwenden.")
    session['student_code'] = code
    return redirect(url_for('index'))


@app.route('/clear_student', methods=['POST'])
def clear_student():
    session.pop('student_code', None)
    return redirect(url_for('index'))


@app.route('/join/<code>', methods=['GET'])
def join(code: str):
    cc = normalize_student_code(code)
    if not cc or not _student_code_allowed(cc):
        return render_template('welcome.html', msg="❌ Ungültiger oder nicht freigeschalteter SuS-Code.")
    session['student_code'] = cc
    return redirect(url_for('index'))


@app.route('/admin', methods=['GET'])
def admin_home():
    if not _admin_enabled():
        return render_template('admin.html', admin_enabled=False, is_admin=False, msg="Admin ist nicht aktiviert (ADMIN_PASSHASH fehlt).")
    if not _is_admin():
        return render_template('admin.html', admin_enabled=True, is_admin=False)
    codes = _load_session_codes()
    return render_template('admin.html', admin_enabled=True, is_admin=True, codes=codes)


@app.route('/admin/login', methods=['POST'])
def admin_login():
    if not _admin_enabled():
        return redirect(url_for('admin_home'))
    username = (request.form.get('username') or '').strip()
    provided = (request.form.get('password') or '').strip()

    expected_user = _admin_user()
    if not username or not hmac.compare_digest(username, expected_user):
        return render_template('admin.html', admin_enabled=True, is_admin=False, msg="❌ Falscher Benutzername oder Passwort.")

    expected_hash = _admin_passhash()
    if expected_hash:
        try:
            ok = bcrypt.checkpw(provided.encode('utf-8'), expected_hash.encode('utf-8'))
        except Exception:
            ok = False
        if ok:
            session['is_admin'] = True
            return redirect(url_for('admin_home'))
        return render_template('admin.html', admin_enabled=True, is_admin=False, msg="❌ Falscher Benutzername oder Passwort.")

    # Legacy plaintext fallback
    expected_plain = _admin_password()
    if expected_plain and hmac.compare_digest(provided, expected_plain):
        session['is_admin'] = True
        return redirect(url_for('admin_home'))

    return render_template('admin.html', admin_enabled=True, is_admin=False, msg="❌ Falscher Benutzername oder Passwort.")


@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('admin_home'))


@app.route('/admin/sessions/generate', methods=['POST'])
def admin_generate_sessions():
    guard = _require_admin()
    if guard is not None:
        return guard

    n_raw = request.form.get('count', '20')
    try:
        n = int(n_raw)
    except Exception:
        n = 20

    codes = _generate_session_codes(n)
    _save_session_codes(codes)
    return redirect(url_for('admin_home'))


@app.route('/query_lis', methods=['POST'])
def query_lis():
    """Simulates a query to the Laboratory Information System (LIS) via HL7 ORU"""
    pid_raw = request.form.get('pid', 'UNKNOWN')
    pid = prefix_for_student(pid_raw) or 'UNKNOWN'
    code = get_student_code()

    if not _patient_exists(code, pid):
        return jsonify({
            'ok': False,
            'error': f"Unbekannte PID: {pid}. Bitte Patient zuerst im KIS erfassen.",
            'pid': pid,
        }), 400
    
    # Simulate a creatinine value (mg/dL)
    # Normal range approx 0.6 - 1.2
    # We'll make it random but deterministic based on PID so it doesn't change on retry
    random.seed(pid)
    base_val = random.uniform(0.5, 1.4)
    
    # 20% chance of being high (risk for contrast media)
    if random.random() > 0.8:
        base_val += random.uniform(0.5, 2.0)
        
    creatinine= round(base_val, 2)
    
    # Determine Status
    status = "NORMAL"
    color = "green"
    if creatinine > 1.3:
        status = "CRITICAL (Niereninsuffizienz?)"
        color = "red"
        
    raw_request = build_hl7_qry_q02(pid=pid)
    raw_oru = (
        f"MSH|^~\\&|LIS|LAB|RIS|RADIO|{_hl7_timestamp()}||ORU^R01|{_hl7_msg_control_id('ORU')}|P|2.3\r"
        f"PID|||{pid}||^\r"
        f"OBR|1|||KREA^Creatinine\r"
        f"OBX|1|NM|KREA||{creatinine}|mg/dL|0.6-1.2|{status}|||F"
    )

    session['last_lis_request_hl7'] = raw_request
    session['last_oru_hl7'] = raw_oru
    session['last_lis_summary'] = {
        'pid': pid,
        'value': creatinine,
        'unit': 'mg/dL',
        'status': status,
        'color': color,
    }
    session.modified = True

    return jsonify({
        'ok': True,
        'pid': pid,
        'structure': 'HL7 ORU^R01 (Observation Result)',
        'value': creatinine,
        'unit': 'mg/dL',
        'status': status,
        'color': color,
        'raw_request_hl7': raw_request,
        'raw_hl7': raw_oru,
    })

# --- DICOM Receiver (Store SCP) for the Workstation ---
# This runs in a background thread to receive images from Orthanc (C-MOVE)
STORE_SCP_PORT = 11112
RECEIVED_IMAGES = []

def handle_store(event):
    ds = event.dataset
    ds.file_meta = event.file_meta
    
    # Minimal validation
    patient_name = str(ds.PatientName) if 'PatientName' in ds else "Unknown"
    patient_id = str(ds.PatientID) if 'PatientID' in ds else ""
        
    RECEIVED_IMAGES.append({
        'PatientName': patient_name,
        'PatientID': patient_id,
        'StudyInstanceUID': str(ds.StudyInstanceUID) if 'StudyInstanceUID' in ds else 'Unknown',
        'Modality': str(ds.Modality) if 'Modality' in ds else 'OT',
        'Timestamp': datetime.datetime.now().strftime('%H:%M:%S')
    })
    
    # Return success status (0x0000)
    return 0x0000

def start_store_scp():
    ae = AE(ae_title=b'SIMULATOR')
    # Add supported presentation contexts for Storage
    ae.add_supported_context(sop_class.CTImageStorage)
    ae.add_supported_context(sop_class.MRImageStorage)
    ae.add_supported_context(sop_class.SecondaryCaptureImageStorage)
    ae.add_supported_context(sop_class.Verification)
    
    # Start listening
    print(f"Starting DICOM Store SCP on port {STORE_SCP_PORT}...")
    ae.start_server(('', STORE_SCP_PORT), evt_handlers=[(evt.EVT_C_STORE, handle_store)]) # Blocking call is fine in thread? No use block=False to avoid issues if needed


_scp_thread_started = False


def ensure_store_scp_thread_started():
    global _scp_thread_started
    if _scp_thread_started:
        return
    scp_thread = threading.Thread(target=start_store_scp, daemon=True)
    scp_thread.start()
    _scp_thread_started = True

# -----------------------------------------------------

WORKLIST_DIR = '/app/worklists'
ORTHANC_HOST = os.environ.get('ORTHANC_DICOM_HOST', 'orthanc')
ORTHANC_PORT = int(os.environ.get('ORTHANC_DICOM_PORT', 4242))
ORTHANC_HTTP_URL = (
    os.environ.get('ORTHANC_URL')
    or os.environ.get('ORTHANC_url')
    or 'http://orthanc:8042'
).rstrip('/')


def _orthanc_get_json(path: str, *, params: Optional[dict] = None):
    url = f"{ORTHANC_HTTP_URL}{path}"
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def _orthanc_get_bytes(path: str, *, params: Optional[dict] = None) -> bytes:
    url = f"{ORTHANC_HTTP_URL}{path}"
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.content


def _orthanc_post_json(path: str, payload: dict):
    url = f"{ORTHANC_HTTP_URL}{path}"
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()
    return r.json()


def _orthanc_post_dicom_instance(dicom_bytes: bytes) -> dict:
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


_DICOM_TAG_RE = re.compile(r"\(?\s*([0-9a-fA-F]{4})\s*,\s*([0-9a-fA-F]{4})\s*\)?")
_DICOM_TAG_HEX8_RE = re.compile(r"^\s*([0-9a-fA-F]{8})\s*$")


def _parse_dicom_tag(tag_text: str, keyword_text: str) -> Optional[Tag]:
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


def _value_for_vr(vr: str, raw_value: str):
    """Best-effort conversion: supports multi-value with backslash separators."""
    vr = (vr or '').strip().upper()
    raw_value = '' if raw_value is None else str(raw_value)

    if vr == 'SQ':
        raise ValueError('SQ (Sequence) wird im Editor nicht unterstützt.')

    if '\\' in raw_value:
        parts = [p for p in raw_value.split('\\')]
        return parts
    return raw_value


def _ensure_new_sop_instance_uid(ds: pydicom.dataset.Dataset) -> None:
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


def _render_dicom_png(dicom_bytes: bytes) -> bytes:
    # Minimal, best-effort PNG renderer for teaching demos.
    # Works well for uncompressed single-frame images; compressed/unsupported
    # transfer syntaxes will raise and be handled by the caller.
    import numpy as np
    from PIL import Image

    ds = pydicom.dcmread(BytesIO(dicom_bytes), force=True)
    arr = ds.pixel_array  # requires numpy and pixel data handlers

    if arr is None:
        raise ValueError("Keine Pixel-Daten")

    # Multi-frame: take first frame
    if hasattr(arr, "ndim") and arr.ndim == 3 and arr.shape[0] not in (3, 4):
        # Likely frames x rows x cols
        arr = arr[0]

    # Grayscale 2D
    if arr.ndim == 2:
        a = arr.astype(np.float32)
        mn = float(np.min(a))
        mx = float(np.max(a))
        if mx <= mn:
            a8 = np.zeros_like(a, dtype=np.uint8)
        else:
            a8 = ((a - mn) * (255.0 / (mx - mn))).clip(0, 255).astype(np.uint8)
        img = Image.fromarray(a8, mode="L")
    # Color image
    elif arr.ndim == 3 and arr.shape[-1] in (3, 4):
        a8 = arr
        if a8.dtype != np.uint8:
            a8 = a8.astype(np.uint8)
        img = Image.fromarray(a8)
    else:
        raise ValueError(f"Unsupported pixel array shape: {getattr(arr, 'shape', None)}")

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


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


def derive_study_uid(accession_number: str) -> str:
    # Deterministic Study UID for this simulation (derived from Accession)
    digest = hashlib.md5((accession_number + ".study").encode()).hexdigest()
    return "1.2.826.0.1.3680043.2." + str(int(digest, 16))[:10]

def create_dicom_worklist_file(patient_name, patient_id, accession_number, study_desc):
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = '1.2.840.10008.5.1.4.1.1.7' # Secondary Capture (dummy)
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.ImplementationClassUID = generate_uid()

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
    
    # Required attributes for valid DICOM
    ds.SpecificCharacterSet = "ISO_IR 100"
    
    # Deterministic Study UID for this simulation (derived from Accession)
    ds.StudyInstanceUID = derive_study_uid(accession_number)
    
    # MWL specific tags
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.AccessionNumber = accession_number
    ds.StudyID = accession_number
    ds.StudyDescription = study_desc
    ds.ReferringPhysicianName = "Dr. House"

    # Scheduled Procedure Step Sequence
    sps = Dataset()
    sps.ScheduledStationAETitle = "SIMULATOR"
    sps.ScheduledProcedureStepStartDate = datetime.datetime.now().strftime('%Y%m%d')
    sps.ScheduledProcedureStepStartTime = datetime.datetime.now().strftime('%H%M%S')
    sps.Modality = "CT"
    sps.ScheduledProcedureStepDescription = study_desc
    sps.ScheduledProcedureStepID = accession_number
    
    ds.ScheduledProcedureStepSequence = [sps]
    
    # Requested Procedure
    ds.RequestedProcedureID = accession_number
    ds.RequestedProcedureDescription = study_desc
    
    safe_acc = safe_filename_component(accession_number)
    filename = os.path.join(WORKLIST_DIR, f"{safe_acc}.wl")
    ds.save_as(filename, write_like_original=False)
    return filename

def dataset_to_dict(ds):
    res = {}
    # Extract root level simple elements
    for elem in ds:
        if elem.VR != "SQ":
            key = elem.keyword if elem.keyword else str(elem.tag)
            res[key] = str(elem.value)
            
    # Extract from SPS Sequence (often nested in MWL)
    if 'ScheduledProcedureStepSequence' in ds and len(ds.ScheduledProcedureStepSequence) > 0:
        sps = ds.ScheduledProcedureStepSequence[0]
        if 'ScheduledProcedureStepDescription' in sps:
             res['RequestedProcedureDescription'] = str(sps.ScheduledProcedureStepDescription)
        if 'Modality' in sps:
             res['Modality'] = str(sps.Modality)
             
    return res

def perform_c_find_mwl():
    ae = AE(ae_title=b'SIMULATOR')
    ae.add_requested_context(sop_class.ModalityWorklistInformationFind)

    # Associate with Peer
    assoc = ae.associate(ORTHANC_HOST, ORTHANC_PORT)

    results = []
    if assoc.is_established:
        print('Association established with Orthanc')
        # Create a query dataset
        ds = Dataset()
        ds.PatientName = '*'
        code = get_student_code()
        ds.PatientID = f"{code}-*" if code else ''
        ds.AccessionNumber = ''
        ds.StudyInstanceUID = ''
        ds.RequestedProcedureDescription = ''
        
        ds.ScheduledProcedureStepSequence = [Dataset()]
        ds.ScheduledProcedureStepSequence[0].ScheduledStationAETitle = 'SIMULATOR'
        ds.ScheduledProcedureStepSequence[0].ScheduledProcedureStepStartDate = datetime.datetime.now().strftime('%Y%m%d')
        ds.ScheduledProcedureStepSequence[0].Modality = 'CT'
        ds.ScheduledProcedureStepSequence[0].ScheduledProcedureStepDescription = ''
        ds.ScheduledProcedureStepSequence[0].ScheduledProcedureStepID = ''

        responses = assoc.send_c_find(ds, query_model=sop_class.ModalityWorklistInformationFind)
        
        for (status, dataset) in responses:
             # C-FIND yields (status, identifier)
             # If status is Pending (0xFF00) or Success (0x0000)
             if status.Status == 0xFF00: 
                 if dataset:
                     results.append(dataset_to_dict(dataset))
             elif status.Status == 0x0000:
                 pass # Success
        
        assoc.release()
    else:
        print('Association rejected, aborted or never connected')
        
    return results

def send_c_store(patient_name, patient_id, accession_number, study_uid=None):
    ae = AE(ae_title=b'SIMULATOR')
    ae.add_requested_context(sop_class.CTImageStorage) 
    
    if not study_uid:
        # Re-derive StudyUID from Accession to match MWL logic
        study_uid = derive_study_uid(accession_number)

    assoc = ae.associate(ORTHANC_HOST, ORTHANC_PORT)
    if assoc.is_established:
        # Create minimal CT Image
        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = sop_class.CTImageStorage
        file_meta.MediaStorageSOPInstanceUID = generate_uid()
        file_meta.TransferSyntaxUID = pydicom.uid.ImplicitVRLittleEndian

        ds = FileDataset('dummy.dcm', {}, file_meta=file_meta, preamble=b"\0" * 128)
        
        ds.PatientName = patient_name
        ds.PatientID = patient_id
        ds.AccessionNumber = accession_number
        ds.Modality = 'CT'
        ds.StudyInstanceUID = study_uid if study_uid else generate_uid()
        ds.SeriesInstanceUID = generate_uid()
        ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
        ds.SOPClassUID = sop_class.CTImageStorage
        
        # Add minimal required tags for CT Image Storage
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.Rows = 512
        ds.Columns = 512
        ds.BitsAllocated = 16
        ds.BitsStored = 12
        ds.HighBit = 11
        ds.PixelRepresentation = 0
        ds.PixelData = (b'\x00\x00' * 512 * 512) # Blank image

        status = assoc.send_c_store(ds)
        assoc.release()
        return status
    return None


def _save_upload_to_tempdir(upload, temp_dir: str) -> str:
    filename = upload.filename or "upload"
    safe_name = os.path.basename(filename)
    if not safe_name:
        safe_name = "upload"
    target_path = os.path.join(temp_dir, safe_name)
    upload.save(target_path)
    return target_path


def _collect_dicom_file_paths_from_uploads(uploads):
    """Return (dicom_file_paths, temp_dir). Caller must delete temp_dir."""
    temp_dir = tempfile.mkdtemp(prefix="dicom_upload_")
    extracted_dir = os.path.join(temp_dir, "extracted")
    os.makedirs(extracted_dir, exist_ok=True)

    file_paths = []
    for upload in uploads:
        if not upload or not getattr(upload, "filename", None):
            continue

        saved_path = _save_upload_to_tempdir(upload, temp_dir)
        if saved_path.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(saved_path, 'r') as zf:
                    zf.extractall(extracted_dir)
            except zipfile.BadZipFile:
                file_paths.append(saved_path)
        else:
            file_paths.append(saved_path)

    for root, _, files in os.walk(extracted_dir):
        for name in files:
            file_paths.append(os.path.join(root, name))

    # Heuristic: if there are obvious DICOM extensions, filter; otherwise keep all
    likely = [p for p in file_paths if p.lower().endswith((".dcm", ".dicom"))]
    if likely:
        return likely, temp_dir

    return file_paths, temp_dir


def send_c_store_uploaded_files(dicom_paths, *, patient_name, patient_id, accession_number, retag):
    """Send real DICOM instances via C-STORE to Orthanc.

    Returns a summary dict with counters and a small error list.
    """
    from pynetdicom.presentation import StoragePresentationContexts

    summary = {
        "sent": 0,
        "ok": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
    }

    if not dicom_paths:
        return summary

    study_uid = derive_study_uid(accession_number)

    # Some uploads may be compressed (e.g. JPEG 2000). Request a broader set of
    # transfer syntaxes so Orthanc can accept them when supported.
    from pydicom.uid import (
        ExplicitVRLittleEndian,
        ImplicitVRLittleEndian,
        ExplicitVRBigEndian,
        DeflatedExplicitVRLittleEndian,
        JPEGBaseline8Bit,
        JPEGExtended12Bit,
        JPEGLosslessSV1,
        JPEGLSLossless,
        JPEGLSNearLossless,
        JPEG2000,
        JPEG2000Lossless,
        RLELossless,
    )

    requested_transfer_syntaxes = [
        ExplicitVRLittleEndian,
        ImplicitVRLittleEndian,
        DeflatedExplicitVRLittleEndian,
        ExplicitVRBigEndian,
        JPEGBaseline8Bit,
        JPEGExtended12Bit,
        JPEGLosslessSV1,
        JPEGLSLossless,
        JPEGLSNearLossless,
        JPEG2000Lossless,
        JPEG2000,
        RLELossless,
    ]

    ae = AE(ae_title=b'SIMULATOR')
    for cx in StoragePresentationContexts:
        ae.add_requested_context(cx.abstract_syntax, requested_transfer_syntaxes)

    assoc = ae.associate(ORTHANC_HOST, ORTHANC_PORT)
    if not assoc.is_established:
        summary["errors"].append("DICOM Association gescheitert. Ist Orthanc erreichbar?")
        return summary

    try:
        for path in dicom_paths:
            try:
                ds = pydicom.dcmread(path, force=True)
            except Exception as e:
                summary["skipped"] += 1
                summary["errors"].append(f"Nicht lesbar: {os.path.basename(path)} ({e})")
                continue

            # Skip non-storage objects
            if not hasattr(ds, "SOPClassUID") or not hasattr(ds, "SOPInstanceUID"):
                summary["skipped"] += 1
                continue

            if retag:
                ds.PatientName = patient_name
                ds.PatientID = patient_id
                ds.AccessionNumber = accession_number
                ds.StudyID = accession_number
                ds.StudyInstanceUID = study_uid
                ds.Modality = getattr(ds, "Modality", "CT") or "CT"

            summary["sent"] += 1

            try:
                status = assoc.send_c_store(ds)
            except ValueError as e:
                # Typical case: dataset is compressed (e.g. JPEG2000) but no accepted
                # presentation context exists for that transfer syntax.
                # Try to decompress (if pixel data handlers are available) and retry.
                try:
                    ts = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
                    is_compressed = bool(getattr(ts, "is_compressed", False))
                except Exception:
                    is_compressed = False

                if is_compressed and hasattr(ds, "decompress"):
                    try:
                        ds.decompress()
                        status = assoc.send_c_store(ds)
                    except Exception:
                        summary["failed"] += 1
                        summary["errors"].append(
                            "C-STORE fehlgeschlagen: Komprimierte DICOM-Datei (z.B. JPEG2000) "
                            "konnte nicht gesendet/entpackt werden. Bitte unkomprimierte DICOMs hochladen "
                            "oder Orthanc mit Unterstützung für diese Kompression betreiben. "
                            f"Datei: {os.path.basename(path)}"
                        )
                        continue
                else:
                    summary["failed"] += 1
                    summary["errors"].append(
                        f"C-STORE fehlgeschlagen (Transfer Syntax nicht akzeptiert): {os.path.basename(path)} ({e})"
                    )
                    continue
            except Exception as e:
                summary["failed"] += 1
                summary["errors"].append(f"C-STORE Fehlermeldung: {os.path.basename(path)} ({e})")
                continue

            if status and getattr(status, "Status", None) == 0x0000:
                summary["ok"] += 1
            else:
                summary["failed"] += 1
                st = f"0x{getattr(status, 'Status', 0):04x}" if status else "(kein Status)"
                summary["errors"].append(f"C-STORE fehlgeschlagen: {os.path.basename(path)} Status {st}")
    finally:
        assoc.release()

    return summary


@app.route('/')
def index():
    code = get_student_code()
    patients = _load_patients(code)
    return render_template(
        'index.html',
        patients=patients,
        ris_reports_by_pid=_reports_index_by_pid(code),
        ris_reports=_load_reports(code) if code else [],
        last_adt_hl7=session.get('last_adt_hl7', ''),
        last_lis_request_hl7=session.get('last_lis_request_hl7', ''),
        last_oru_hl7=session.get('last_oru_hl7', ''),
        last_lis_summary=session.get('last_lis_summary', None),
        workflow_current="1. HL7 ADT: KIS → RIS (Patient aufnehmen)",
        workflow_next="2. HL7 ORU: RIS ↔ LIS (Kreatinin)",
    )

@app.route('/echo', methods=['POST'])
def echo():
    code = get_student_code()
    try:
        from pynetdicom import AE, sop_class
        ae = AE(ae_title=b'SIMULATOR')
        ae.add_requested_context(sop_class.Verification)
        assoc = ae.associate(ORTHANC_HOST, ORTHANC_PORT)
        if assoc.is_established:
            status = assoc.send_c_echo()
            assoc.release()
            return render_template(
                'index.html',
                patients=_load_patients(code),
                ris_reports_by_pid=_reports_index_by_pid(code),
                ris_reports=_load_reports(code) if code else [],
                msg=f"✅ DICOM C-ECHO erfolgreich! Das PACS ist unter {ORTHANC_HOST}:{ORTHANC_PORT} erreichbar.",
                last_adt_hl7=session.get('last_adt_hl7', ''),
                last_lis_request_hl7=session.get('last_lis_request_hl7', ''),
                last_oru_hl7=session.get('last_oru_hl7', ''),
                last_lis_summary=session.get('last_lis_summary', None),
                workflow_current="1. HL7 ADT: KIS → RIS (Patient aufnehmen)",
                workflow_next="2. HL7 ORU: RIS ↔ LIS (Kreatinin)",
            )
        else:
            return render_template(
                'index.html',
                patients=_load_patients(code),
                ris_reports_by_pid=_reports_index_by_pid(code),
                ris_reports=_load_reports(code) if code else [],
                msg="❌ DICOM Association gescheitert. Ist der Orthanc-Container gestartet?",
                last_adt_hl7=session.get('last_adt_hl7', ''),
                last_lis_request_hl7=session.get('last_lis_request_hl7', ''),
                last_oru_hl7=session.get('last_oru_hl7', ''),
                last_lis_summary=session.get('last_lis_summary', None),
                workflow_current="1. HL7 ADT: KIS → RIS (Patient aufnehmen)",
                workflow_next="2. HL7 ORU: RIS ↔ LIS (Kreatinin)",
            )
    except Exception as e:
        return render_template(
            'index.html',
            patients=_load_patients(code),
            ris_reports_by_pid=_reports_index_by_pid(code),
            ris_reports=_load_reports(code) if code else [],
            msg=f"❌ Fehler bei C-ECHO: {str(e)}",
            last_adt_hl7=session.get('last_adt_hl7', ''),
            last_lis_request_hl7=session.get('last_lis_request_hl7', ''),
            last_oru_hl7=session.get('last_oru_hl7', ''),
            last_lis_summary=session.get('last_lis_summary', None),
            workflow_current="1. HL7 ADT: KIS → RIS (Patient aufnehmen)",
            workflow_next="2. HL7 ORU: RIS ↔ LIS (Kreatinin)",
        )


@app.route('/kis/register_patient', methods=['POST'])
def kis_register_patient():
    name = (request.form.get('name') or '').strip()
    pid_raw = (request.form.get('pid') or '').strip()
    code = get_student_code()

    if not name or not pid_raw:
        return render_template(
            'index.html',
            patients=_load_patients(code),
            ris_reports_by_pid=_reports_index_by_pid(code),
            ris_reports=_load_reports(code) if code else [],
            msg="❌ Bitte Patientenname und PID angeben.",
            last_adt_hl7=session.get('last_adt_hl7', ''),
            last_lis_request_hl7=session.get('last_lis_request_hl7', ''),
            last_oru_hl7=session.get('last_oru_hl7', ''),
            last_lis_summary=session.get('last_lis_summary', None),
            workflow_current="1. HL7 ADT: KIS → RIS (Patient aufnehmen)",
            workflow_next="2. HL7 ORU: RIS ↔ LIS (Kreatinin)",
        )

    pid = prefix_for_student(pid_raw) or 'UNKNOWN'
    _upsert_patient(code, name, pid)

    raw_hl7 = build_hl7_adt_a04(pid=pid, name=name)
    session['last_adt_hl7'] = raw_hl7
    session.modified = True

    return render_template(
        'index.html',
        msg=f"✅ Patient erfasst: {name} (PID: {pid}).",
        patients=_load_patients(code),
        ris_reports_by_pid=_reports_index_by_pid(code),
        ris_reports=_load_reports(code) if code else [],
        last_adt_hl7=raw_hl7,
        last_lis_request_hl7=session.get('last_lis_request_hl7', ''),
        last_oru_hl7=session.get('last_oru_hl7', ''),
        last_lis_summary=session.get('last_lis_summary', None),
        workflow_current="1. HL7 ADT: KIS → RIS (Patient aufnehmen)",
        workflow_next="2. HL7 ORU: RIS ↔ LIS (Kreatinin)",
    )

@app.route('/create_order', methods=['POST'])
def create_order():
    name = request.form.get('name')
    pid = prefix_for_student(request.form.get('pid'))
    acc = prefix_for_student(request.form.get('acc'))
    desc = request.form.get('desc')

    code = get_student_code()
    if not _patient_exists(code, pid):
        return render_template(
            'index.html',
            msg=f"❌ Unbekannte PID: {pid}. Bitte Patient zuerst im KIS erfassen.",
            patients=_load_patients(code),
            ris_reports_by_pid=_reports_index_by_pid(code),
            ris_reports=_load_reports(code) if code else [],
            last_adt_hl7=session.get('last_adt_hl7', ''),
            last_lis_request_hl7=session.get('last_lis_request_hl7', ''),
            last_oru_hl7=session.get('last_oru_hl7', ''),
            last_lis_summary=session.get('last_lis_summary', None),
            workflow_current="1. HL7 ADT: KIS → RIS (Patient aufnehmen)",
            workflow_next="2. HL7 ORU: RIS ↔ LIS (Kreatinin)",
        )
    
    create_dicom_worklist_file(name, pid, acc, desc)
    ns = f" (SuS-Code: {code})" if code else ""
    msg = f"✅ Auftrag erfolgreich! HL7 ORM wurde simuliert und ein Worklist-Eintrag für '{name}' erstellt.{ns}"
    return render_template(
        'index.html',
        msg=msg,
        patients=_load_patients(code),
        ris_reports_by_pid=_reports_index_by_pid(code),
        ris_reports=_load_reports(code) if code else [],
        last_adt_hl7=session.get('last_adt_hl7', ''),
        last_lis_request_hl7=session.get('last_lis_request_hl7', ''),
        last_oru_hl7=session.get('last_oru_hl7', ''),
        last_lis_summary=session.get('last_lis_summary', None),
        workflow_current="3. HL7 ORM: RIS (Auftrag freigeben)",
        workflow_next="4. DICOM C-FIND (MWL): Worklist abrufen",
    )

@app.route('/modality')
def modality():
    items = perform_c_find_mwl()
    return render_template(
        'modality.html',
        items=items,
        workflow_current="4. DICOM C-FIND (MWL): Worklist abrufen",
        workflow_next="5. DICOM C-STORE: Bilder senden → PACS",
    )

@app.route('/scan', methods=['POST'])
def scan():
    name = request.form.get('name')
    pid = prefix_for_student(request.form.get('pid'))
    acc = prefix_for_student(request.form.get('acc'))

    uploads = request.files.getlist('dicom_files') if request.files else []
    retag = request.form.get('retag') == 'on'

    if uploads and any(u and u.filename for u in uploads):
        dicom_paths, temp_dir = _collect_dicom_file_paths_from_uploads(uploads)
        try:
            summary = send_c_store_uploaded_files(
                dicom_paths,
                patient_name=name,
                patient_id=pid,
                accession_number=acc,
                retag=retag,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        if summary["sent"] == 0 and summary["skipped"] > 0:
            msg = "⚠️ Es wurden Dateien hochgeladen, aber keine gültigen DICOM-Instanzen gefunden (SOPClassUID/SOPInstanceUID fehlen)."
        else:
            msg = (
                f"☢️ Upload-Scan für {name}: gesendet={summary['sent']}, ok={summary['ok']}, "
                f"fehlgeschlagen={summary['failed']}, übersprungen={summary['skipped']}."
            )
            if summary["errors"]:
                msg += " Details: " + " | ".join(summary["errors"][:3])
                if len(summary["errors"]) > 3:
                    msg += f" (+{len(summary['errors']) - 3} weitere)"
    else:
        status = send_c_store(name, pid, acc)
        msg = f"☢️ Dummy-Scan für {name}. (Hinweis: Für echte Daten bitte DICOM-Dateien hochladen.) Status: {status}."

    items = perform_c_find_mwl()
    return render_template(
        'modality.html',
        items=items,
        msg=msg,
        workflow_current="5. DICOM C-STORE: Bilder senden → PACS",
        workflow_next="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studien suchen)",
    )


@app.route('/pacs')
def pacs_home():
    code = get_student_code()
    accession_filter = (request.args.get('acc') or '').strip()
    try:
        studies = _orthanc_get_json('/studies', params={'expand': 'true'})
    except Exception as e:
        return render_template(
            'pacs.html',
            studies=[],
            msg=f"❌ Orthanc nicht erreichbar: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studien suchen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    visible = [s for s in (studies or []) if _study_visible_for_student(s, code)]
    if accession_filter:
        visible = [
            s for s in visible
            if str((s.get('MainDicomTags') or {}).get('AccessionNumber') or '') == accession_filter
        ]
    # Sort: newest first when StudyDate is present
    def _sort_key(st):
        tags = (st.get('MainDicomTags') or {})
        return (tags.get('StudyDate') or '', tags.get('StudyTime') or '')
    visible.sort(key=_sort_key, reverse=True)

    return render_template(
        'pacs.html',
        studies=visible,
        acc=accession_filter,
        workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studien suchen)",
        workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
    )


@app.route('/pacs/studies/<study_id>')
def pacs_study(study_id: str):
    code = get_student_code()
    msg = (request.args.get('msg') or '').strip() or None
    try:
        study = _orthanc_get_json(f'/studies/{study_id}', params={'expand': 'true'})
    except Exception as e:
        return render_template(
            'pacs_study.html',
            study=None,
            msg=f"❌ Fehler beim Laden der Studie: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studie anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    if not _study_visible_for_student(study, code):
        abort(404)

    series_ids = [str(x) for x in (study.get('Series') or [])]
    series = []
    for sid in series_ids:
        try:
            series.append(_orthanc_get_json(f'/series/{sid}', params={'expand': 'true'}))
        except Exception:
            continue

    return render_template(
        'pacs_study.html',
        study=study,
        series=series,
        msg=msg,
        workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studie anzeigen)",
        workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
    )


@app.route('/pacs/series/<series_id>')
def pacs_series(series_id: str):
    code = get_student_code()
    msg = (request.args.get('msg') or '').strip() or None
    try:
        series = _orthanc_get_json(f'/series/{series_id}', params={'expand': 'true'})
    except Exception as e:
        return render_template(
            'pacs_series.html',
            study=None,
            series=None,
            instances=[],
            msg=f"❌ Fehler beim Laden der Serie: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Serie anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    parent_study_id = str(series.get('ParentStudy') or '')
    if not parent_study_id:
        return render_template(
            'pacs_series.html',
            study=None,
            series=series,
            instances=[],
            msg="❌ ParentStudy fehlt.",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Serie anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    try:
        study = _orthanc_get_json(f'/studies/{parent_study_id}', params={'expand': 'true'})
    except Exception as e:
        return render_template(
            'pacs_series.html',
            study=None,
            series=series,
            instances=[],
            msg=f"❌ Fehler beim Laden der Studie: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Serie anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    if not _study_visible_for_student(study, code):
        abort(404)

    instance_ids = [str(x) for x in (series.get('Instances') or [])]
    instances = []
    for iid in instance_ids[:200]:
        try:
            instances.append(_orthanc_get_json(f'/instances/{iid}'))
        except Exception:
            instances.append({'ID': iid, 'MainDicomTags': {}})

    return render_template(
        'pacs_series.html',
        study=study,
        series=series,
        instances=instances,
        msg=msg,
        workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Serie anzeigen)",
        workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
    )


@app.route('/pacs/series/<series_id>/derive_seg', methods=['POST'])
def pacs_series_derive_seg(series_id: str):
    code = get_student_code()

    try:
        series = _orthanc_get_json(f'/series/{series_id}', params={'expand': 'true'})
    except Exception as e:
        return redirect(url_for('pacs_series', series_id=series_id, msg=f"❌ Serie konnte nicht geladen werden: {e}"))

    parent_study_id = str(series.get('ParentStudy') or '').strip()
    if not parent_study_id:
        return redirect(url_for('pacs_series', series_id=series_id, msg="❌ ParentStudy fehlt."))

    try:
        study = _orthanc_get_json(f'/studies/{parent_study_id}', params={'expand': 'true'})
    except Exception as e:
        return redirect(url_for('pacs_series', series_id=series_id, msg=f"❌ Studie konnte nicht geladen werden: {e}"))

    if not _study_visible_for_student(study, code):
        abort(404)

    instance_ids = [str(x) for x in (series.get('Instances') or [])]
    if not instance_ids:
        return redirect(url_for('pacs_series', series_id=series_id, msg="❌ Keine Instanzen in dieser Serie."))

    # Keep the demo reasonably fast.
    instance_ids = instance_ids[:30]

    new_series_uid = generate_uid()
    uploaded_instance_ids: list[str] = []
    new_series_id: Optional[str] = None

    try:
        for iid in instance_ids:
            dicom_bytes = _orthanc_get_bytes(f'/instances/{iid}/file')
            ds = pydicom.dcmread(BytesIO(dicom_bytes), force=True)

            # Simulate a derived "segmentation" series (not a real DICOM-SEG IOD).
            try:
                ds.SeriesInstanceUID = new_series_uid
            except Exception:
                pass
            try:
                ds.SeriesDescription = 'Segmentation (simulated)'
            except Exception:
                pass
            try:
                ds.ImageType = ['DERIVED', 'SECONDARY']
            except Exception:
                pass
            try:
                ds.DerivationDescription = 'Simulated derived series (teaching demo)'
            except Exception:
                pass

            # Bump series number so it shows up separately in many viewers.
            try:
                base = int(getattr(ds, 'SeriesNumber', 0) or 0)
                ds.SeriesNumber = base + 500
            except Exception:
                try:
                    ds.SeriesNumber = 500
                except Exception:
                    pass

            _ensure_new_sop_instance_uid(ds)
            try:
                if hasattr(ds, 'file_meta') and ds.file_meta is not None:
                    try:
                        ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
                    except Exception:
                        pass
            except Exception:
                pass

            buf = BytesIO()
            pydicom.dcmwrite(buf, ds, write_like_original=False)
            resp = _orthanc_post_dicom_instance(buf.getvalue())
            new_instance_id = str(resp.get('ID') or '').strip()
            if new_instance_id:
                uploaded_instance_ids.append(new_instance_id)

                if not new_series_id:
                    try:
                        inst_meta = _orthanc_get_json(f'/instances/{new_instance_id}')
                        new_series_id = str(inst_meta.get('ParentSeries') or '').strip() or None
                    except Exception:
                        new_series_id = None

        if not uploaded_instance_ids:
            return redirect(url_for('pacs_series', series_id=series_id, msg="❌ Upload fehlgeschlagen (keine Instanzen erzeugt)."))

        target = new_series_id or series_id
        return redirect(url_for(
            'pacs_series',
            series_id=target,
            msg=f"✅ Derived Series erzeugt: 'Segmentation (simulated)' ({len(uploaded_instance_ids)} Instanzen).",
        ))
    except Exception as e:
        return redirect(url_for('pacs_series', series_id=series_id, msg=f"❌ Derived Series fehlgeschlagen: {e}"))


@app.route('/pacs/instances/<instance_id>')
def pacs_instance(instance_id: str):
    code = get_student_code()
    msg = (request.args.get('msg') or '').strip() or None
    series_id = (request.args.get('series') or '').strip()
    index_raw = (request.args.get('i') or '0').strip()
    try:
        index = max(0, int(index_raw))
    except Exception:
        index = 0

    try:
        instance = _orthanc_get_json(f'/instances/{instance_id}')
    except Exception as e:
        return render_template(
            'pacs_instance.html',
            study=None,
            series=None,
            instance=None,
            tags=[],
            instance_ids=[],
            i=0,
            msg=f"❌ Fehler beim Laden der Instanz: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Instanz anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    parent_series_id = str(instance.get('ParentSeries') or '')
    if not series_id:
        series_id = parent_series_id
    if not series_id:
        return render_template(
            'pacs_instance.html',
            study=None,
            series=None,
            instance=instance,
            tags=[],
            instance_ids=[],
            i=0,
            msg="❌ ParentSeries fehlt.",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Instanz anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    try:
        series = _orthanc_get_json(f'/series/{series_id}', params={'expand': 'true'})
    except Exception as e:
        return render_template(
            'pacs_instance.html',
            study=None,
            series=None,
            instance=instance,
            tags=[],
            instance_ids=[],
            i=0,
            msg=f"❌ Fehler beim Laden der Serie: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Instanz anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    parent_study_id = str(series.get('ParentStudy') or '')
    try:
        study = _orthanc_get_json(f'/studies/{parent_study_id}', params={'expand': 'true'})
    except Exception as e:
        return render_template(
            'pacs_instance.html',
            study=None,
            series=series,
            instance=instance,
            tags=[],
            instance_ids=[],
            i=0,
            msg=f"❌ Fehler beim Laden der Studie: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Instanz anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    if not _study_visible_for_student(study, code):
        abort(404)

    instance_ids = [str(x) for x in (series.get('Instances') or [])]
    if instance_id in instance_ids:
        index = instance_ids.index(instance_id)
    if index >= len(instance_ids):
        index = max(0, len(instance_ids) - 1)

    tags = []
    try:
        dicom_bytes = _orthanc_get_bytes(f'/instances/{instance_id}/file')
        tags = _dicom_tags_for_table(dicom_bytes)
    except Exception as e:
        tags = []
        msg = f"⚠️ Metadaten konnten nicht gelesen werden: {e}"
        return render_template(
            'pacs_instance.html',
            study=study,
            series=series,
            instance=instance,
            tags=tags,
            instance_ids=instance_ids,
            i=index,
            msg=msg,
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Instanz anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    return render_template(
        'pacs_instance.html',
        study=study,
        series=series,
        instance=instance,
        tags=tags,
        instance_ids=instance_ids,
        i=index,
        msg=msg,
        workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Instanz anzeigen)",
        workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
    )


@app.route('/pacs/open_by_uid')
def pacs_open_by_uid():
    code = get_student_code()
    study_uid = (request.args.get('study_uid') or '').strip()
    if not study_uid:
        return redirect(url_for('pacs_home'))

    try:
        result = _orthanc_post_json('/tools/find', {
            'Level': 'Study',
            'Query': {
                'StudyInstanceUID': study_uid,
            },
            'Limit': 20,
        })
    except Exception as e:
        return render_template(
            'pacs.html',
            studies=[],
            msg=f"❌ Orthanc Suche fehlgeschlagen: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studien suchen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    study_ids = []
    if isinstance(result, list):
        study_ids = [str(x) for x in result]
    elif isinstance(result, dict) and isinstance(result.get('ID'), str):
        study_ids = [result['ID']]
    elif isinstance(result, dict) and isinstance(result.get('Results'), list):
        study_ids = [str(x) for x in result.get('Results')]

    for sid in study_ids:
        try:
            st = _orthanc_get_json(f'/studies/{sid}', params={'expand': 'true'})
            if _study_visible_for_student(st, code):
                return redirect(url_for('pacs_study', study_id=sid))
        except Exception:
            continue

    return render_template(
        'pacs.html',
        studies=[],
        msg="⚠️ Studie nicht gefunden oder nicht sichtbar für diesen SuS-Code.",
        workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studien suchen)",
        workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
    )


@app.route('/pacs/open_first_instance_by_uid')
def pacs_open_first_instance_by_uid():
    """Convenience for Workstation: jump directly to first instance viewer for a StudyInstanceUID."""
    code = get_student_code()
    study_uid = (request.args.get('study_uid') or '').strip()
    if not study_uid:
        return redirect(url_for('pacs_home'))

    try:
        result = _orthanc_post_json('/tools/find', {
            'Level': 'Study',
            'Query': {
                'StudyInstanceUID': study_uid,
            },
            'Limit': 20,
        })
    except Exception as e:
        return render_template(
            'pacs.html',
            studies=[],
            msg=f"❌ Orthanc Suche fehlgeschlagen: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studien suchen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    study_ids = []
    if isinstance(result, list):
        study_ids = [str(x) for x in result]
    elif isinstance(result, dict) and isinstance(result.get('ID'), str):
        study_ids = [result['ID']]
    elif isinstance(result, dict) and isinstance(result.get('Results'), list):
        study_ids = [str(x) for x in result.get('Results')]

    for sid in study_ids:
        try:
            st = _orthanc_get_json(f'/studies/{sid}', params={'expand': 'true'})
            if not _study_visible_for_student(st, code):
                continue
            series_list = st.get('Series') or []
            if not series_list:
                return redirect(url_for('pacs_study', study_id=sid))
            first_series_id = str(series_list[0])
            se = _orthanc_get_json(f'/series/{first_series_id}', params={'expand': 'true'})
            insts = se.get('Instances') or []
            if not insts:
                return redirect(url_for('pacs_series', series_id=first_series_id))
            return redirect(url_for('pacs_instance', instance_id=str(insts[0]), series=first_series_id))
        except Exception:
            continue

    return render_template(
        'pacs.html',
        studies=[],
        msg="⚠️ Studie nicht gefunden oder nicht sichtbar für diesen SuS-Code.",
        workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studien suchen)",
        workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
    )


@app.route('/pacs/studies/<study_id>/viewer')
def pacs_viewer(study_id: str):
    code = get_student_code()
    try:
        study = _orthanc_get_json(f'/studies/{study_id}', params={'expand': 'true'})
    except Exception as e:
        return render_template(
            'pacs.html',
            studies=[],
            msg=f"❌ Fehler beim Laden der Studie: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studien suchen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    if not _study_visible_for_student(study, code):
        abort(404)

    series_list = study.get('Series') or []
    if not series_list:
        return render_template(
            'pacs_study.html',
            study=study,
            series=[],
            msg="⚠️ Keine Serien in dieser Studie.",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studie anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    first_series_id = str(series_list[0])
    try:
        series = _orthanc_get_json(f'/series/{first_series_id}', params={'expand': 'true'})
    except Exception:
        return redirect(url_for('pacs_series', series_id=first_series_id))

    instance_ids = [str(x) for x in (series.get('Instances') or [])]
    if not instance_ids:
        return redirect(url_for('pacs_series', series_id=first_series_id))

    return redirect(url_for('pacs_instance', instance_id=instance_ids[0], series=first_series_id))


@app.route('/pacs/instances/<instance_id>/preview.png')
def pacs_instance_preview(instance_id: str):
    # Best-effort: render as PNG. If it fails, return a readable error.
    try:
        dicom_bytes = _orthanc_get_bytes(f'/instances/{instance_id}/file')
        png = _render_dicom_png(dicom_bytes)
        resp = make_response(png)
        resp.headers['Content-Type'] = 'image/png'
        resp.headers['Cache-Control'] = 'no-store'
        return resp
    except Exception as e:
        return make_response(
            f"Cannot render this DICOM instance as PNG ({e}). If this is a compressed DICOM (e.g. JPEG2000), upload an uncompressed export.",
            415,
        )


@app.route('/pacs/instances/<instance_id>/edit_metadata', methods=['POST'])
def pacs_instance_edit_metadata(instance_id: str):
    """Edit or add a DICOM tag on an instance by re-uploading a modified copy to Orthanc."""
    code = get_student_code()

    tag_text = (request.form.get('tag') or '').strip()
    keyword_text = (request.form.get('keyword') or '').strip()
    vr_text = (request.form.get('vr') or '').strip().upper()
    value_text = request.form.get('value')

    tag = _parse_dicom_tag(tag_text, keyword_text)
    if tag is None:
        return redirect(url_for('pacs_instance', instance_id=instance_id, series=(request.args.get('series') or '').strip(), msg="❌ Ungültiger Tag/Keyword."))

    # Load instance + resolve study for authorization (SuS filtering)
    try:
        instance = _orthanc_get_json(f'/instances/{instance_id}')
        parent_series_id = str(instance.get('ParentSeries') or '')
        if not parent_series_id:
            return redirect(url_for('pacs_instance', instance_id=instance_id, msg="❌ ParentSeries fehlt."))
        series = _orthanc_get_json(f'/series/{parent_series_id}', params={'expand': 'true'})
        parent_study_id = str(series.get('ParentStudy') or '')
        study = _orthanc_get_json(f'/studies/{parent_study_id}', params={'expand': 'true'})
    except Exception as e:
        return redirect(url_for('pacs_instance', instance_id=instance_id, msg=f"❌ Fehler beim Laden: {e}"))

    if not _study_visible_for_student(study, code):
        abort(404)

    try:
        dicom_bytes = _orthanc_get_bytes(f'/instances/{instance_id}/file')
        ds = pydicom.dcmread(BytesIO(dicom_bytes), force=True)

        if tag == Tag(0x0010, 0x0020) and code:
            # PatientID should keep SuS prefix so the instance stays visible.
            value_text = prefix_for_student(str(value_text or ''))

        if tag in ds:
            elem = ds[tag]
            vr = getattr(elem, 'VR', '') or ''
            ds[tag].value = _value_for_vr(vr, '' if value_text is None else str(value_text))
        else:
            vr = vr_text or (dictionary_VR(tag) or '')
            if not vr:
                raise ValueError('VR fehlt (z.B. LO, PN, SH, DA, TM, UI).')
            ds.add_new(tag, vr, _value_for_vr(vr, '' if value_text is None else str(value_text)))

        _ensure_new_sop_instance_uid(ds)

        out = BytesIO()
        ds.save_as(out, write_like_original=True)
        new_bytes = out.getvalue()

        created = _orthanc_post_dicom_instance(new_bytes)
        new_id = str(created.get('ID') or '')
        if not new_id:
            raise ValueError(f"Orthanc upload ok, aber keine ID erhalten: {created}")

        new_inst = _orthanc_get_json(f'/instances/{new_id}')
        new_series = str(new_inst.get('ParentSeries') or '')

        return redirect(url_for('pacs_instance', instance_id=new_id, series=new_series, msg=f"✅ Metadaten gespeichert: Neue Instanz erstellt ({new_id})."))
    except Exception as e:
        return redirect(url_for('pacs_instance', instance_id=instance_id, series=(request.args.get('series') or '').strip(), msg=f"❌ Metadaten-Änderung fehlgeschlagen: {e}"))


def _query_studies():
    studies = []
    try:
        ae = AE(ae_title=b'SIMULATOR')
        ae.add_requested_context(sop_class.StudyRootQueryRetrieveInformationModelFind)

        assoc = ae.associate(ORTHANC_HOST, ORTHANC_PORT)
        if assoc.is_established:
            ds = Dataset()
            ds.QueryRetrieveLevel = 'STUDY'
            ds.PatientName = ''
            code = get_student_code()
            ds.PatientID = f"{code}-*" if code else ''
            ds.StudyDate = ''
            ds.StudyInstanceUID = ''
            ds.AccessionNumber = ''
            ds.ModalitiesInStudy = ''

            responses = assoc.send_c_find(ds, query_model=sop_class.StudyRootQueryRetrieveInformationModelFind)
            for (status, dataset) in responses:
                if status.Status == 0xFF00 and dataset:
                    studies.append(dataset_to_dict(dataset))
            assoc.release()
    except Exception as e:
        print(f"Error querying PACS: {e}")

    return studies

@app.route('/viewer')
def viewer():
    studies = _query_studies()
    code = get_student_code()
    received = _received_images_for_code(code)
    return render_template(
        'viewer.html',
        studies=studies,
        received=received,
        received_studies=_received_study_groups(received),
        moved_studies=_viewer_moved_studies(),
        reports=_load_reports(code) if code else [],
        last_workstation_oru_hl7=session.get('last_workstation_oru_hl7'),
        workflow_current="6. DICOM C-FIND (Study): Studien suchen",
        workflow_next="7. DICOM C-MOVE: Retrieve anfordern",
    )


@app.route('/workstation/report', methods=['POST'])
def workstation_report():
    """Create a radiology report on the Workstation (as HL7 ORU) after images were received."""
    code = get_student_code()
    study_uid = (request.form.get('study_uid') or '').strip()
    report_text = (request.form.get('report_text') or '').strip()

    studies = _query_studies()
    received = _received_images_for_code(code)
    received_studies = _received_study_groups(received)

    if not study_uid:
        return render_template(
            'viewer.html',
            msg="❌ Bitte eine Studie auswählen.",
            studies=studies,
            received=received,
            received_studies=received_studies,
            moved_studies=_viewer_moved_studies(),
            reports=_load_reports(code) if code else [],
            last_workstation_oru_hl7=session.get('last_workstation_oru_hl7'),
            workflow_current="7. DICOM C-MOVE: Retrieve + Empfang",
            workflow_next="Optional: HL7 ORU^R01 – Befund (Workstation → RIS)",
        )

    match = None
    for img in received:
        if str((img or {}).get('StudyInstanceUID') or '').strip() == study_uid:
            match = img
            break

    if not match:
        return render_template(
            'viewer.html',
            msg="❌ Für diese Studie wurden noch keine Bilder empfangen (Cache leer). Erst C-MOVE anfordern und Empfang abwarten.",
            studies=studies,
            received=received,
            received_studies=received_studies,
            moved_studies=_viewer_moved_studies(),
            reports=_load_reports(code) if code else [],
            last_workstation_oru_hl7=session.get('last_workstation_oru_hl7'),
            workflow_current="7. DICOM C-MOVE: Retrieve + Empfang",
            workflow_next="Optional: HL7 ORU^R01 – Befund (Workstation → RIS)",
        )

    pid = str((match or {}).get('PatientID') or '').strip() or 'UNKNOWN'
    pname = str((match or {}).get('PatientName') or '').strip() or '^'

    raw_oru = build_hl7_oru_report(
        pid=pid,
        patient_name=pname,
        study_uid=study_uid,
        report_text=report_text,
    )

    session['last_workstation_oru_hl7'] = raw_oru
    session.modified = True

    if code:
        reports = _load_reports(code)
        reports.append({
            'created_at': datetime.datetime.now().isoformat(timespec='seconds'),
            'StudyInstanceUID': study_uid,
            'PatientID': pid,
            'PatientName': pname,
            'text': report_text,
            'hl7': raw_oru,
        })
        reports = reports[-50:]
        _save_reports(code, reports)

    return render_template(
        'viewer.html',
        msg="✅ Befund erstellt (HL7 ORU^R01) und an RIS gesendet (simuliert).",
        studies=studies,
        received=received,
        received_studies=received_studies,
        moved_studies=_viewer_moved_studies(),
        reports=_load_reports(code) if code else [],
        last_workstation_oru_hl7=raw_oru,
        workflow_current="Optional: HL7 ORU^R01 – Befund (Workstation → RIS)",
        workflow_next="6. DICOM C-FIND: nächste Studie suchen",
    )

@app.route('/retrieve', methods=['POST'])
def retrieve():
    study_uid = request.form.get('study_uid')
    code = get_student_code()
    
    # Trigger C-MOVE
    try:
        ae = AE(ae_title=b'SIMULATOR')
        ae.add_requested_context(sop_class.StudyRootQueryRetrieveInformationModelMove)
        
        assoc = ae.associate(ORTHANC_HOST, ORTHANC_PORT)
        if assoc.is_established:
            ds = Dataset()
            ds.QueryRetrieveLevel = 'STUDY'
            ds.StudyInstanceUID = study_uid
            
            # C-MOVE to 'SIMULATOR' (our AE Title)
            # Orthanc must know 'SIMULATOR' in DicomModalities config!
            responses = assoc.send_c_move(ds, b'SIMULATOR', query_model=sop_class.StudyRootQueryRetrieveInformationModelMove)
            for (status, identifier) in responses:
                 if status:
                     print(f"C-MOVE Status: 0x{status.Status:04x}")
            assoc.release()

            # Gate: once the user has triggered C-MOVE for this StudyInstanceUID,
            # allow opening the PACS viewer/metadata links from the Workstation list.
            _viewer_mark_study_moved(study_uid)
            
        studies = _query_studies()
        return render_template(
            'viewer.html',
            msg=(
                "✅ C-MOVE (Retrieve) angefordert: Das PACS wird die Instanzen nun aktiv per C-STORE "
                "an diese Workstation senden. Bitte kurz warten und dann den Cache unten prüfen (ggf. Refresh)."
            ),
            studies=studies,
            received=_received_images_for_code(code),
            received_studies=_received_study_groups(_received_images_for_code(code)),
            moved_studies=_viewer_moved_studies(),
            reports=_load_reports(code) if code else [],
            last_workstation_oru_hl7=session.get('last_workstation_oru_hl7'),
            workflow_current="7. DICOM C-MOVE: Retrieve anfordern",
            workflow_next="PACS → Workstation: Bilder kommen per DICOM C-STORE",
        )

    except Exception as e:
         studies = _query_studies()
         return render_template(
             'viewer.html',
             msg=f"❌ Fehler bei C-MOVE (Retrieve): {e}",
             studies=studies,
             received=_received_images_for_code(code),
             received_studies=_received_study_groups(_received_images_for_code(code)),
             moved_studies=_viewer_moved_studies(),
             reports=_load_reports(code) if code else [],
             last_workstation_oru_hl7=session.get('last_workstation_oru_hl7'),
             workflow_current="7. DICOM C-MOVE: Retrieve anfordern",
             workflow_next="PACS → Workstation: Bilder kommen per DICOM C-STORE",
         )

if __name__ == '__main__':
    # Flask debug reloader runs the module twice. Only start the DICOM listener once.
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or os.environ.get('FLASK_ENV') != 'development':
        ensure_store_scp_thread_started()

    # Add dummy data to received images for testing/demo
    if not RECEIVED_IMAGES:
         RECEIVED_IMAGES.append({
             'PatientName': 'TEST^DEMO',
             'PatientID': 'DEMO-0001',
             'StudyInstanceUID': '1.2.826.0.1.3680043.10.999.1',
             'Modality': 'CT',
             'Timestamp': '00:00:00',
         })

    if not os.path.exists(WORKLIST_DIR):
        os.makedirs(WORKLIST_DIR)
    # Important: Run threaded=True so the web server doesn't block the DICOM listener threads
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
