"""
Low-level POCT message parsing and field checks.

A POCT result file is a raw transcript of an instrument "conversation":
several complete XML documents (HEL, ACK, DST, DTV, OBS, END, ...) sent
back and forth, each one spread across many physical lines and prefixed
with "[timestamp]  Client/Server N: " - the same shape ASTM_LIS's raw
transcripts use, just with XML instead of pipe-delimited text.

Unlike the ASTM checker, findings here are NOT printed directly. Each
check appends (level, text) tuples to a shared `findings` list instead -
level is "error" or "info". That's what lets app.py decide red/green
from real data instead of scanning rendered text for keywords like
"invalid" - which would misfire here, since "invalid" is also a
legitimate test *result* value (see sample_results/POCT Patient test
SARS.txt).
"""
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

LINE_PATTERN = re.compile(r'^\[[\d.]+\]\s+(Client|Server)\s+\d+:\s?(.*)$')

# POCT timestamps carry their own real UTC offset (e.g. "-08:00"), so
# unlike ASTM there's no DST guessing needed - just convert to Pacific
# local time for display, same style as the ASTM tool.
LOCAL_TZ = ZoneInfo("America/Los_Angeles")


def format_local_datetime(iso_string):
    """
    Convert a POCT ISO-8601 datetime (e.g. "2026-03-10T11:32:26+00:00")
    to Pacific local time, formatted as "03/10/2026 at 11:32 PDT" - same
    style as the ASTM tool's format_local_time(). Returns None if the
    string can't be parsed (check_dates() already reports that as an
    error; this just avoids crashing the display).
    """
    if not iso_string:
        return None
    try:
        dt = datetime.fromisoformat(iso_string)
    except ValueError:
        return None
    local_dt = dt.astimezone(LOCAL_TZ)
    return f"{local_dt.month:02d}/{local_dt.day:02d}/{local_dt.year} at {local_dt.hour:02d}:{local_dt.minute:02d} {local_dt.tzname()}"

# Root tags we know how to check. Anything else is reported as unrecognized.
KNOWN_ROOT_TAGS = {"HEL.R01", "ACK.R01", "DST.R01", "DTV.R01", "OBS.R01", "OBS.R02", "END.R01"}

DATETIME_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$')
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def add_error(findings, text):
    findings.append(("error", text))


def add_info(findings, text):
    findings.append(("info", text))


class Message:
    """One parsed XML document from the transcript (e.g. one <OBS.R01> block)."""
    def __init__(self, sender, root):
        self.sender = sender  # "Client" or "Server"
        self.root = root      # xml.etree.ElementTree.Element


def scrape_messages(lines, findings):
    """
    Reassemble the raw transcript's embedded XML documents and parse each
    one for real with ElementTree. A malformed document is reported as an
    error and skipped - it doesn't stop the rest of the file from being
    checked, the same way one bad ASTM record doesn't stop scrape_lines()
    from handling the others.
    """
    messages = []
    current_sender = None
    current_lines = []

    def flush():
        if not current_lines:
            return
        xml_text = "\n".join(current_lines)
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            add_error(findings, f'Could not read an XML message from {current_sender}: {e}')
            return
        messages.append(Message(current_sender, root))

    for raw_line in lines:
        match = LINE_PATTERN.match(raw_line.rstrip("\n"))
        if not match:
            continue  # not a transcript line (blank line, etc.) - skip it
        sender, content = match.group(1), match.group(2).rstrip()
        if content.startswith("<?xml"):
            flush()
            current_lines = [content]
            current_sender = sender
        elif current_lines:
            current_lines.append(content)
    flush()
    return messages


def find_descendant(root, tag_name):
    """Find the first element anywhere under `root` with this exact tag,
    e.g. find_descendant(root, 'SVC') finds the <SVC> container."""
    if root is None:
        return None
    for el in root.iter():
        if el.tag == tag_name:
            return el
    return None


def child_value(parent, field_name):
    """Return the V attribute of the direct child tagged '<Parent>.<field_name>',
    e.g. child_value(hdr, 'control_id') reads <HDR.control_id V="..."/>."""
    if parent is None:
        return None
    suffix = "." + field_name
    for child in parent:
        if child.tag and child.tag.endswith(suffix):
            return child.get("V")
    return None


def child_present(parent, field_name):
    """True if `parent` has a child element for `field_name` at all, even
    if its V value is blank. Some fields - patient_id in particular - can
    legitimately be sent empty depending on the lab's workflow (e.g. a
    quick/walk-in test); only a fully absent element is a real problem,
    unlike a value that's actually wrong."""
    if parent is None:
        return False
    suffix = "." + field_name
    return any(child.tag and child.tag.endswith(suffix) for child in parent)


def check_message_structure(messages, findings):
    """Validate that each message has the sections POCT1 requires for its type."""
    for msg in messages:
        tag = msg.root.tag or ""
        sender = msg.sender

        if tag not in KNOWN_ROOT_TAGS:
            add_error(findings, f'{sender} sent an unrecognized message type "{tag}"')
            continue

        hdr = find_descendant(msg.root, "HDR")
        if hdr is None:
            add_error(findings, f"{sender} {tag}: missing HDR section")
        else:
            if not child_value(hdr, "control_id"):
                add_error(findings, f"{sender} {tag}: HDR is missing control_id")
            version = child_value(hdr, "version_id")
            if version != "POCT1":
                add_error(findings, f'{sender} {tag}: HDR.version_id is "{version}", expected "POCT1"')
            if not child_value(hdr, "creation_dttm"):
                add_error(findings, f"{sender} {tag}: HDR is missing creation_dttm")

        if tag == "HEL.R01":
            dev = find_descendant(msg.root, "DEV")
            if dev is None:
                add_error(findings, f"{sender} HEL.R01: missing DEV section")
            else:
                if not child_value(dev, "device_id"):
                    add_error(findings, f"{sender} HEL.R01: DEV is missing device_id")
                serial_id = child_value(dev, "serial_id")
                if not serial_id:
                    add_error(findings, f"{sender} HEL.R01: DEV is missing serial_id")
                elif not (len(serial_id) == 8 and serial_id.isdigit()):
                    add_error(findings, f'{sender} HEL.R01: serial number "{serial_id}" should be exactly '
                                         f'8 digits')

        elif tag == "ACK.R01":
            ack = find_descendant(msg.root, "ACK")
            if ack is None:
                add_error(findings, f"{sender} ACK.R01: missing ACK section")
            else:
                type_cd = child_value(ack, "type_cd")
                if type_cd != "AA":
                    add_error(findings, f'{sender} ACK.R01: type_cd is "{type_cd}", expected "AA" (accept)')
                if not child_value(ack, "ack_control_id"):
                    add_error(findings, f"{sender} ACK.R01: missing ack_control_id")

        elif tag == "DST.R01":
            if find_descendant(msg.root, "DST") is None:
                add_error(findings, f"{sender} DST.R01: missing DST section")

        elif tag == "DTV.R01":
            dtv = find_descendant(msg.root, "DTV")
            if dtv is None or not child_value(dtv, "command_cd"):
                add_error(findings, f"{sender} DTV.R01: missing DTV.command_cd")

        elif tag == "END.R01":
            trm = find_descendant(msg.root, "TRM")
            if trm is None or not child_value(trm, "reason_cd"):
                add_error(findings, f"{sender} END.R01: missing TRM.reason_cd")

        elif tag in ("OBS.R01", "OBS.R02"):
            _check_obs_content(msg, tag, sender, findings)


def _check_obs_content(msg, tag, sender, findings):
    """Validate the actual result payload of an OBS.R01/OBS.R02 message."""
    svc = find_descendant(msg.root, "SVC")
    if svc is None:
        add_error(findings, f"{sender} {tag}: missing SVC section")
        return

    role_cd = child_value(svc, "role_cd")
    if role_cd not in ("OBS", "CAL", "LQC"):
        add_error(findings, f'{sender} {tag}: SVC.role_cd is "{role_cd}", expected OBS, CAL, or LQC')
        return  # can't check the rest without knowing which shape to expect

    if role_cd == "OBS":
        pt = find_descendant(svc, "PT")
        if pt is None:
            add_error(findings, f"{sender} {tag}: Patient result is missing the PT (patient) section")
        else:
            if not child_present(pt, "patient_id"):
                add_error(findings, f"{sender} {tag}: PT is missing the patient_id field entirely")
            # A blank patient_id (element present, empty value) is valid -
            # some workflows legitimately don't collect one - only length
            # is checked here, not presence.
            patient_id = child_value(pt, "patient_id") or ""
            if len(patient_id) > 20:
                add_error(findings, f"{sender} {tag}: Patient ID is too long "
                                     f"({len(patient_id)} characters, max 20)")

        ord_el = find_descendant(svc, "ORD")
        if ord_el is None:
            add_error(findings, f"{sender} {tag}: Patient result is missing the ORD (order) section")
        else:
            order_id = child_value(ord_el, "order_id") or ""
            if len(order_id) > 20:
                add_error(findings, f"{sender} {tag}: Order Number is too long "
                                     f"({len(order_id)} characters, max 20)")
        container_tag = "PT"
    else:
        ctc = find_descendant(svc, "CTC")
        if ctc is None:
            add_error(findings, f"{sender} {tag}: Control result is missing the CTC section")
        else:
            if not child_value(ctc, "name"):
                add_error(findings, f"{sender} {tag}: CTC is missing name")
            if not child_value(ctc, "lot_number"):
                add_error(findings, f"{sender} {tag}: CTC is missing lot_number")
        container_tag = "CTC"

    container = find_descendant(svc, container_tag)
    analytes = container.findall("OBS") if container is not None else []
    if not analytes:
        add_error(findings, f"{sender} {tag}: no analyte result found")
    for analyte in analytes:
        name = child_value(analyte, "observation_id")
        if not name:
            add_error(findings, f"{sender} {tag}: an analyte is missing observation_id")
        if name and name.endswith("_VAL"):
            # A companion S/CO (signal-to-cutoff) reading for another
            # analyte, e.g. "Legion_VAL" alongside "Legion" - it reports a
            # numeric OBS.value, not a qualitative_value.
            if child_value(analyte, "value") is None:
                add_error(findings, f"{sender} {tag}: {name} is missing its S/CO value")
        elif child_value(analyte, "qualitative_value") is None:
            add_error(findings, f"{sender} {tag}: an analyte is missing qualitative_value")

    opr = find_descendant(svc, "OPR")
    if opr is None:
        add_error(findings, f"{sender} {tag}: missing OPR (operator) section")
    else:
        operator_id = child_value(opr, "operator_id") or ""
        if len(operator_id) > 20:
            add_error(findings, f"{sender} {tag}: User ID is too long "
                                 f"({len(operator_id)} characters, max 20)")


def check_handshake_linkage(messages, findings):
    """
    Every non-ACK message should get acknowledged by the *other* side,
    referencing its control_id, with type_cd "AA" (accept). This is the
    "everything has to be precise" check on the conversation itself, not
    just the result content.
    """
    pending = {}  # control_id -> (sender, tag) of the message awaiting an ack

    for msg in messages:
        tag = msg.root.tag or ""
        hdr = find_descendant(msg.root, "HDR")
        control_id = child_value(hdr, "control_id") if hdr is not None else None

        if tag == "ACK.R01":
            ack = find_descendant(msg.root, "ACK")
            ack_control_id = child_value(ack, "ack_control_id") if ack is not None else None
            if ack_control_id is None:
                continue  # already reported by check_message_structure
            if ack_control_id not in pending:
                add_error(findings, f"{msg.sender} ACK.R01 acknowledges control_id {ack_control_id}, "
                                     f"but no message with that ID is waiting for an ack")
            else:
                sender, orig_tag = pending.pop(ack_control_id)
                if sender == msg.sender:
                    add_error(findings, f"{msg.sender} ACK.R01 acknowledges its own message "
                                         f"({orig_tag} control_id {ack_control_id}) instead of the other side's")
        elif control_id is not None:
            pending[control_id] = (msg.sender, tag)

    for control_id, (sender, tag) in pending.items():
        add_error(findings, f"{sender} {tag} (control_id {control_id}) was never acknowledged")


def check_control_id_sequencing(messages, findings):
    """control_id is a counter each sender maintains independently - check
    it's unique and strictly increasing within each sender's own stream."""
    last_id = {}
    seen = {}
    for msg in messages:
        hdr = find_descendant(msg.root, "HDR")
        control_id = child_value(hdr, "control_id") if hdr is not None else None
        if control_id is None:
            continue
        sender = msg.sender
        seen.setdefault(sender, set())
        if control_id in seen[sender]:
            add_error(findings, f"{sender} control_id {control_id} is used more than once")
        seen[sender].add(control_id)

        try:
            numeric_id = int(control_id)
        except ValueError:
            add_error(findings, f'{sender} control_id "{control_id}" is not numeric')
            continue
        if sender in last_id and numeric_id <= last_id[sender]:
            add_error(findings, f"{sender} control_id {control_id} is out of sequence "
                                 f"(expected greater than {last_id[sender]:05d})")
        last_id[sender] = numeric_id


def check_dates(messages, findings):
    """Every *_dttm attribute should be a full ISO-8601 date/time with a UTC
    offset; every *_date attribute should be a plain YYYY-MM-DD date. POCT
    timestamps carry their own real UTC offset (e.g. "-08:00"), so unlike
    ASTM there's no DST guessing needed here - just check the shape."""
    for msg in messages:
        for el in msg.root.iter():
            value = el.get("V")
            if value is None or not el.tag:
                continue
            field_name = el.tag.split(".")[-1]
            if field_name.endswith("_dttm"):
                if not DATETIME_RE.match(value):
                    add_error(findings, f'{msg.sender} {msg.root.tag}: {el.tag} value "{value}" is not a valid '
                                         f'date/time (expected YYYY-MM-DDTHH:MM:SS+HH:MM)')
            elif field_name.endswith("_date"):
                if not DATE_RE.match(value):
                    add_error(findings, f'{msg.sender} {msg.root.tag}: {el.tag} value "{value}" is not a valid '
                                         f'date (expected YYYY-MM-DD)')


def check_bad_characters(messages, findings):
    """
    Flags actual corruption: the Unicode replacement character (a sign a
    decode failed), stray control characters, or unpaired surrogates.
    Does NOT flag legitimate foreign-language text - a tester-entered name
    like "Ostergaarden..." with real accented letters is valid data, not
    an error (confirmed against sample_results/POCT Calibration.txt).
    """
    for msg in messages:
        for el in msg.root.iter():
            value = el.get("V")
            if not value or not el.tag:
                continue
            for ch in value:
                if ch == "�":
                    add_error(findings, f'{msg.sender} {msg.root.tag}: {el.tag} contains the Unicode replacement '
                                         f'character (a sign this field failed to decode correctly): "{value}"')
                    break
                if unicodedata.category(ch) == "Cs":
                    add_error(findings, f'{msg.sender} {msg.root.tag}: {el.tag} contains an invalid character '
                                         f'(unpaired surrogate): "{value}"')
                    break
                if ord(ch) < 0x20 and ch != "\t":
                    add_error(findings, f'{msg.sender} {msg.root.tag}: {el.tag} contains a control character '
                                         f'(code point {ord(ch)}): "{value}"')
                    break


def _build_analytes(container):
    """
    Pull every <OBS> result out of a PT/CTC container. Some instruments
    report a numeric S/CO (signal-to-cutoff) reading as its own separate
    <OBS> block alongside the qualitative call, named "<analyte>_VAL"
    (e.g. "Legion" + "Legion_VAL", using OBS.value instead of
    OBS.qualitative_value) - this pairs each "_VAL" entry with its
    matching analyte instead of listing it as an unrelated result.
    """
    if container is None:
        return []

    raw = [
        {
            "name": child_value(obs, "observation_id"),
            "qualitative_value": child_value(obs, "qualitative_value"),
            "sco_value": child_value(obs, "value"),
            "method_cd": child_value(obs, "method_cd"),
        }
        for obs in container.findall("OBS")
    ]

    analytes = [
        {"name": a["name"], "value": a["qualitative_value"], "method_cd": a["method_cd"], "sco_value": None}
        for a in raw if not (a["name"] or "").endswith("_VAL")
    ]
    for a in raw:
        name = a["name"] or ""
        if not name.endswith("_VAL"):
            continue
        base_name = name[: -len("_VAL")]
        target = next((m for m in analytes if m["name"] == base_name), None)
        if target is not None:
            target["sco_value"] = a["sco_value"]
        else:
            # No matching base analyte - report it on its own rather than
            # silently dropping the value.
            analytes.append({"name": name, "value": a["qualitative_value"],
                              "method_cd": a["method_cd"], "sco_value": a["sco_value"]})
    return analytes


def extract_device_info(messages):
    """
    Pulls the instrument's serial number and software version from the
    HEL.R01 handshake message - sent once per conversation (not once per
    result), so this is reported separately from extract_results().
    """
    for msg in messages:
        if msg.root.tag == "HEL.R01":
            dev = find_descendant(msg.root, "DEV")
            return {
                "serial_id": child_value(dev, "serial_id"),
                "sw_version": child_value(dev, "sw_version"),
            }
    return {"serial_id": None, "sw_version": None}


def extract_results(messages):
    """
    Returns one dict per Client-sent OBS.R01/OBS.R02 message. A file can
    contain more than one result (e.g. two QC levels run back to back -
    see sample_results/Full QC SARS+.txt), so this always returns a list.
    """
    results = []
    for msg in messages:
        if msg.sender != "Client" or msg.root.tag not in ("OBS.R01", "OBS.R02"):
            continue
        svc = find_descendant(msg.root, "SVC")
        if svc is None:
            continue

        role_cd = child_value(svc, "role_cd")
        result_type = {"OBS": "patient", "CAL": "calibration", "LQC": "qc"}.get(role_cd, "unknown")
        container_tag = "PT" if result_type == "patient" else "CTC"
        container = find_descendant(svc, container_tag)
        hdr = find_descendant(msg.root, "HDR")

        result = {
            "type": result_type,
            # When the message itself was sent, vs. observation_dttm below
            # (when the test was actually run) - these can differ a lot,
            # see sample_results/POCT Calibration.txt.
            "creation_dttm": child_value(hdr, "creation_dttm"),
            "observation_dttm": child_value(svc, "observation_dttm"),
            "patient_id": child_value(container, "patient_id") if result_type == "patient" else None,
            "control": {
                "name": child_value(container, "name"),
                "lot_number": child_value(container, "lot_number"),
                "expiration_date": child_value(container, "expiration_date"),
                "level_cd": child_value(container, "level_cd"),
            } if result_type != "patient" else {},
            "analytes": _build_analytes(container),
            "operator": {
                "operator_id": child_value(find_descendant(svc, "OPR"), "operator_id"),
                "name": child_value(find_descendant(svc, "OPR"), "name"),
            },
            "order": {
                "universal_service_id": child_value(find_descendant(svc, "ORD"), "universal_service_id"),
                "order_id": child_value(find_descendant(svc, "ORD"), "order_id"),
            },
            "reagent": {
                "name": child_value(find_descendant(svc, "RGT"), "name"),
                "lot_number": child_value(find_descendant(svc, "RGT"), "lot_number"),
                "expiration_date": child_value(find_descendant(svc, "RGT"), "expiration_date"),
            },
        }
        results.append(result)
    return results
