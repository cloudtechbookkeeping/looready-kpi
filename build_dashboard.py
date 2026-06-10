"""
LooReady - Dashboard Builder & Hostinger FTP Uploader
Reads today's KPI JSON, patches looready-kpi.html, uploads via FTP with retry.
Credentials come from environment variables (GitHub Secrets).
"""

import json
import re
import os
import sys
import io
import time
import ftplib
import datetime
import traceback
from pathlib import Path

# -- FTP credentials from GitHub Secrets --------------------------------------
FTP_HOST = os.environ.get("FTP_HOST", "145.79.209.123")
FTP_USER = os.environ.get("FTP_USER", "u133013644")
FTP_PASS = os.environ.get("FTP_PASS") or os.environ.get("SSH_PASS")
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


def ftp_upload(html_content, status, max_retries=3):
    html_bytes = html_content.encode("utf-8")
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            print("FTP attempt " + str(attempt) + "/" + str(max_retries) +
                  " connecting to " + FTP_HOST)
            ftp = ftplib.FTP(timeout=60)
            ftp.connect(FTP_HOST, 21, timeout=60)
            ftp.login(FTP_USER, FTP_PASS)
            ftp.set_pasv(True)
            print("FTP logged in, cwd -> " + REMOTE_DIR)
            ftp.cwd(REMOTE_DIR)

            # Upload status.txt (diagnostic marker)
            status_bytes = json.dumps(status).encode("utf-8")
            ftp.storbinary("STOR status.txt", io.BytesIO(status_bytes))
            print("status.txt uploaded")

            # Upload index.html
            ftp.storbinary("STOR index.html", io.BytesIO(html_bytes))
            print("index.html uploaded (" + str(len(html_bytes)) + " bytes)")

            # Update status.txt with success flag
            status["ftp_ok"] = True
            ftp.storbinary("STOR status.txt",
                           io.BytesIO(json.dumps(status).encode("utf-8")))

            ftp.quit()
            print("FTP upload done. Live at: https://looreadykpi.cloudtechbookkeeping.com")
            return  # success

        except Exception as e:
            last_error = e
            print("FTP attempt " + str(attempt) + " FAILED: " + str(e))
            if attempt < max_retries:
                wait = 10 * attempt  # 10s, 20s
                print("Retrying in " + str(wait) + "s...")
                time.sleep(wait)

    raise RuntimeError("All " + str(max_retries) +
                       " FTP attempts failed. Last: " + str(last_error))


if __name__ == "__main__":
    print("=== START ===")
    data = load_today_data()
    html, today_str, n1, n2, n3 = update_html(data)
    status = {
        "run": datetime.datetime.utcnow().isoformat(),
        "today": today_str,
        "n1": n1, "n2": n2, "n3": n3,
        "ftp_ok": False
    }
    try:
        ftp_upload(html, status)
    except Exception as e:
        print("ERROR: " + str(e))
        traceback.print_exc()
        sys.exit(1)
    print("=== DONE ===")
