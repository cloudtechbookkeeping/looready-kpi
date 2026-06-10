"""
LooReady - Dashboard Builder & Hostinger SFTP Uploader
Reads today's KPI JSON, patches looready-kpi.html, uploads via SFTP (SSH port 65002).
SSH credentials come from environment variables (GitHub Secrets).
"""

import json
import re
import os
import sys
import io
import datetime
import traceback
from pathlib import Path

import paramiko

# -- SSH/SFTP credentials from GitHub Secrets ---------------------------------
SSH_HOST = os.environ.get("SSH_HOST", "145.79.209.123")
SSH_PORT = 65002
SSH_USER = os.environ.get("SSH_USER", "u133013644")
SSH_PASS = os.environ.get("SSH_PASS") or os.environ["FTP_PASS"]
REMOTE_DIR  = "public_html/looreadykpi"
# -----------------------------------------------------------------------------

HTML_FILE = Path("looready-kpi.html")
DATA_DIR  = Path("kpi_data")


def load_today_data():
    today = datetime.date.today().isoformat()
    json_path = DATA_DIR / f"{today}.json"
    print("Data file: " + str(json_path) + " exists=" + str(json_path.exists()))
    if not json_path.exists():
        print("No data file for today: " + str(json_path))
        sys.exit(1)
    with open(json_path) as f:
        return json.load(f)


def update_html(data):
    today_str = datetime.date.today().strftime("%B %-d, %Y")
    revenue   = "$" + f"{data['revenue_today']:,.2f}"
    orders    = data['orders_today']
    units     = data.get('units_ordered', 0)
    fees      = data.get('finance', {}).get('total_fees', 0)

    html = HTML_FILE.read_text(encoding="utf-8")
    print("HTML len=" + str(len(html)))

    # 1. Live badge date
    html, n1 = re.subn(
        r"Live .{1,3} Updated \w+ \d+, \d{4}",
        "Live . Updated " + today_str,
        html
    )

    # 2. Data snapshot line
    html, n2 = re.subn(
        r"Data snapshot: [^\n<]*</div>",
        "Data snapshot: " + today_str + " . SP-API live pull</div>",
        html
    )

    # 3. today JS data object
    today_obj = (
        "'today': { revenue:'" + revenue +
        "', units:'" + str(orders) +
        "', spend:'--', acos:'--', sessions:'--', ipi:'628',\n" +
        "            rsub:'Today " + today_str + " . SP-API live'" +
        ", usub:'" + str(orders) + " orders . " + str(units) +
        " units . Fees $" + f"{fees:,.2f}'" +
        ", ssub:'Not yet available', asub:'Not yet available'" +
        ", sesub:'Not yet available', isub:'Range 570-686',\n" +
        "            acosColor:'#6b7280' }"
    )
    html, n3 = re.subn(r"'today':\s*\{[\s\S]*?\}(?=\s*,)", today_obj, html)

    print("n1=" + str(n1) + " n2=" + str(n2) + " n3=" + str(n3))
    if n1 == 0 or n2 == 0 or n3 == 0:
        print("WARNING: one or more regex patterns did not match!")
    return html, today_str, n1, n2, n3


def sftp_upload(html_content, status):
    print("SFTP connecting to " + SSH_HOST + ":" + str(SSH_PORT))
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER, password=SSH_PASS, timeout=30)
    print("SSH connected")

    sftp = ssh.open_sftp()

    # Ensure remote directory exists
    try:
        sftp.chdir(REMOTE_DIR)
        print("chdir OK: " + REMOTE_DIR)
    except IOError:
        print("Creating remote dir: " + REMOTE_DIR)
        parts = REMOTE_DIR.split("/")
        path = ""
        for part in parts:
            path = (path + "/" + part).lstrip("/")
            try:
                sftp.mkdir(path)
            except IOError:
                pass  # already exists
        sftp.chdir(REMOTE_DIR)

    # Upload status.txt first (diagnostic)
    sftp.putfo(io.BytesIO(json.dumps(status).encode("utf-8")), "status.txt")
    print("status.txt uploaded")

    # Upload index.html
    data = html_content.encode("utf-8")
    sftp.putfo(io.BytesIO(data), "index.html")
    print("index.html uploaded (" + str(len(data)) + " bytes)")

    # Update status.txt to confirm success
    status["sftp_ok"] = True
    sftp.putfo(io.BytesIO(json.dumps(status).encode("utf-8")), "status.txt")

    sftp.close()
    ssh.close()
    print("SFTP done. Live at: https://looreadykpi.cloudtechbookkeeping.com")


if __name__ == "__main__":
    print("=== START ===")
    data = load_today_data()
    html, today_str, n1, n2, n3 = update_html(data)
    status = {
        "run": datetime.datetime.utcnow().isoformat(),
        "today": today_str,
        "n1": n1, "n2": n2, "n3": n3,
        "sftp_ok": False
    }
    try:
        sftp_upload(html, status)
    except Exception as e:
        print("ERROR: " + str(e))
        traceback.print_exc()
        sys.exit(1)
    print("=== DONE ===")
