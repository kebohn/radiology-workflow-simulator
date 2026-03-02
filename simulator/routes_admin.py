from __future__ import annotations

from flask import redirect, render_template, request, session, url_for

try:
    from blueprint import bp
except ImportError:
    from .blueprint import bp

try:
    from simlib import admin_auth, storage
except ModuleNotFoundError:
    from .simlib import admin_auth, storage


def _admin_enabled() -> bool:
    return admin_auth.admin_enabled()


def _is_admin() -> bool:
    return admin_auth.is_admin()


def _require_admin():
    return admin_auth.require_admin()


@bp.route('/admin', methods=['GET'])
def admin_home():
    if not _admin_enabled():
        return render_template('admin.html', admin_enabled=False, is_admin=False, msg="Admin ist nicht aktiviert (ADMIN_PASSHASH fehlt).")
    if not _is_admin():
        return render_template('admin.html', admin_enabled=True, is_admin=False)
    codes = storage.load_session_codes()
    return render_template('admin.html', admin_enabled=True, is_admin=True, codes=codes)


@bp.route('/admin/login', methods=['POST'])
def admin_login():
    if not _admin_enabled():
        return redirect(url_for('main.admin_home'))
    username = (request.form.get('username') or '').strip()
    provided = (request.form.get('password') or '').strip()

    if admin_auth.check_login(username, provided):
        session['is_admin'] = True
        return redirect(url_for('main.admin_home'))

    return render_template('admin.html', admin_enabled=True, is_admin=False, msg="❌ Falscher Benutzername oder Passwort.")


@bp.route('/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('main.admin_home'))


@bp.route('/admin/sessions/generate', methods=['POST'])
def admin_generate_sessions():
    guard = _require_admin()
    if guard is not None:
        return guard

    n_raw = request.form.get('count', '20')
    try:
        n = int(n_raw)
    except Exception:
        n = 20

    codes = storage.generate_session_codes(n)
    storage.save_session_codes(codes)
    return redirect(url_for('main.admin_home'))
