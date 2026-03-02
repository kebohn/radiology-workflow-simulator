from __future__ import annotations

from flask import render_template, request, session

try:
    from blueprint import bp
except ImportError:
    from .blueprint import bp

try:
    from simlib.hl7 import build_hl7_adt_a04
    from simlib.students import get_student_code, prefix_for_student
except ModuleNotFoundError:
    from .simlib.hl7 import build_hl7_adt_a04
    from .simlib.students import get_student_code, prefix_for_student

try:
    from deps import _load_patients, _load_reports, _reports_index_by_pid, _upsert_patient
except ImportError:
    from .deps import _load_patients, _load_reports, _reports_index_by_pid, _upsert_patient


@bp.route('/kis/register_patient', methods=['POST'])
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
