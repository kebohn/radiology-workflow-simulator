from __future__ import annotations

from pynetdicom import AE, sop_class
from pydicom.dataset import Dataset

try:
    from simlib.config import ORTHANC_HOST, ORTHANC_PORT
    from simlib.students import get_student_code
except ModuleNotFoundError:
    from .simlib.config import ORTHANC_HOST, ORTHANC_PORT
    from .simlib.students import get_student_code

try:
    from mwl import dataset_to_dict
except ImportError:
    from .mwl import dataset_to_dict


def _query_studies():
    studies = []
    try:
        ae = AE(ae_title=b'SIMULATOR')
        ae.add_requested_context(sop_class.StudyRootQueryRetrieveInformationModelFind)

        assoc = ae.associate(ORTHANC_HOST, ORTHANC_PORT)
        if assoc.is_established:
            ds = Dataset()
            ds.QueryRetrieveLevel = 'STUDY'
            ds.PatientName = ''
            code = get_student_code()
            ds.PatientID = f"{code}-*" if code else ''
            ds.StudyDate = ''
            ds.StudyInstanceUID = ''
            ds.AccessionNumber = ''
            ds.ModalitiesInStudy = ''

            responses = assoc.send_c_find(ds, query_model=sop_class.StudyRootQueryRetrieveInformationModelFind)
            for (status, dataset) in responses:
                if status.Status == 0xFF00 and dataset:
                    studies.append(dataset_to_dict(dataset))
            assoc.release()
    except Exception as e:
        print(f"Error querying PACS: {e}")

    return studies
