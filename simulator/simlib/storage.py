import datetime
import json
import os
import secrets
import threading
from typing import Optional

from .config import DATA_DIR, SESSIONS_FILE
from .util import normalize_student_code, safe_filename_component

_SESSIONS_LOCK = threading.Lock()
_PATIENTS_LOCK = threading.Lock()
_REPORTS_LOCK = threading.Lock()


def ensure_data_dir() -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        pass


def load_session_codes() -> list[str]:
    ensure_data_dir()
    with _SESSIONS_LOCK:
        try:
            if not os.path.exists(SESSIONS_FILE):
                return []
            with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            codes = payload.get('codes', []) if isinstance(payload, dict) else []
            if not isinstance(codes, list):
                return []
            cleaned: list[str] = []
            seen: set[str] = set()
            for c in codes:
                cc = normalize_student_code(str(c))
                if cc and cc not in seen:
                    seen.add(cc)
                    cleaned.append(cc)
            return cleaned
        except Exception:
            return []


def save_session_codes(codes: list[str]) -> None:
    ensure_data_dir()
    cleaned: list[str] = []
    seen: set[str] = set()
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


def generate_session_codes(n: int) -> list[str]:
    n = max(1, min(int(n or 20), 200))
    out: list[str] = []
    seen: set[str] = set()
    while len(out) < n:
        suffix = secrets.token_hex(3).upper()
        code = normalize_student_code(f"SUS-{suffix}")
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def maybe_auto_generate_sessions() -> None:
    """Optionally pre-populate sessions.json when AUTO_GENERATE_SESSIONS is set."""
    raw = (os.environ.get('AUTO_GENERATE_SESSIONS') or '').strip()
    if not raw:
        return
    try:
        n = int(raw)
    except Exception:
        n = 20
    if n <= 0:
        return
    existing = load_session_codes()
    if existing:
        return
    codes = generate_session_codes(n)
    save_session_codes(codes)


def patients_file_for_code(code: str) -> str:
    safe = safe_filename_component(code or '')
    if not safe or safe == 'item':
        safe = 'default'
    return os.path.join(DATA_DIR, f"patients_{safe}.json")


def load_patients(code: str) -> list[dict]:
    ensure_data_dir()
    path = patients_file_for_code(code)
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


def save_patients(code: str, patients: list[dict]) -> None:
    ensure_data_dir()
    path = patients_file_for_code(code)
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


def patient_exists(code: str, pid: str) -> bool:
    pid = (pid or '').strip()
    if not pid:
        return False
    for p in load_patients(code):
        if str((p or {}).get('pid') or '') == pid:
            return True
    return False


def upsert_patient(code: str, name: str, pid: str) -> None:
    name = (name or '').strip()
    pid = (pid or '').strip()
    if not name or not pid:
        return

    patients = load_patients(code)
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
    save_patients(code, patients)


def update_patient_last_exam(
    code: str,
    pid: str,
    *,
    accession_number: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
) -> None:
    """Update lightweight exam/order status for a patient (teaching aid)."""
    pid = (pid or '').strip()
    if not pid:
        return

    patients = load_patients(code)
    now = datetime.datetime.now().isoformat(timespec='seconds')
    changed = False
    for p in patients:
        if str((p or {}).get('pid') or '') != pid:
            continue
        ex = (p.get('last_exam') or {}) if isinstance(p, dict) else {}
        if accession_number:
            ex['acc'] = accession_number
        if description:
            ex['desc'] = description
        if status:
            ex['status'] = status
        ex['updated_at'] = now

        if status == 'Auftrag freigegeben':
            ex['ordered_at'] = now
            ex.pop('started_at', None)
            ex.pop('completed_at', None)
            ex.pop('reported_at', None)
        elif status == 'Untersuchung begonnen' and not ex.get('started_at'):
            ex['started_at'] = now
        elif status == 'Untersuchung abgeschlossen' and not ex.get('completed_at'):
            ex['completed_at'] = now
        elif status == 'Befundet' and not ex.get('reported_at'):
            ex['reported_at'] = now

        p['last_exam'] = ex
        p['updated_at'] = now
        changed = True
        break

    if changed:
        save_patients(code, patients)


def reports_file_for_code(code: str) -> str:
    safe = safe_filename_component(code or '')
    if not safe or safe == 'item':
        safe = 'default'
    return os.path.join(DATA_DIR, f"reports_{safe}.json")


def load_reports(code: str) -> list[dict]:
    ensure_data_dir()
    path = reports_file_for_code(code)
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


def save_reports(code: str, reports: list[dict]) -> None:
    ensure_data_dir()
    path = reports_file_for_code(code)
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


def reports_index_by_pid(code: str) -> dict[str, dict]:
    """Return a mapping pid -> {count, last_at} for quick RIS status display on dashboard."""
    out: dict[str, dict] = {}
    for r in load_reports(code):
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
