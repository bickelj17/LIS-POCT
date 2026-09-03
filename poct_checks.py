"""
Top-level POCT analysis: parse the file, run every check, and describe
the result(s) found. This is the POCT equivalent of astm_checks.py.
"""
from poct_line_checks import (
    scrape_messages,
    check_message_structure,
    check_handshake_linkage,
    check_control_id_sequencing,
    check_dates,
    check_bad_characters,
    extract_device_info,
    extract_results,
    format_local_datetime,
    add_info,
    add_error,
)

RESULT_LABELS = {"patient": "Patient", "qc": "QC", "calibration": "Calibration", "unknown": "Unknown"}


def analyze(lines):
    """
    Runs the full POCT pipeline and returns a list of (level, text)
    findings in display order - "error" for problems, "info" for the
    human-readable summary of what's in the file. The "<type> test
    checked" summary lines come first, matching the ASTM tool.
    """
    findings = []

    messages = scrape_messages(lines, findings)
    if not messages:
        add_error(findings, "No POCT messages could be read from this file")
        return findings

    check_message_structure(messages, findings)
    check_handshake_linkage(messages, findings)
    check_control_id_sequencing(messages, findings)
    check_dates(messages, findings)
    check_bad_characters(messages, findings)

    results = extract_results(messages)
    if not results:
        add_error(findings, "No Patient/QC/Calibration result was found in this file")

    # Device info (serial number, SW version) comes from one HEL.R01
    # handshake per file, not once per result - shown after the first
    # result's heading rather than repeated for every result.
    device_lines = describe_device(messages)

    summary = []
    for i, result in enumerate(results, start=1):
        summary.extend(describe_result(result, i, len(results), device_lines if i == 1 else None))

    # Summary ("<type> test checked" + the readable fields) goes first,
    # the detailed structural/handshake findings follow.
    return summary + findings


def _add_time_line(lines, label, iso_string):
    """Print one "<label>: MM/DD/YYYY at HH:MM PST/PDT" line, or a fallback
    if the timestamp is missing or couldn't be parsed."""
    if not iso_string:
        return
    formatted = format_local_datetime(iso_string)
    if formatted:
        add_info(lines, f"{label}: {formatted}")
    else:
        add_info(lines, f"{label}: {iso_string} (could not read this date/time)")


def describe_device(messages):
    """Build the "Serial Number" / "Sofia 2 SW Version" lines from the
    file's HEL.R01 handshake message."""
    lines = []
    device = extract_device_info(messages)
    if device.get("serial_id"):
        add_info(lines, f"Serial Number: {device['serial_id']}")
    if device.get("sw_version"):
        add_info(lines, f"Sofia 2 SW Version: {device['sw_version']}")
    return lines


def describe_result(result, index, total, device_lines=None):
    """Build the human-readable summary lines for one result."""
    lines = []
    label = RESULT_LABELS.get(result["type"], "Unknown")
    heading = f"{label} test checked" if total == 1 else f"{label} test checked (result {index} of {total})"
    add_info(lines, heading)

    _add_time_line(lines, "Message created", result["creation_dttm"])

    if device_lines:
        lines.extend(device_lines)

    if result["type"] == "patient":
        add_info(lines, f"Patient ID: {result['patient_id']}")
    else:
        control = result["control"]
        if control.get("name") or control.get("lot_number"):
            add_info(lines, f"{control.get('name')}, lot {control.get('lot_number')}")
            if control.get("level_cd"):
                add_info(lines, f"Control level: {control['level_cd']}")
            if control.get("expiration_date"):
                add_info(lines, f"Expires: {control['expiration_date']}")
        else:
            add_info(lines, "(control/calibration details could not be read - see errors below)")

    for analyte in result["analytes"]:
        line = f"{analyte['name']} = {analyte['value']}"
        if analyte.get("sco_value") is not None:
            line += f" (S/CO {analyte['sco_value']})"
        add_info(lines, line)

    _add_time_line(lines, "Test executed", result["observation_dttm"])

    operator = result["operator"]
    if operator.get("operator_id"):
        add_info(lines, f"User ID: {operator['operator_id']}")
    if operator.get("name"):
        add_info(lines, f"Username: {operator['name']}")

    order = result["order"]
    if order.get("order_id"):
        add_info(lines, f"Order Number: {order['order_id']}")

    reagent = result["reagent"]
    if reagent.get("name"):
        add_info(lines, f"Reagent: {reagent['name']}, lot {reagent.get('lot_number')}, "
                        f"expires {reagent.get('expiration_date')}")

    return lines


if __name__ == "__main__":
    # Simple CLI test when running this file directly.
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "sample_results/good/POCT Patient test FLU AB.txt"
    with open(path, "r", encoding="utf-8-sig") as f:
        raw_lines = f.readlines()
    for level, text in analyze(raw_lines):
        prefix = "Error: " if level == "error" else ""
        print(f"{prefix}{text}")
