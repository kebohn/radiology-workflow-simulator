from __future__ import annotations

import random

from flask import jsonify, request, session

try:
    from blueprint import bp
except ImportError:
    from .blueprint import bp

try:
    from simlib.hl7 import build_hl7_qry_q02, hl7_msg_control_id, hl7_timestamp
    from simlib.students import get_student_code, prefix_for_student
except ModuleNotFoundError:
    from .simlib.hl7 import build_hl7_qry_q02, hl7_msg_control_id, hl7_timestamp
    from .simlib.students import get_student_code, prefix_for_student

try:
    from deps import _patient_exists
except ImportError:
    from .deps import _patient_exists


def _hl7_timestamp() -> str:
    return hl7_timestamp()


def _hl7_msg_control_id(prefix: str = 'MSG') -> str:
    return hl7_msg_control_id(prefix)


@bp.route('/query_lis', methods=['POST'])
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

    creatinine = round(base_val, 2)

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
