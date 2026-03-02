"""Flask entrypoint for the RIS/PACS simulator.

This file is intentionally small: it wires the app factory and keeps
Docker/script execution ("python app.py") working.
"""

from __future__ import annotations

import os

try:
    # Script mode (Dockerfile runs inside /simulator): `python app.py`
    from app_factory import create_app
    from simlib import dicom_receiver
    from simlib.config import WORKLIST_DIR
except ModuleNotFoundError:
    # Package mode: `python -m simulator.app` / WSGI import.
    from .app_factory import create_app
    from .simlib import dicom_receiver
    from .simlib.config import WORKLIST_DIR


app = create_app()


if __name__ == '__main__':
    # Flask debug reloader runs the module twice. Only start the DICOM listener once.
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or os.environ.get('FLASK_ENV') != 'development':
        dicom_receiver.ensure_store_scp_thread_started()

    dicom_receiver.seed_demo_received_images()

    if not os.path.exists(WORKLIST_DIR):
        os.makedirs(WORKLIST_DIR)
    # Important: Run threaded=True so the web server doesn't block the DICOM listener threads
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
