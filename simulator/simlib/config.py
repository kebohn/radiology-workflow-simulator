import os
import re

STUDENT_CODE_RE = re.compile(r"[^A-Za-z0-9_-]")
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_.-]")

DATA_DIR = os.environ.get('DATA_DIR', '/app/data')
WORKLIST_DIR = os.environ.get('WORKLIST_DIR', '/app/worklists')

SESSIONS_FILE = os.path.join(DATA_DIR, 'sessions.json')

ORTHANC_HOST = os.environ.get('ORTHANC_DICOM_HOST', 'orthanc')
ORTHANC_PORT = int(os.environ.get('ORTHANC_DICOM_PORT', 4242))
ORTHANC_HTTP_URL = (
    os.environ.get('ORTHANC_URL')
    or os.environ.get('ORTHANC_url')
    or 'http://orthanc:8042'
).rstrip('/')

STORE_SCP_PORT = int(os.environ.get('STORE_SCP_PORT', 11112))

FLASK_SECRET_KEY = os.environ.get('FLASK_SECRET_KEY') or 'dev-insecure-change-me'

# Real CT studies can be large. If you hit HTTP 413 (Request Entity Too Large),
# increase this value.
MAX_CONTENT_LENGTH = 1024 * 1024 * 1024  # 1 GiB
