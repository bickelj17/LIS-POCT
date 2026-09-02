"""
Flask web app for POCT result file analysis.
Run: python app.py
- You: http://127.0.0.1:5000
- Teammates (same network): http://<your-IP>:5000  (printed when server starts)
"""
import html
import socket
import tempfile
import threading
import webbrowser
from pathlib import Path

from flask import Flask, request, render_template_string
from werkzeug.utils import secure_filename

from poct_checks import analyze

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # 4 MB max upload

INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>POCT Result File Analysis</title>
    <style>
        * { box-sizing: border-box; }
        body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }
        h1 { margin-bottom: 0.5rem; }
        p { color: #555; margin-bottom: 1.5rem; }
        form { margin-bottom: 1.5rem; }
        input[type="file"] { margin-bottom: 0.75rem; display: block; }
        button {
            background: #2563eb; color: white; border: none; padding: 0.5rem 1rem;
            border-radius: 6px; cursor: pointer; font-size: 1rem;
        }
        button:hover { background: #1d4ed8; }
        .output {
            background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
            padding: 1rem; white-space: pre-wrap; font-family: ui-monospace, monospace;
            font-size: 0.9rem; min-height: 80px;
        }
        .error {
            color: #b91c1c; font-weight: 600;
            background: #fef2f2; border: 1px solid #fecaca;
            border-radius: 8px; padding: 0.75rem 1rem; margin-top: 1rem;
        }
        /* Lines inside analysis output that report failures */
        .output .error-line {
            color: #b91c1c; font-weight: 600;
            background: #fff1f2; display: inline; padding: 0.1em 0.25em;
            border-radius: 4px;
        }
        /* The "<type> test checked" summary line: green if no errors, red if any */
        .output .ok-line {
            color: #15803d; font-weight: 600;
            background: #f0fdf4; display: inline; padding: 0.1em 0.25em;
            border-radius: 4px;
        }
    </style>
</head>
<body>
    <h1>POCT Result File Analysis</h1>
    <p>Upload a POCT result file to run the LIS checks.</p>
    <form method="post" enctype="multipart/form-data">
        <input type="file" name="file" accept=".txt" required>
        <button type="submit">Analyze</button>
    </form>
    {% if result_html %}
    <h2>File Analysis</h2>
    <div class="output">{{ result_html | safe }}</div>
    {% endif %}
    {% if error %}
    <p class="error">{{ error }}</p>
    {% endif %}
</body>
</html>
"""


def run_analysis(file_path: str):
    """Read the file and return its (level, text) findings list."""
    with open(file_path, "r", encoding="utf-8-sig") as f:
        lines = f.readlines()
    return analyze(lines)


def findings_to_html(findings) -> str:
    """
    Turn the structured (level, text) findings into HTML. Unlike the ASTM
    tool, this never has to guess whether a line is an error by scanning
    its wording - `level` already says so directly, which is what lets a
    result value like "invalid" or a foreign-language name print as
    plain, unhighlighted text instead of a false alarm.
    """
    if not findings:
        return ""
    has_errors = any(level == "error" for level, _ in findings)

    chunks = []
    for level, text in findings:
        esc = html.escape(text)
        if level == "error":
            chunks.append(f'<span class="error-line">Error: {esc}</span>')
        elif "test checked" in text:
            css_class = "error-line" if has_errors else "ok-line"
            chunks.append(f'<span class="{css_class}">{esc}</span>')
        else:
            chunks.append(esc)
    return "<br>\n".join(chunks)


@app.route("/", methods=["GET", "POST"])
def index():
    result_html = ""
    error = None
    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename:
            error = "No file selected."
            return render_template_string(INDEX_HTML, result_html=result_html, error=error)

        filename = secure_filename(f.filename) or "upload.txt"
        try:
            # Private temp folder per request - avoids two people running
            # this at once (e.g. off a network share) overwriting each
            # other's upload.
            with tempfile.TemporaryDirectory(prefix="poct_upload_") as tmp_dir:
                path = Path(tmp_dir) / filename
                f.save(str(path))
                findings = run_analysis(str(path))
                result_html = findings_to_html(findings)
        except Exception as e:
            error = str(e)
    return render_template_string(INDEX_HTML, result_html=result_html, error=error)


def _local_ip():
    """Get this machine's LAN IP so teammates can connect."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "?"


if __name__ == "__main__":
    port = 5000
    print("\n  POCT Result Analysis")
    print("  ---------------------")
    print(f"  Open in browser:   http://127.0.0.1:{port}")
    ip = _local_ip()
    if ip != "?":
        print(f"  For teammates:     http://{ip}:{port}")
        print("  (Teammates must be on the same network; allow Python in Windows Firewall if needed.)")
    print("  (Closing this window will stop the app.)\n")

    def _open_browser():
        import time
        time.sleep(1.2)
        webbrowser.open(f"http://127.0.0.1:{port}")
    threading.Thread(target=_open_browser, daemon=True).start()
    app.run(host="0.0.0.0", port=port, debug=False)
