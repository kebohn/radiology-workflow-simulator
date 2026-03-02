from __future__ import annotations

from flask import render_template, session

try:
    from blueprint import bp
except ImportError:
    from .blueprint import bp

try:
    from simlib.config import ORTHANC_HOST, ORTHANC_PORT
    from simlib.students import get_student_code
except ModuleNotFoundError:
    from .simlib.config import ORTHANC_HOST, ORTHANC_PORT
    from .simlib.students import get_student_code

try:
    from deps import _load_patients, _load_reports, _reports_index_by_pid
except ImportError:
    from .deps import _load_patients, _load_reports, _reports_index_by_pid


@bp.route('/')
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


@bp.route('/echo', methods=['POST'])
def echo():
    code = get_student_code()
    try:
        from pynetdicom import AE, sop_class
        ae = AE(ae_title=b'SIMULATOR')
        ae.add_requested_context(sop_class.Verification)
        assoc = ae.associate(ORTHANC_HOST, ORTHANC_PORT)
        if assoc.is_established:
            assoc.send_c_echo()
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
