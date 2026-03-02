from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from simulator.app_factory import create_app


def test_welcome_accessible_without_student_code():
    app = create_app()
    app.testing = True

    client = app.test_client()
    res = client.get('/welcome')
    assert res.status_code == 200


def test_gate_redirects_to_welcome_without_student_code():
    app = create_app()
    app.testing = True

    client = app.test_client()
    res = client.get('/', follow_redirects=False)
    assert res.status_code in {301, 302, 303, 307, 308}
    assert res.headers['Location'].endswith('/welcome')


def test_index_accessible_with_student_code():
    app = create_app()
    app.testing = True

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['student_code'] = 'SUS-TEST'

    res = client.get('/')
    assert res.status_code == 200
    assert b'Radiologie Workflow Simulator' in res.data


def _run_python(code: str) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[2]
    return subprocess.run(
        [sys.executable, '-c', code],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )


def test_import_app_package_mode():
    res = _run_python(
        "import simulator.app as a; print(len(list(a.app.url_map.iter_rules())));",
    )
    assert res.returncode == 0, res.stderr
    assert int(res.stdout.strip().splitlines()[-1]) > 0


def test_import_app_script_mode():
    res = _run_python(
        "import sys; sys.path.insert(0, 'simulator'); import app as a; print(len(list(a.app.url_map.iter_rules())));",
    )
    assert res.returncode == 0, res.stderr
    assert int(res.stdout.strip().splitlines()[-1]) > 0
