import datetime
import random


def hl7_timestamp() -> str:
    return datetime.datetime.now().strftime('%Y%m%d%H%M%S')


def hl7_msg_control_id(prefix: str = 'MSG') -> str:
    return f"{prefix}{random.randint(100000, 999999)}"


def hl7_sanitize_field(text: str) -> str:
    """Keep HL7 fields single-line and avoid separator characters.

    This is intentionally minimal for demo purposes.
    """
    s = '' if text is None else str(text)
    s = s.replace('\r', ' ').replace('\n', ' ').strip()
    s = s.replace('|', '/').replace('~', '-').replace('\\', '/')
    return s


def build_hl7_oru_report(*, pid: str, patient_name: str, study_uid: str, report_text: str) -> str:
    """Return a simple HL7 v2.x ORU^R01 message (Workstation -> RIS) representing a report."""
    ts = hl7_timestamp()
    msg_id = hl7_msg_control_id('ORU')
    pid = (pid or 'UNKNOWN').strip()
    patient_name = hl7_sanitize_field(patient_name or '^') or '^'
    study_uid = hl7_sanitize_field(study_uid or '')
    report_text = hl7_sanitize_field(report_text or '')
    if not report_text:
        report_text = 'Kein Text.'

    return (
        f"MSH|^~\\&|WORKSTATION|RAD|RIS|RADIO|{ts}||ORU^R01|{msg_id}|P|2.3\r"
        f"PID|1||{pid}||{patient_name}\r"
        f"OBR|1|||RPT^Radiology Report\r"
        f"OBX|1|TX|RPT||{report_text}|||||F\r"
        f"OBX|2|ST|STUDYUID||{study_uid}|||||F"
    )


def build_hl7_adt_a04(pid: str, name: str) -> str:
    """Return a simple HL7 v2.x ADT^A04 registration message as raw segments."""
    ts = hl7_timestamp()
    msg_id = hl7_msg_control_id('ADT')
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
    ts = hl7_timestamp()
    msg_id = hl7_msg_control_id('QRY')
    pid = (pid or 'UNKNOWN').strip()
    return (
        f"MSH|^~\\&|RIS|RADIO|LIS|LAB|{ts}||QRY^Q02|{msg_id}|P|2.3\r"
        f"PID|1||{pid}||^\r"
        f"QRD|{ts}|R|I|{msg_id}|||1^RD|{pid}|RES\r"
        f"QRF|MON|||||RCT^Creatinine\r"
    )
