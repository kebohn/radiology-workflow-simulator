from __future__ import annotations

from io import BytesIO
from typing import Optional

import pydicom
from flask import abort, make_response, redirect, render_template, request, url_for
from pydicom.datadict import dictionary_VR
from pydicom.tag import Tag
from pydicom.uid import generate_uid

try:
    from blueprint import bp
except ImportError:
    from .blueprint import bp

try:
    from simlib.students import get_student_code, prefix_for_student
except ModuleNotFoundError:
    from .simlib.students import get_student_code, prefix_for_student

try:
    from dicom_helpers import (
        _dicom_tags_for_table,
        _ensure_new_sop_instance_uid,
        _parse_dicom_tag,
        _render_dicom_png,
        _value_for_vr,
    )
except ImportError:
    from .dicom_helpers import (
    _dicom_tags_for_table,
    _ensure_new_sop_instance_uid,
    _parse_dicom_tag,
    _render_dicom_png,
    _value_for_vr,
    )

try:
    from orthanc_helpers import (
        _orthanc_get_bytes,
        _orthanc_get_json,
        _orthanc_post_dicom_instance,
        _orthanc_post_json,
        _study_visible_for_student,
    )
except ImportError:
    from .orthanc_helpers import (
    _orthanc_get_bytes,
    _orthanc_get_json,
    _orthanc_post_dicom_instance,
    _orthanc_post_json,
    _study_visible_for_student,
    )


@bp.route('/pacs')
def pacs_home():
    code = get_student_code()
    accession_filter = (request.args.get('acc') or '').strip()
    try:
        studies = _orthanc_get_json('/studies', params={'expand': 'true'})
    except Exception as e:
        return render_template(
            'pacs.html',
            studies=[],
            msg=f"❌ Orthanc nicht erreichbar: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studien suchen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    visible = [s for s in (studies or []) if _study_visible_for_student(s, code)]
    if accession_filter:
        visible = [
            s for s in visible
            if str((s.get('MainDicomTags') or {}).get('AccessionNumber') or '') == accession_filter
        ]

    # Sort: newest first when StudyDate is present
    def _sort_key(st):
        tags = (st.get('MainDicomTags') or {})
        return (tags.get('StudyDate') or '', tags.get('StudyTime') or '')

    visible.sort(key=_sort_key, reverse=True)

    return render_template(
        'pacs.html',
        studies=visible,
        acc=accession_filter,
        workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studien suchen)",
        workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
    )


@bp.route('/pacs/studies/<study_id>')
def pacs_study(study_id: str):
    code = get_student_code()
    msg = (request.args.get('msg') or '').strip() or None
    try:
        study = _orthanc_get_json(f'/studies/{study_id}', params={'expand': 'true'})
    except Exception as e:
        return render_template(
            'pacs_study.html',
            study=None,
            msg=f"❌ Fehler beim Laden der Studie: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studie anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    if not _study_visible_for_student(study, code):
        abort(404)

    series_ids = [str(x) for x in (study.get('Series') or [])]
    series = []
    for sid in series_ids:
        try:
            series.append(_orthanc_get_json(f'/series/{sid}', params={'expand': 'true'}))
        except Exception:
            continue

    return render_template(
        'pacs_study.html',
        study=study,
        series=series,
        msg=msg,
        workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studie anzeigen)",
        workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
    )


@bp.route('/pacs/series/<series_id>')
def pacs_series(series_id: str):
    code = get_student_code()
    msg = (request.args.get('msg') or '').strip() or None
    try:
        series = _orthanc_get_json(f'/series/{series_id}', params={'expand': 'true'})
    except Exception as e:
        return render_template(
            'pacs_series.html',
            study=None,
            series=None,
            instances=[],
            msg=f"❌ Fehler beim Laden der Serie: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Serie anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    parent_study_id = str(series.get('ParentStudy') or '')
    if not parent_study_id:
        return render_template(
            'pacs_series.html',
            study=None,
            series=series,
            instances=[],
            msg="❌ ParentStudy fehlt.",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Serie anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    try:
        study = _orthanc_get_json(f'/studies/{parent_study_id}', params={'expand': 'true'})
    except Exception as e:
        return render_template(
            'pacs_series.html',
            study=None,
            series=series,
            instances=[],
            msg=f"❌ Fehler beim Laden der Studie: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Serie anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    if not _study_visible_for_student(study, code):
        abort(404)

    instance_ids = [str(x) for x in (series.get('Instances') or [])]
    instances = []
    for iid in instance_ids[:200]:
        try:
            instances.append(_orthanc_get_json(f'/instances/{iid}'))
        except Exception:
            instances.append({'ID': iid, 'MainDicomTags': {}})

    return render_template(
        'pacs_series.html',
        study=study,
        series=series,
        instances=instances,
        msg=msg,
        workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Serie anzeigen)",
        workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
    )


@bp.route('/pacs/series/<series_id>/derive_seg', methods=['POST'])
def pacs_series_derive_seg(series_id: str):
    code = get_student_code()

    try:
        series = _orthanc_get_json(f'/series/{series_id}', params={'expand': 'true'})
    except Exception as e:
        return redirect(url_for('main.pacs_series', series_id=series_id, msg=f"❌ Serie konnte nicht geladen werden: {e}"))

    parent_study_id = str(series.get('ParentStudy') or '').strip()
    if not parent_study_id:
        return redirect(url_for('main.pacs_series', series_id=series_id, msg="❌ ParentStudy fehlt."))

    try:
        study = _orthanc_get_json(f'/studies/{parent_study_id}', params={'expand': 'true'})
    except Exception as e:
        return redirect(url_for('main.pacs_series', series_id=series_id, msg=f"❌ Studie konnte nicht geladen werden: {e}"))

    if not _study_visible_for_student(study, code):
        abort(404)

    instance_ids = [str(x) for x in (series.get('Instances') or [])]
    if not instance_ids:
        return redirect(url_for('main.pacs_series', series_id=series_id, msg="❌ Keine Instanzen in dieser Serie."))

    # Keep the demo reasonably fast.
    instance_ids = instance_ids[:30]

    new_series_uid = generate_uid()
    uploaded_instance_ids: list[str] = []
    new_series_id: Optional[str] = None

    try:
        for iid in instance_ids:
            dicom_bytes = _orthanc_get_bytes(f'/instances/{iid}/file')
            ds = pydicom.dcmread(BytesIO(dicom_bytes), force=True)

            # Simulate a derived "segmentation" series (not a real DICOM-SEG IOD).
            try:
                ds.SeriesInstanceUID = new_series_uid
            except Exception:
                pass
            try:
                ds.SeriesDescription = 'Segmentation (simulated)'
            except Exception:
                pass
            try:
                ds.ImageType = ['DERIVED', 'SECONDARY']
            except Exception:
                pass
            try:
                ds.DerivationDescription = 'Simulated derived series (teaching demo)'
            except Exception:
                pass

            # Bump series number so it shows up separately in many viewers.
            try:
                base = int(getattr(ds, 'SeriesNumber', 0) or 0)
                ds.SeriesNumber = base + 500
            except Exception:
                try:
                    ds.SeriesNumber = 500
                except Exception:
                    pass

            _ensure_new_sop_instance_uid(ds)
            try:
                if hasattr(ds, 'file_meta') and ds.file_meta is not None:
                    try:
                        ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
                    except Exception:
                        pass
            except Exception:
                pass

            buf = BytesIO()
            pydicom.dcmwrite(buf, ds, write_like_original=False)
            resp = _orthanc_post_dicom_instance(buf.getvalue())
            new_instance_id = str(resp.get('ID') or '').strip()
            if new_instance_id:
                uploaded_instance_ids.append(new_instance_id)

                if not new_series_id:
                    try:
                        inst_meta = _orthanc_get_json(f'/instances/{new_instance_id}')
                        new_series_id = str(inst_meta.get('ParentSeries') or '').strip() or None
                    except Exception:
                        new_series_id = None

        if not uploaded_instance_ids:
            return redirect(url_for('main.pacs_series', series_id=series_id, msg="❌ Upload fehlgeschlagen (keine Instanzen erzeugt)."))

        target = new_series_id or series_id
        return redirect(url_for(
            'main.pacs_series',
            series_id=target,
            msg=f"✅ Derived Series erzeugt: 'Segmentation (simulated)' ({len(uploaded_instance_ids)} Instanzen).",
        ))
    except Exception as e:
        return redirect(url_for('main.pacs_series', series_id=series_id, msg=f"❌ Derived Series fehlgeschlagen: {e}"))


@bp.route('/pacs/instances/<instance_id>')
def pacs_instance(instance_id: str):
    code = get_student_code()
    msg = (request.args.get('msg') or '').strip() or None
    series_id = (request.args.get('series') or '').strip()
    index_raw = (request.args.get('i') or '0').strip()
    try:
        index = max(0, int(index_raw))
    except Exception:
        index = 0

    try:
        instance = _orthanc_get_json(f'/instances/{instance_id}')
    except Exception as e:
        return render_template(
            'pacs_instance.html',
            study=None,
            series=None,
            instance=None,
            tags=[],
            instance_ids=[],
            i=0,
            msg=f"❌ Fehler beim Laden der Instanz: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Instanz anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    parent_series_id = str(instance.get('ParentSeries') or '')
    if not series_id:
        series_id = parent_series_id
    if not series_id:
        return render_template(
            'pacs_instance.html',
            study=None,
            series=None,
            instance=instance,
            tags=[],
            instance_ids=[],
            i=0,
            msg="❌ ParentSeries fehlt.",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Instanz anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    try:
        series = _orthanc_get_json(f'/series/{series_id}', params={'expand': 'true'})
    except Exception as e:
        return render_template(
            'pacs_instance.html',
            study=None,
            series=None,
            instance=instance,
            tags=[],
            instance_ids=[],
            i=0,
            msg=f"❌ Fehler beim Laden der Serie: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Instanz anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    parent_study_id = str(series.get('ParentStudy') or '')
    try:
        study = _orthanc_get_json(f'/studies/{parent_study_id}', params={'expand': 'true'})
    except Exception as e:
        return render_template(
            'pacs_instance.html',
            study=None,
            series=series,
            instance=instance,
            tags=[],
            instance_ids=[],
            i=0,
            msg=f"❌ Fehler beim Laden der Studie: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Instanz anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    if not _study_visible_for_student(study, code):
        abort(404)

    instance_ids = [str(x) for x in (series.get('Instances') or [])]
    if instance_id in instance_ids:
        index = instance_ids.index(instance_id)
    if index >= len(instance_ids):
        index = max(0, len(instance_ids) - 1)

    tags = []
    try:
        dicom_bytes = _orthanc_get_bytes(f'/instances/{instance_id}/file')
        tags = _dicom_tags_for_table(dicom_bytes)
    except Exception as e:
        tags = []
        msg = f"⚠️ Metadaten konnten nicht gelesen werden: {e}"
        return render_template(
            'pacs_instance.html',
            study=study,
            series=series,
            instance=instance,
            tags=tags,
            instance_ids=instance_ids,
            i=index,
            msg=msg,
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Instanz anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    return render_template(
        'pacs_instance.html',
        study=study,
        series=series,
        instance=instance,
        tags=tags,
        instance_ids=instance_ids,
        i=index,
        msg=msg,
        workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Instanz anzeigen)",
        workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
    )


@bp.route('/pacs/open_by_uid')
def pacs_open_by_uid():
    code = get_student_code()
    study_uid = (request.args.get('study_uid') or '').strip()
    if not study_uid:
        return redirect(url_for('main.pacs_home'))

    try:
        result = _orthanc_post_json('/tools/find', {
            'Level': 'Study',
            'Query': {
                'StudyInstanceUID': study_uid,
            },
            'Limit': 20,
        })
    except Exception as e:
        return render_template(
            'pacs.html',
            studies=[],
            msg=f"❌ Orthanc Suche fehlgeschlagen: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studien suchen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    study_ids = []
    if isinstance(result, list):
        study_ids = [str(x) for x in result]
    elif isinstance(result, dict) and isinstance(result.get('ID'), str):
        study_ids = [result['ID']]
    elif isinstance(result, dict) and isinstance(result.get('Results'), list):
        study_ids = [str(x) for x in result.get('Results')]

    for sid in study_ids:
        try:
            st = _orthanc_get_json(f'/studies/{sid}', params={'expand': 'true'})
            if _study_visible_for_student(st, code):
                return redirect(url_for('main.pacs_study', study_id=sid))
        except Exception:
            continue

    return render_template(
        'pacs.html',
        studies=[],
        msg="⚠️ Studie nicht gefunden oder nicht sichtbar für diesen SuS-Code.",
        workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studien suchen)",
        workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
    )


@bp.route('/pacs/open_first_instance_by_uid')
def pacs_open_first_instance_by_uid():
    """Convenience for Workstation: jump directly to first instance viewer for a StudyInstanceUID."""
    code = get_student_code()
    study_uid = (request.args.get('study_uid') or '').strip()
    if not study_uid:
        return redirect(url_for('main.pacs_home'))

    try:
        result = _orthanc_post_json('/tools/find', {
            'Level': 'Study',
            'Query': {
                'StudyInstanceUID': study_uid,
            },
            'Limit': 20,
        })
    except Exception as e:
        return render_template(
            'pacs.html',
            studies=[],
            msg=f"❌ Orthanc Suche fehlgeschlagen: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studien suchen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    study_ids = []
    if isinstance(result, list):
        study_ids = [str(x) for x in result]
    elif isinstance(result, dict) and isinstance(result.get('ID'), str):
        study_ids = [result['ID']]
    elif isinstance(result, dict) and isinstance(result.get('Results'), list):
        study_ids = [str(x) for x in result.get('Results')]

    for sid in study_ids:
        try:
            st = _orthanc_get_json(f'/studies/{sid}', params={'expand': 'true'})
            if not _study_visible_for_student(st, code):
                continue
            series_list = st.get('Series') or []
            if not series_list:
                return redirect(url_for('main.pacs_study', study_id=sid))
            first_series_id = str(series_list[0])
            se = _orthanc_get_json(f'/series/{first_series_id}', params={'expand': 'true'})
            insts = se.get('Instances') or []
            if not insts:
                return redirect(url_for('main.pacs_series', series_id=first_series_id))
            return redirect(url_for('main.pacs_instance', instance_id=str(insts[0]), series=first_series_id))
        except Exception:
            continue

    return render_template(
        'pacs.html',
        studies=[],
        msg="⚠️ Studie nicht gefunden oder nicht sichtbar für diesen SuS-Code.",
        workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studien suchen)",
        workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
    )


@bp.route('/pacs/studies/<study_id>/viewer')
def pacs_viewer(study_id: str):
    code = get_student_code()
    try:
        study = _orthanc_get_json(f'/studies/{study_id}', params={'expand': 'true'})
    except Exception as e:
        return render_template(
            'pacs.html',
            studies=[],
            msg=f"❌ Fehler beim Laden der Studie: {e}",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studien suchen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    if not _study_visible_for_student(study, code):
        abort(404)

    series_list = study.get('Series') or []
    if not series_list:
        return render_template(
            'pacs_study.html',
            study=study,
            series=[],
            msg="⚠️ Keine Serien in dieser Studie.",
            workflow_current="6. DICOM C-FIND (Study): Workstation ↔ PACS (Studie anzeigen)",
            workflow_next="7. DICOM C-MOVE: Retrieve (Workstation)",
        )

    first_series_id = str(series_list[0])
    try:
        series = _orthanc_get_json(f'/series/{first_series_id}', params={'expand': 'true'})
    except Exception:
        return redirect(url_for('main.pacs_series', series_id=first_series_id))

    instance_ids = [str(x) for x in (series.get('Instances') or [])]
    if not instance_ids:
        return redirect(url_for('main.pacs_series', series_id=first_series_id))

    return redirect(url_for('main.pacs_instance', instance_id=instance_ids[0], series=first_series_id))


@bp.route('/pacs/instances/<instance_id>/preview.png')
def pacs_instance_preview(instance_id: str):
    # Best-effort: render as PNG. If it fails, return a readable error.
    try:
        dicom_bytes = _orthanc_get_bytes(f'/instances/{instance_id}/file')
        png = _render_dicom_png(dicom_bytes)
        resp = make_response(png)
        resp.headers['Content-Type'] = 'image/png'
        resp.headers['Cache-Control'] = 'no-store'
        return resp
    except Exception as e:
        return make_response(
            f"Cannot render this DICOM instance as PNG ({e}). If this is a compressed DICOM (e.g. JPEG2000), upload an uncompressed export.",
            415,
        )


@bp.route('/pacs/instances/<instance_id>/edit_metadata', methods=['POST'])
def pacs_instance_edit_metadata(instance_id: str):
    """Edit or add a DICOM tag on an instance by re-uploading a modified copy to Orthanc."""
    code = get_student_code()

    tag_text = (request.form.get('tag') or '').strip()
    keyword_text = (request.form.get('keyword') or '').strip()
    vr_text = (request.form.get('vr') or '').strip().upper()
    value_text = request.form.get('value')

    tag = _parse_dicom_tag(tag_text, keyword_text)
    if tag is None:
        return redirect(url_for('main.pacs_instance', instance_id=instance_id, series=(request.args.get('series') or '').strip(), msg="❌ Ungültiger Tag/Keyword."))

    # Load instance + resolve study for authorization (SuS filtering)
    try:
        instance = _orthanc_get_json(f'/instances/{instance_id}')
        parent_series_id = str(instance.get('ParentSeries') or '')
        if not parent_series_id:
            return redirect(url_for('main.pacs_instance', instance_id=instance_id, msg="❌ ParentSeries fehlt."))
        series = _orthanc_get_json(f'/series/{parent_series_id}', params={'expand': 'true'})
        parent_study_id = str(series.get('ParentStudy') or '')
        study = _orthanc_get_json(f'/studies/{parent_study_id}', params={'expand': 'true'})
    except Exception as e:
        return redirect(url_for('main.pacs_instance', instance_id=instance_id, msg=f"❌ Fehler beim Laden: {e}"))

    if not _study_visible_for_student(study, code):
        abort(404)

    try:
        dicom_bytes = _orthanc_get_bytes(f'/instances/{instance_id}/file')
        ds = pydicom.dcmread(BytesIO(dicom_bytes), force=True)

        if tag == Tag(0x0010, 0x0020) and code:
            # PatientID should keep SuS prefix so the instance stays visible.
            value_text = prefix_for_student(str(value_text or ''))

        if tag in ds:
            elem = ds[tag]
            vr = getattr(elem, 'VR', '') or ''
            ds[tag].value = _value_for_vr(vr, '' if value_text is None else str(value_text))
        else:
            vr = vr_text or (dictionary_VR(tag) or '')
            if not vr:
                raise ValueError('VR fehlt (z.B. LO, PN, SH, DA, TM, UI).')
            ds.add_new(tag, vr, _value_for_vr(vr, '' if value_text is None else str(value_text)))

        _ensure_new_sop_instance_uid(ds)

        out = BytesIO()
        ds.save_as(out, write_like_original=True)
        new_bytes = out.getvalue()

        created = _orthanc_post_dicom_instance(new_bytes)
        new_id = str(created.get('ID') or '')
        if not new_id:
            raise ValueError(f"Orthanc upload ok, aber keine ID erhalten: {created}")

        new_inst = _orthanc_get_json(f'/instances/{new_id}')
        new_series = str(new_inst.get('ParentSeries') or '')

        return redirect(url_for('main.pacs_instance', instance_id=new_id, series=new_series, msg=f"✅ Metadaten gespeichert: Neue Instanz erstellt ({new_id})."))
    except Exception as e:
        return redirect(url_for('main.pacs_instance', instance_id=instance_id, series=(request.args.get('series') or '').strip(), msg=f"❌ Metadaten-Änderung fehlgeschlagen: {e}"))
