from __future__ import annotations

import datetime

from flask import render_template, request, session

try:
    from blueprint import bp
except ImportError:
    from .blueprint import bp

try:
    from simlib.config import ORTHANC_HOST, ORTHANC_PORT
    from simlib.hl7 import build_hl7_oru_report
    from simlib.students import get_student_code
except ModuleNotFoundError:
    from .simlib.config import ORTHANC_HOST, ORTHANC_PORT
    from .simlib.hl7 import build_hl7_oru_report
    from .simlib.students import get_student_code

from pynetdicom import AE, sop_class
from pydicom.dataset import Dataset

try:
    from deps import (
        _load_reports,
        _received_images_for_code,
        _received_study_groups,
        _save_reports,
        _update_patient_last_exam,
        _viewer_mark_study_moved,
        _viewer_moved_studies,
    )
except ImportError:
    from .deps import (
    _load_reports,
    _received_images_for_code,
    _received_study_groups,
    _save_reports,
    _update_patient_last_exam,
    _viewer_mark_study_moved,
    _viewer_moved_studies,
    )

try:
    from workstation_query import _query_studies
except ImportError:
    from .workstation_query import _query_studies


@bp.route('/viewer')
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


@bp.route('/workstation/report', methods=['POST'])
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
        _update_patient_last_exam(code, pid, status='Befundet')

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


@bp.route('/retrieve', methods=['POST'])
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
