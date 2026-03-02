from __future__ import annotations

import shutil

from flask import render_template, request, session

try:
    from blueprint import bp
except ImportError:
    from .blueprint import bp

try:
    from simlib.students import get_student_code, prefix_for_student
except ModuleNotFoundError:
    from .simlib.students import get_student_code, prefix_for_student

try:
    from cstore import _collect_dicom_file_paths_from_uploads, send_c_store, send_c_store_uploaded_files
except ImportError:
    from .cstore import _collect_dicom_file_paths_from_uploads, send_c_store, send_c_store_uploaded_files

try:
    from deps import (
        _load_patients,
        _load_reports,
        _patient_exists,
        _reports_index_by_pid,
        _update_patient_last_exam,
    )
except ImportError:
    from .deps import (
    _load_patients,
    _load_reports,
    _patient_exists,
    _reports_index_by_pid,
    _update_patient_last_exam,
    )

try:
    from mwl import create_dicom_worklist_file, perform_c_find_mwl
except ImportError:
    from .mwl import create_dicom_worklist_file, perform_c_find_mwl


@bp.route('/create_order', methods=['POST'])
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
    _update_patient_last_exam(
        code,
        pid,
        accession_number=acc,
        description=desc,
        status='Auftrag freigegeben',
    )
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


@bp.route('/modality')
def modality():
    items = perform_c_find_mwl()
    return render_template(
        'modality.html',
        items=items,
        workflow_current="4. DICOM C-FIND (MWL): Worklist abrufen",
        workflow_next="5. DICOM C-STORE: Bilder senden → PACS",
    )


@bp.route('/scan', methods=['POST'])
def scan():
    name = request.form.get('name')
    pid = prefix_for_student(request.form.get('pid'))
    acc = prefix_for_student(request.form.get('acc'))

    uploads = request.files.getlist('dicom_files') if request.files else []
    retag = request.form.get('retag') == 'on'

    code = get_student_code()

    _update_patient_last_exam(code, pid, accession_number=acc, status='Untersuchung begonnen')

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

        if summary.get('ok', 0) > 0:
            _update_patient_last_exam(code, pid, accession_number=acc, status='Untersuchung abgeschlossen')
    else:
        status = send_c_store(name, pid, acc)
        msg = f"☢️ Dummy-Scan für {name}. (Hinweis: Für echte Daten bitte DICOM-Dateien hochladen.) Status: {status}."

        if status and getattr(status, 'Status', None) == 0x0000:
            _update_patient_last_exam(code, pid, accession_number=acc, status='Untersuchung abgeschlossen')

    items = perform_c_find_mwl()
    return render_template(
        'modality.html',
        items=items,
        msg=msg,
        workflow_current="5. DICOM C-STORE: Bilder senden → PACS",
        workflow_next="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studien suchen)",
    )
