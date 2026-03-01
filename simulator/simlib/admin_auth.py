import hmac
import os

import bcrypt
from flask import render_template, session


def admin_user() -> str:
    return (os.environ.get('ADMIN_USER') or 'admin').strip() or 'admin'


def admin_passhash() -> str:
    # Prefer dedicated admin passhash; fallback to Orthanc proxy hash so one secret can be used.
    return (
        (os.environ.get('ADMIN_PASSHASH') or '').strip()
        or (os.environ.get('ORTHANC_PROXY_PASSHASH') or '').strip()
    )


def admin_password() -> str:
    # Legacy plaintext fallback; prefer admin_passhash().
    return (os.environ.get('ADMIN_PASSWORD') or '').strip()


def admin_enabled() -> bool:
    return bool(admin_passhash() or admin_password())


def is_admin() -> bool:
    return bool(session.get('is_admin'))


def require_admin():
    if not admin_enabled():
        return render_template('admin.html', admin_enabled=False, is_admin=False, msg='Admin ist nicht aktiviert (ADMIN_PASSHASH fehlt).')
    if not is_admin():
        return render_template('admin.html', admin_enabled=True, is_admin=False)
    return None


def check_login(username: str, password: str) -> bool:
    username = (username or '').strip()
    password = (password or '').strip()

    expected_user = admin_user()
    if not username or not hmac.compare_digest(username, expected_user):
        return False

    expected_hash = admin_passhash()
    if expected_hash:
        try:
            return bool(bcrypt.checkpw(password.encode('utf-8'), expected_hash.encode('utf-8')))
        except Exception:
            return False

    expected_plain = admin_password()
    if expected_plain and hmac.compare_digest(password, expected_plain):
        return True

    return False
