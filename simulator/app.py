from flask import Flask, render_template, request, make_response, jsonify, session, redirect, url_for
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

app = Flask(__name__)

# IMPORTANT (central server): Set a stable secret via env so sessions survive restarts.
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-insecure-change-me')

# Real CT studies can be large. If you hit HTTP 413 (Request Entity Too Large),
# increase this value.
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1 GiB

# --- LIS Simulation ---

STUDENT_CODE_RE = re.compile(r"[^A-Za-z0-9_-]")
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_.-]")

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


def _admin_password() -> str:
    return (os.environ.get('ADMIN_PASSWORD') or '').strip()


def _admin_enabled() -> bool:
    return bool(_admin_password())


def _is_admin() -> bool:
    return bool(session.get('is_admin'))


def _require_admin():
    if not _admin_enabled():
        return render_template('admin.html', admin_enabled=False, is_admin=False, msg="Admin ist nicht aktiviert (ADMIN_PASSWORD fehlt).")
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


def normalize_student_code(raw: Optional[str]) -> str:
    if not raw:
        return ""
    code = raw.strip()
    code = STUDENT_CODE_RE.sub("", code)
    code = code[:24]
    return code


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
    if value.startswith(code + "-"):
        return value
    return f"{code}-{value}"


def safe_filename_component(value: str) -> str:
    """Return a filesystem-safe component (no slashes), suitable for filenames."""
    v = (value or "").strip()
    v = v.replace("/", "-").replace("\\", "-")
    v = SAFE_FILENAME_RE.sub("_", v)
    v = v[:64]
    return v or "item"


@app.context_processor
def _inject_globals():
    return {
        'student_code': get_student_code(),
        'orthanc_public_url': os.environ.get('ORTHANC_PUBLIC_URL', '').strip(),
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
        return render_template('admin.html', admin_enabled=False, is_admin=False, msg="Admin ist nicht aktiviert (ADMIN_PASSWORD fehlt).")
    if not _is_admin():
        return render_template('admin.html', admin_enabled=True, is_admin=False)
    codes = _load_session_codes()
    return render_template('admin.html', admin_enabled=True, is_admin=True, codes=codes)


@app.route('/admin/login', methods=['POST'])
def admin_login():
    if not _admin_enabled():
        return redirect(url_for('admin_home'))
    provided = (request.form.get('password') or '').strip()
    expected = _admin_password()
    if expected and hmac.compare_digest(provided, expected):
        session['is_admin'] = True
        return redirect(url_for('admin_home'))
    return render_template('admin.html', admin_enabled=True, is_admin=False, msg="❌ Falsches Admin-Passwort.")


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
        
    return jsonify({
        'structure': 'HL7 ORU^R01 (Observation Result)',
        'value': creatinine,
        'unit': 'mg/dL',
        'status': status,
        'color': color,
        'raw_hl7': f"MSH|^~\\&|LIS|LAB|KAS|RADIO|{datetime.datetime.now().strftime('%Y%m%d')}|ORU^R01|MSG{random.randint(100,999)}|P|2.3\rPID|||{pid}||^\rOBR|1|||KREA^Creatinine\rOBX|1|NM|KREA||{creatinine}|mg/dL|0.6-1.2|{status}|||F"
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

    ae = AE(ae_title=b'SIMULATOR')
    for cx in StoragePresentationContexts:
        ae.add_requested_context(cx.abstract_syntax)

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
            status = assoc.send_c_store(ds)
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
    return render_template(
        'index.html',
        workflow_current="KIS: Patient aufnehmen (HL7 ADT)",
        workflow_next="LIS: Kreatinin prüfen (HL7 ORU)",
    )

@app.route('/echo', methods=['POST'])
def echo():
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
                msg=f"✅ DICOM C-ECHO erfolgreich! Das PACS ist unter {ORTHANC_HOST}:{ORTHANC_PORT} erreichbar.",
                workflow_current="KIS: Patient aufnehmen (HL7 ADT)",
                workflow_next="LIS: Kreatinin prüfen (HL7 ORU)",
            )
        else:
            return render_template(
                'index.html',
                msg="❌ DICOM Association gescheitert. Ist der Orthanc-Container gestartet?",
                workflow_current="KIS: Patient aufnehmen (HL7 ADT)",
                workflow_next="LIS: Kreatinin prüfen (HL7 ORU)",
            )
    except Exception as e:
        return render_template(
            'index.html',
            msg=f"❌ Fehler bei C-ECHO: {str(e)}",
            workflow_current="KIS: Patient aufnehmen (HL7 ADT)",
            workflow_next="LIS: Kreatinin prüfen (HL7 ORU)",
        )

@app.route('/create_order', methods=['POST'])
def create_order():
    name = request.form.get('name')
    pid = prefix_for_student(request.form.get('pid'))
    acc = prefix_for_student(request.form.get('acc'))
    desc = request.form.get('desc')
    
    create_dicom_worklist_file(name, pid, acc, desc)
    code = get_student_code()
    ns = f" (SuS-Code: {code})" if code else ""
    msg = f"✅ Auftrag erfolgreich! HL7 ORM wurde simuliert und ein Worklist-Eintrag für '{name}' erstellt.{ns}"
    return render_template(
        'index.html',
        msg=msg,
        workflow_current="RIS: Auftrag freigeben (HL7 ORM)",
        workflow_next="MWL: Worklist abrufen (DICOM C-FIND)",
    )

@app.route('/modality')
def modality():
    items = perform_c_find_mwl()
    return render_template('modality.html', items=items, workflow_current="Worklist abrufen (DICOM C-FIND)", workflow_next="Bilder senden (DICOM C-STORE)")

@app.route('/scan', methods=['POST'])
def scan():
    name = request.form.get('name')
    pid = request.form.get('pid')
    acc = request.form.get('acc')

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
    return render_template('modality.html', items=items, msg=msg, workflow_current="Bilder senden (DICOM C-STORE)", workflow_next="Studien suchen (DICOM C-FIND)")


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
    if code:
        received = [r for r in RECEIVED_IMAGES if str(r.get('PatientID', '')).startswith(code + "-")]
    else:
        received = RECEIVED_IMAGES
    return render_template('viewer.html', studies=studies, received=received, workflow_current="Studien suchen (DICOM C-FIND)", workflow_next="Retrieve (DICOM C-MOVE)")

@app.route('/retrieve', methods=['POST'])
def retrieve():
    study_uid = request.form.get('study_uid')
    
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
            
        studies = _query_studies()
        return render_template('viewer.html', msg="C-MOVE Anforderung gesendet! Bitte warten Sie auf eintreffende Bilder...", studies=studies, received=RECEIVED_IMAGES, workflow_current="Retrieve (DICOM C-MOVE)", workflow_next="Bilder empfangen (DICOM C-STORE)")

    except Exception as e:
         studies = _query_studies()
         return render_template('viewer.html', msg=f"Fehler bei C-MOVE: {e}", studies=studies, received=RECEIVED_IMAGES, workflow_current="Retrieve (DICOM C-MOVE)", workflow_next="Bilder empfangen (DICOM C-STORE)")

if __name__ == '__main__':
    # Flask debug reloader runs the module twice. Only start the DICOM listener once.
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or os.environ.get('FLASK_ENV') != 'development':
        ensure_store_scp_thread_started()

    # Add dummy data to received images for testing/demo
    if not RECEIVED_IMAGES:
         RECEIVED_IMAGES.append({'PatientName': 'TEST^DEMO', 'Study': 'Local Cache', 'Modality':'CT', 'Timestamp': '00:00:00'})

    if not os.path.exists(WORKLIST_DIR):
        os.makedirs(WORKLIST_DIR)
    # Important: Run threaded=True so the web server doesn't block the DICOM listener threads
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
