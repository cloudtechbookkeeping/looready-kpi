"""
LooReady - Dashboard Builder & Hostinger FTP Uploader
Reads today's KPI JSON, patches looready-kpi.html, uploads via FTP.
FTP credentials come from environment variables (GitHub Secrets).
"""

import json
import re
import os
import sys
import ftplib
import io
import datetime
from pathlib import Path

# -- FTP credentials from GitHub Secrets -------------------------------------
FTP_HOST = os.environ.get("FTP_HOST", "145.79.209.123")
FTP_USER = os.environ.get("FTP_USER", "u133013644")
FTP_PASS = os.environ["FTP_PASS"]
FTP_PORT = 21
FTP_REMOTE_PATH = "/public_html/looreadykpi/index.html"
# ----------------------------------------------------------------------------

HTML_FILE = Path("looready-kpi.html")
DATA_DIR  = Path("kpi_data")


def load_today_data():
    today = datetime.date.today().isoformat()
    json_path = DATA_DIR / f"{today}.json"
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

    # 1. Live badge date - match "Live <sep> Updated <date>" without crossing newlines
    html, n1 = re.subn(
        r"Live .{1,3} Updated \w+ \d+, \d{4}",
        "Live . Updated " + today_str,
        html
    )

    # 2. Data snapshot line - [^\n<]* stays on one line
    html, n2 = re.subn(
        r"Data snapshot: [^\n<]*</div>",
        "Data snapshot: " + today_str + " . SP-API live pull</div>",
        html
    )

    # 3. today JS data object - [\s\S]*? matches across newlines safely
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
    html, n3 = re.subn(
        r"'today':\s*\{[\s\S]*?\}(?=\s*,)",
        today_obj,
        html
    )

    print("Regex matches: live=" + str(n1) + ", snapshot=" + str(n2) + ", today=" + str(n3))
    if n1 == 0 or n2 == 0 or n3 == 0:
        print("WARNING: one or more patterns did not match the HTML!")
    print("HTML updated - " + revenue + ", " + str(orders) + " orders")
    return html


def ftp_makedirs(ftp, path):
    """Create remote directory tree, ignoring errors if it already exists."""
    parts = [p for p in path.split("/") if p]
    current = ""
    for part in parts:
        current += "/" + part
        try:
            ftp.mkd(current)
        except ftplib.error_perm:
            pass  # already exists


def ftp_upload(html_content):
    print("Uploading to Hostinger...")
    ftp = ftplib.FTP()
    ftp.connect(FTP_HOST, FTP_PORT, timeout=30)
    ftp.login(FTP_USER, FTP_PASS)

    remote_dir  = "/".join(FTP_REMOTE_PATH.split("/")[:-1])
    remote_file = FTP_REMOTE_PATH.split("/")[-1]

    ftp_makedirs(ftp, remote_dir)
    ftp.cwd(remote_dir)
    ftp.storbinary("STOR " + remote_file, io.BytesIO(html_content.encode("utf-8")))
    ftp.quit()
    print("Live at: https://looreadykpi.cloudtechbookkeeping.com")


if __name__ == "__main__":
    print("LooReady Dashboard Builder")
    print("=" * 40)
    data = load_today_data()
    html = update_html(data)
    ftp_upload(html)
    print("Done!")
