from __future__ import annotations

import os
import tempfile
import zipfile

import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import generate_uid
from pynetdicom import AE, sop_class

try:
    from simlib.config import ORTHANC_HOST, ORTHANC_PORT
except ModuleNotFoundError:
    from .simlib.config import ORTHANC_HOST, ORTHANC_PORT

try:
    from mwl import derive_study_uid
except ImportError:
    from .mwl import derive_study_uid


def send_c_store(patient_name, patient_id, accession_number, study_uid=None):
    ae = AE(ae_title=b'SIMULATOR')
    ae.add_requested_context(sop_class.CTImageStorage)

    if not study_uid:
        # Re-derive StudyUID from Accession to match MWL logic
        study_uid = derive_study_uid(accession_number)

    assoc = ae.associate(ORTHANC_HOST, ORTHANC_PORT)
    if assoc.is_established:
        # Create minimal CT Image
        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = sop_class.CTImageStorage
        file_meta.MediaStorageSOPInstanceUID = generate_uid()
        file_meta.TransferSyntaxUID = pydicom.uid.ImplicitVRLittleEndian

        ds = FileDataset('dummy.dcm', {}, file_meta=file_meta, preamble=b"\0" * 128)

        ds.PatientName = patient_name
        ds.PatientID = patient_id
        ds.AccessionNumber = accession_number
        ds.Modality = 'CT'
        ds.StudyInstanceUID = study_uid if study_uid else generate_uid()
        ds.SeriesInstanceUID = generate_uid()
        ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
        ds.SOPClassUID = sop_class.CTImageStorage

        # Add minimal required tags for CT Image Storage
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.Rows = 512
        ds.Columns = 512
        ds.BitsAllocated = 16
        ds.BitsStored = 12
        ds.HighBit = 11
        ds.PixelRepresentation = 0
        ds.PixelData = (b'\x00\x00' * 512 * 512)  # Blank image

        status = assoc.send_c_store(ds)
        assoc.release()
        return status
    return None


def _save_upload_to_tempdir(upload, temp_dir: str) -> str:
    filename = upload.filename or "upload"
    safe_name = os.path.basename(filename)
    if not safe_name:
        safe_name = "upload"
    target_path = os.path.join(temp_dir, safe_name)
    upload.save(target_path)
    return target_path


def _collect_dicom_file_paths_from_uploads(uploads):
    """Return (dicom_file_paths, temp_dir). Caller must delete temp_dir."""
    temp_dir = tempfile.mkdtemp(prefix="dicom_upload_")
    extracted_dir = os.path.join(temp_dir, "extracted")
    os.makedirs(extracted_dir, exist_ok=True)

    file_paths = []
    for upload in uploads:
        if not upload or not getattr(upload, "filename", None):
            continue

        saved_path = _save_upload_to_tempdir(upload, temp_dir)
        if saved_path.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(saved_path, 'r') as zf:
                    zf.extractall(extracted_dir)
            except zipfile.BadZipFile:
                file_paths.append(saved_path)
        else:
            file_paths.append(saved_path)

    for root, _, files in os.walk(extracted_dir):
        for name in files:
            file_paths.append(os.path.join(root, name))

    # Heuristic: if there are obvious DICOM extensions, filter; otherwise keep all
    likely = [p for p in file_paths if p.lower().endswith((".dcm", ".dicom"))]
    if likely:
        return likely, temp_dir

    return file_paths, temp_dir


def send_c_store_uploaded_files(dicom_paths, *, patient_name, patient_id, accession_number, retag):
    """Send real DICOM instances via C-STORE to Orthanc.

    Returns a summary dict with counters and a small error list.
    """
    from pynetdicom.presentation import StoragePresentationContexts

    summary = {
        "sent": 0,
        "ok": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
    }

    if not dicom_paths:
        return summary

    study_uid = derive_study_uid(accession_number)

    # Some uploads may be compressed (e.g. JPEG 2000). Request a broader set of
    # transfer syntaxes so Orthanc can accept them when supported.
    from pydicom.uid import (
        ExplicitVRLittleEndian,
        ImplicitVRLittleEndian,
        ExplicitVRBigEndian,
        DeflatedExplicitVRLittleEndian,
        JPEGBaseline8Bit,
        JPEGExtended12Bit,
        JPEGLosslessSV1,
        JPEGLSLossless,
        JPEGLSNearLossless,
        JPEG2000,
        JPEG2000Lossless,
        RLELossless,
    )

    requested_transfer_syntaxes = [
        ExplicitVRLittleEndian,
        ImplicitVRLittleEndian,
        DeflatedExplicitVRLittleEndian,
        ExplicitVRBigEndian,
        JPEGBaseline8Bit,
        JPEGExtended12Bit,
        JPEGLosslessSV1,
        JPEGLSLossless,
        JPEGLSNearLossless,
        JPEG2000Lossless,
        JPEG2000,
        RLELossless,
    ]

    ae = AE(ae_title=b'SIMULATOR')
    for cx in StoragePresentationContexts:
        ae.add_requested_context(cx.abstract_syntax, requested_transfer_syntaxes)

    assoc = ae.associate(ORTHANC_HOST, ORTHANC_PORT)
    if not assoc.is_established:
        summary["errors"].append("DICOM Association gescheitert. Ist Orthanc erreichbar?")
        return summary

    try:
        for path in dicom_paths:
            try:
                ds = pydicom.dcmread(path, force=True)
            except Exception as e:
                summary["skipped"] += 1
                summary["errors"].append(f"Nicht lesbar: {os.path.basename(path)} ({e})")
                continue

            # Skip non-storage objects
            if not hasattr(ds, "SOPClassUID") or not hasattr(ds, "SOPInstanceUID"):
                summary["skipped"] += 1
                continue

            if retag:
                ds.PatientName = patient_name
                ds.PatientID = patient_id
                ds.AccessionNumber = accession_number
                ds.StudyID = accession_number
                ds.StudyInstanceUID = study_uid
                ds.Modality = getattr(ds, "Modality", "CT") or "CT"

            summary["sent"] += 1

            try:
                status = assoc.send_c_store(ds)
            except ValueError as e:
                # Typical case: dataset is compressed (e.g. JPEG2000) but no accepted
                # presentation context exists for that transfer syntax.
                # Try to decompress (if pixel data handlers are available) and retry.
                try:
                    ts = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
                    is_compressed = bool(getattr(ts, "is_compressed", False))
                except Exception:
                    is_compressed = False

                if is_compressed and hasattr(ds, "decompress"):
                    try:
                        ds.decompress()
                        status = assoc.send_c_store(ds)
                    except Exception:
                        summary["failed"] += 1
                        summary["errors"].append(
                            "C-STORE fehlgeschlagen: Komprimierte DICOM-Datei (z.B. JPEG2000) "
                            "konnte nicht gesendet/entpackt werden. Bitte unkomprimierte DICOMs hochladen "
                            "oder Orthanc mit Unterstützung für diese Kompression betreiben. "
                            f"Datei: {os.path.basename(path)}"
                        )
                        continue
                else:
                    summary["failed"] += 1
                    summary["errors"].append(
                        f"C-STORE fehlgeschlagen (Transfer Syntax nicht akzeptiert): {os.path.basename(path)} ({e})"
                    )
                    continue
            except Exception as e:
                summary["failed"] += 1
                summary["errors"].append(f"C-STORE Fehlermeldung: {os.path.basename(path)} ({e})")
                continue

            if status and getattr(status, "Status", None) == 0x0000:
                summary["ok"] += 1
            else:
                summary["failed"] += 1
                st = f"0x{getattr(status, 'Status', 0):04x}" if status else "(kein Status)"
                summary["errors"].append(f"C-STORE fehlgeschlagen: {os.path.basename(path)} Status {st}")
    finally:
        assoc.release()

    return summary
