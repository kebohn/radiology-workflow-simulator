from __future__ import annotations

import datetime
import hashlib
import os

from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import generate_uid
from pynetdicom import AE, sop_class

try:
    from simlib.config import ORTHANC_HOST, ORTHANC_PORT, WORKLIST_DIR
    from simlib.students import get_student_code
    from simlib.util import safe_filename_component
except ModuleNotFoundError:
    from .simlib.config import ORTHANC_HOST, ORTHANC_PORT, WORKLIST_DIR
    from .simlib.students import get_student_code
    from .simlib.util import safe_filename_component


def derive_study_uid(accession_number: str) -> str:
    # Deterministic Study UID for this simulation (derived from Accession)
    digest = hashlib.md5((accession_number + ".study").encode()).hexdigest()
    return "1.2.826.0.1.3680043.2." + str(int(digest, 16))[:10]


def create_dicom_worklist_file(patient_name, patient_id, accession_number, study_desc):
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = '1.2.840.10008.5.1.4.1.1.7'  # Secondary Capture (dummy)
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.ImplementationClassUID = generate_uid()

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)

    # Required attributes for valid DICOM
    ds.SpecificCharacterSet = "ISO_IR 100"

    # Deterministic Study UID for this simulation (derived from Accession)
    ds.StudyInstanceUID = derive_study_uid(accession_number)

    # MWL specific tags
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.AccessionNumber = accession_number
    ds.StudyID = accession_number
    ds.StudyDescription = study_desc
    ds.ReferringPhysicianName = "Dr. House"

    # Scheduled Procedure Step Sequence
    sps = Dataset()
    sps.ScheduledStationAETitle = "SIMULATOR"
    sps.ScheduledProcedureStepStartDate = datetime.datetime.now().strftime('%Y%m%d')
    sps.ScheduledProcedureStepStartTime = datetime.datetime.now().strftime('%H%M%S')
    sps.Modality = "CT"
    sps.ScheduledProcedureStepDescription = study_desc
    sps.ScheduledProcedureStepID = accession_number

    ds.ScheduledProcedureStepSequence = [sps]

    # Requested Procedure
    ds.RequestedProcedureID = accession_number
    ds.RequestedProcedureDescription = study_desc

    safe_acc = safe_filename_component(accession_number)
    filename = os.path.join(WORKLIST_DIR, f"{safe_acc}.wl")
    ds.save_as(filename, write_like_original=False)
    return filename


def dataset_to_dict(ds):
    res = {}
    # Extract root level simple elements
    for elem in ds:
        if elem.VR != "SQ":
            key = elem.keyword if elem.keyword else str(elem.tag)
            res[key] = str(elem.value)

    # Extract from SPS Sequence (often nested in MWL)
    if 'ScheduledProcedureStepSequence' in ds and len(ds.ScheduledProcedureStepSequence) > 0:
        sps = ds.ScheduledProcedureStepSequence[0]
        if 'ScheduledProcedureStepDescription' in sps:
            res['RequestedProcedureDescription'] = str(sps.ScheduledProcedureStepDescription)
        if 'Modality' in sps:
            res['Modality'] = str(sps.Modality)

    return res


def perform_c_find_mwl():
    ae = AE(ae_title=b'SIMULATOR')
    ae.add_requested_context(sop_class.ModalityWorklistInformationFind)

    # Associate with Peer
    assoc = ae.associate(ORTHANC_HOST, ORTHANC_PORT)

    results = []
    if assoc.is_established:
        print('Association established with Orthanc')
        # Create a query dataset
        ds = Dataset()
        ds.PatientName = '*'
        code = get_student_code()
        ds.PatientID = f"{code}-*" if code else ''
        ds.AccessionNumber = ''
        ds.StudyInstanceUID = ''
        ds.RequestedProcedureDescription = ''

        ds.ScheduledProcedureStepSequence = [Dataset()]
        ds.ScheduledProcedureStepSequence[0].ScheduledStationAETitle = 'SIMULATOR'
        ds.ScheduledProcedureStepSequence[0].ScheduledProcedureStepStartDate = datetime.datetime.now().strftime('%Y%m%d')
        ds.ScheduledProcedureStepSequence[0].Modality = 'CT'
        ds.ScheduledProcedureStepSequence[0].ScheduledProcedureStepDescription = ''
        ds.ScheduledProcedureStepSequence[0].ScheduledProcedureStepID = ''

        responses = assoc.send_c_find(ds, query_model=sop_class.ModalityWorklistInformationFind)

        for (status, dataset) in responses:
            # C-FIND yields (status, identifier)
            # If status is Pending (0xFF00) or Success (0x0000)
            if status.Status == 0xFF00:
                if dataset:
                    results.append(dataset_to_dict(dataset))
            elif status.Status == 0x0000:
                pass  # Success

        assoc.release()
    else:
        print('Association rejected, aborted or never connected')

    return results
