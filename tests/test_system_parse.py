import json

from pyrinnaitouch.const import RinnaiSystemMode
from pyrinnaitouch.system_status import RinnaiSystemStatus

def get_test_json():
    """Fixture to return a sample JSON response str"""
    return '[{"SYST": {"CFG": {"MTSP": "N", "NC": "00", "DF": "N", "TU": "C", "CF": "1", "VR": "0183", "CV": "0010", "CC": "043", "ZA": " ", "ZB": " ", "ZC": " ", "ZD": " " }, "AVM": {"HG": "Y", "EC": "N", "CG": "Y", "RA": "N", "RH": "N", "RC": "N" }, "OSS": {"DY": "TUE", "TM": "16:45", "BP": "Y", "RG": "Y", "ST": "N", "MD": "C", "DE": "N", "DU": "N", "AT": "999", "LO": "N" }, "FLT": {"AV": "N", "C3": "000" } } },{"CGOM": {"CFG": {"ZUIS": "N", "ZAIS": "Y", "ZBIS": "Y", "ZCIS": "N", "ZDIS": "N", "CF": "N", "PS": "Y", "DG": "W" }, "OOP": {"ST": "F", "CF": "N", "FL": "00", "SN": "Y" }, "GSS": {"CC": "N", "FS": "N", "CP": "N" }, "APS": {"AV": "N" }, "ZUS": {"AE": "N", "MT": "999" }, "ZAS": {"AE": "N", "MT": "999" }, "ZBS": {"AE": "N", "MT": "999" }, "ZCS": {"AE": "N", "MT": "999" }, "ZDS": {"AE": "N", "MT": "999" } } }]'

def test_zones():
    status = RinnaiSystemStatus()

    assert status.handle_status(json.loads(get_test_json()))
    assert status.mode == RinnaiSystemMode.COOLING
    assert not status.is_multi_set_point
    assert set(status.unit_status.zones) == {"A", "B"}


def test_status_objects_do_not_depend_on_array_order():
    payload = json.loads(get_test_json())
    status = RinnaiSystemStatus()

    assert status.handle_status(list(reversed(payload)))
    assert status.mode == RinnaiSystemMode.COOLING
    assert set(status.unit_status.zones) == {"A", "B"}
