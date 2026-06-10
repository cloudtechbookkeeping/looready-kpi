"""
LooReady - Dashboard Builder & Hostinger SSH Uploader
Reads today's KPI JSON, patches looready-kpi.html, uploads via SSH (cat > pipe).
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

# -- SSH credentials from GitHub Secrets --------------------------------------
SSH_HOST = os.environ.get("SSH_HOST", "145.79.209.123")
SSH_PORT = 65002
SSH_USER = os.environ.get("SSH_USER", "u133013644")
SSH_PASS = os.environ.get("SSH_PASS") or os.environ["FTP_PASS"]
REMOTE_DIR = "public_html/looreadykpi"
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


def ssh_write_file(ssh, remote_path, content_bytes):
    """Write bytes to a remote file via SSH using cat > pipe."""
    cmd = "cat > " + remote_path
    stdin, stdout, stderr = ssh.exec_command(cmd)
    stdin.write(content_bytes)
    stdin.channel.shutdown_write()
    exit_code = stdout.channel.recv_exit_status()
    err = stderr.read().decode().strip()
    if exit_code != 0 or err:
        print("  write_file stderr: " + err + " exit=" + str(exit_code))
    return exit_code


def ssh_upload(html_content, status):
    print("SSH connecting to " + SSH_HOST + ":" + str(SSH_PORT))
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER, password=SSH_PASS, timeout=30)
    print("SSH connected")

    # Ensure remote directory exists
    mkdir_cmd = "mkdir -p ~/" + REMOTE_DIR
    stdin, stdout, stderr = ssh.exec_command(mkdir_cmd)
    stdout.channel.recv_exit_status()
    print("mkdir done: " + mkdir_cmd)

    remote_base = "~/" + REMOTE_DIR + "/"

    # Upload status.txt first (diagnostic)
    status_bytes = json.dumps(status).encode("utf-8")
    ec = ssh_write_file(ssh, remote_base + "status.txt", status_bytes)
    print("status.txt uploaded (exit=" + str(ec) + ")")

    # Upload index.html
    html_bytes = html_content.encode("utf-8")
    ec = ssh_write_file(ssh, remote_base + "index.html", html_bytes)
    print("index.html uploaded (" + str(len(html_bytes)) + " bytes, exit=" + str(ec) + ")")

    # Update status.txt to confirm success
    status["upload_ok"] = True
    status_bytes_final = json.dumps(status).encode("utf-8")
    ssh_write_file(ssh, remote_base + "status.txt", status_bytes_final)

    ssh.close()
    print("SSH upload done. Live at: https://looreadykpi.cloudtechbookkeeping.com")


if __name__ == "__main__":
    print("=== START ===")
    data = load_today_data()
    html, today_str, n1, n2, n3 = update_html(data)
    status = {
        "run": datetime.datetime.utcnow().isoformat(),
        "today": today_str,
        "n1": n1, "n2": n2, "n3": n3,
        "upload_ok": False
    }
    try:
        ssh_upload(html, status)
    except Exception as e:
        print("ERROR: " + str(e))
        traceback.print_exc()
        sys.exit(1)
    print("=== DONE ===")
