"""
LooReady — Dashboard Builder & Hostinger FTP Uploader
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

# ── FTP credentials from GitHub Secrets ──────────────────────────────────────
FTP_HOST = os.environ.get("FTP_HOST", "145.79.209.123")
FTP_USER = os.environ.get("FTP_USER", "u133013644")
FTP_PASS = os.environ["FTP_PASS"]
FTP_PORT = 21
FTP_REMOTE_PATH = "/public_html/looreadykpi/index.html"
# ─────────────────────────────────────────────────────────────────────────────

HTML_FILE = Path("looready-kpi.html")
DATA_DIR  = Path("kpi_data")


def load_today_data():
        today = datetime.date.today().isoformat()
        json_path = DATA_DIR / f"{today}.json"
        if not json_path.exists():
                    print(f"❌ No data file for today: {json_path}")
                    sys.exit(1)
                with open(json_path) as f:
                            return json.load(f)


def update_html(data):
        today_str = datetime.date.today().strftime("%B %-d, %Y")
    revenue   = f"${data['revenue_today']:,.2f}"
    orders    = data['orders_today']
    units     = data.get('units_ordered', 0)
    fees      = data.get('finance', {}).get('total_fees', 0)

    html = HTML_FILE.read_text(encoding="utf-8")

    html = re.sub(r"Live · Updated .+?<", f"Live · Updated {today_str}<", html)
    html = re.sub(
                r"Data snapshot: .+?</div>",
                f"Data snapshot: {today_str} · SP-API live pull</div>",
                html
    )
    html = re.sub(
                r"'today':\s*\{[^}]+\}",
                f"'today': {{ revenue:'{revenue}', units:'{orders}', spend:'—', acos:'—', sessions:'—', ipi:'628', "
                f"rsub:'Today {today_str} · SP-API live', usub:'{orders} orders · {units} units · Fees ${fees:,.2f}', "
                f"ssub:'Not yet available', asub:'Not yet available', sesub:'Not yet available', isub:'Range 570–686'}}",
                html
    )

    print(f"✅ HTML updated — {revenue}, {orders} orders")
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
        print(f"📤 Uploading to Hostinger...")
    ftp = ftplib.FTP()
    ftp.connect(FTP_HOST, FTP_PORT, timeout=30)
    ftp.login(FTP_USER, FTP_PASS)

    remote_dir  = "/".join(FTP_REMOTE_PATH.split("/")[:-1])
    remote_file = FTP_REMOTE_PATH.split("/")[-1]

    # Ensure the remote directory exists
    ftp_makedirs(ftp, remote_dir)
    ftp.cwd(remote_dir)
    ftp.storbinary(f"STOR {remote_file}", io.BytesIO(html_content.encode("utf-8")))
    ftp.quit()
    print(f"✅ Live at: https://looreadykpi.cloudtechbookkeeping.com")


if __name__ == "__main__":
        print("\n🔄 LooReady Dashboard Builder")
    print("=" * 40)
    data = load_today_data()
    html = update_html(data)
    ftp_upload(html)
    print("\n🎉 Done!")
