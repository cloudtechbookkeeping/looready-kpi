"""
LooReady - Dashboard Builder & Hostinger FTP Uploader
"""
import json, re, os, sys, ftplib, io, datetime, traceback
from pathlib import Path

FTP_HOST = os.environ.get("FTP_HOST", "145.79.209.123")
FTP_USER = os.environ.get("FTP_USER", "u133013644")
FTP_PASS = os.environ["FTP_PASS"]
FTP_PORT = 21
FTP_REMOTE_PATH = "/public_html/looreadykpi/index.html"
HTML_FILE = Path("looready-kpi.html")
DATA_DIR  = Path("kpi_data")

def load_today_data():
    today = datetime.date.today().isoformat()
    json_path = DATA_DIR / (today + ".json")
    print("Data file: " + str(json_path) + " exists=" + str(json_path.exists()))
    if not json_path.exists():
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

    html, n1 = re.subn(
        r"Live .{1,3} Updated \w+ \d+, \d{4}",
        "Live . Updated " + today_str, html
    )
    html, n2 = re.subn(
        r"Data snapshot: [^\n<]*</div>",
        "Data snapshot: " + today_str + " . SP-API live pull</div>", html
    )
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
    return html, today_str, n1, n2, n3

def ftp_upload_all(html_content, status):
    remote_dir = "/public_html/looreadykpi"
    print("FTP connect " + FTP_HOST)
    with ftplib.FTP() as ftp:
        ftp.connect(FTP_HOST, FTP_PORT, timeout=30)
        ftp.login(FTP_USER, FTP_PASS)
        print("FTP login OK")
        # List root to confirm connection
        ftp.cwd("/")
        dirs = ftp.nlst()
        print("FTP root dirs: " + str(dirs[:10]))
        # Navigate to target dir
        try:
            ftp.cwd(remote_dir)
            print("CWD OK: " + remote_dir)
        except ftplib.error_perm as e:
            print("CWD failed: " + str(e) + " - trying to create")
            ftp.mkd(remote_dir)
            ftp.cwd(remote_dir)
        # List what's already there
        existing = ftp.nlst()
        print("Existing files: " + str(existing))
        # Upload status.txt FIRST
        ftp.storbinary("STOR status.txt", io.BytesIO(json.dumps(status).encode("utf-8")))
        print("status.txt uploaded")
        # Upload index.html
        data = html_content.encode("utf-8")
        ftp.storbinary("STOR index.html", io.BytesIO(data))
        print("index.html uploaded (" + str(len(data)) + " bytes)")
        status["ftp_ok"] = True
        ftp.storbinary("STOR status.txt", io.BytesIO(json.dumps(status).encode("utf-8")))

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
        ftp_upload_all(html, status)
    except Exception as e:
        print("ERROR: " + str(e))
        traceback.print_exc()
        sys.exit(1)
    print("=== DONE ===")
