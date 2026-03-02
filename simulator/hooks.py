from __future__ import annotations

import os

from flask import redirect, request, url_for

try:
    from blueprint import bp
except ImportError:
    from .blueprint import bp

try:
    from simlib.students import get_student_code
except ModuleNotFoundError:
    from .simlib.students import get_student_code

try:
    from deps import _admin_user, _is_admin
except ImportError:
    from .deps import _admin_user, _is_admin


@bp.app_context_processor
def _inject_globals():
    orthanc_public_url = os.environ.get('ORTHANC_PUBLIC_URL', '').strip()
    orthanc_domain = (os.environ.get('ORTHANC_DOMAIN') or '').strip()

    # If Orthanc is exposed via reverse proxy, prefer HTTPS on its hostname.
    # Allow explicit ORTHANC_PUBLIC_URL to override.
    if not orthanc_public_url and orthanc_domain:
        d = orthanc_domain
        if d.startswith('http://'):
            d = d[len('http://'):]
        elif d.startswith('https://'):
            d = d[len('https://'):]
        d = d.strip().strip('/')
        if d:
            orthanc_public_url = f"https://{d}"

    # Convenience for local development: if the simulator is accessed via localhost,
    # show Orthanc links even when ORTHANC_PUBLIC_URL is not set.
    # On central servers (accessed via IP/domain), we keep this empty by default so
    # Orthanc is not accidentally linked publicly.
    if not orthanc_public_url:
        try:
            host = (request.host or '').split(':', 1)[0].lower()
        except Exception:
            host = ''
        if host in {'localhost', '127.0.0.1'}:
            orthanc_public_url = 'http://localhost:8042'

    is_admin = _is_admin()

    # Only show Orthanc link/buttons when admin is logged in.
    if not is_admin:
        orthanc_public_url = ''

    return {
        'student_code': get_student_code(),
        'orthanc_public_url': orthanc_public_url,
        'is_admin': is_admin,
        'admin_user': _admin_user(),
    }


@bp.before_app_request
def _require_student_code_gate():
    # Force an initial welcome page where SuS must enter a session key.
    # Allow admin and the entry points.
    allowed_endpoints = {
        'main.welcome',
        'main.set_student',
        'main.join',
        'main.admin_home',
        'main.admin_login',
        'main.admin_logout',
        'main.admin_generate_sessions',
        'static',
    }
    if request.endpoint in allowed_endpoints:
        return None
    if request.path.startswith('/admin'):
        return None
    if get_student_code():
        return None
    return redirect(url_for('main.welcome'))
