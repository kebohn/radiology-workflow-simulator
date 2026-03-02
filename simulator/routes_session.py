from __future__ import annotations

from flask import redirect, render_template, request, session, url_for

try:
    from blueprint import bp
except ImportError:
    from .blueprint import bp

try:
    from simlib.students import get_student_code, student_code_allowed
    from simlib.util import normalize_student_code
except ModuleNotFoundError:
    from .simlib.students import get_student_code, student_code_allowed
    from .simlib.util import normalize_student_code


def _student_code_allowed(code: str) -> bool:
    return student_code_allowed(code)


@bp.route('/welcome', methods=['GET'])
def welcome():
    code = get_student_code()
    if code:
        return redirect(url_for('main.index'))
    return render_template('welcome.html')


@bp.route('/set_student', methods=['POST'])
def set_student():
    code = normalize_student_code(request.form.get('student_code'))
    if not code:
        session.pop('student_code', None)
        return redirect(url_for('main.welcome'))
    if not _student_code_allowed(code):
        return render_template('welcome.html', msg="❌ Ungültiger SuS-Code. Bitte einen der vorgegebenen Codes verwenden.")
    session['student_code'] = code
    return redirect(url_for('main.index'))


@bp.route('/clear_student', methods=['POST'])
def clear_student():
    session.pop('student_code', None)
    return redirect(url_for('main.index'))


@bp.route('/join/<code>', methods=['GET'])
def join(code: str):
    cc = normalize_student_code(code)
    if not cc or not _student_code_allowed(cc):
        return render_template('welcome.html', msg="❌ Ungültiger oder nicht freigeschalteter SuS-Code.")
    session['student_code'] = cc
    return redirect(url_for('main.index'))
