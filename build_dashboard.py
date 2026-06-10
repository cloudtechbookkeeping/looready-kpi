"""
LooReady - Dashboard Builder & Hostinger FTP Uploader
Reads today's KPI JSON, patches looready-kpi.html, uploads via FTP.
FTP credentials come from environment variables (GitHub Secrets).
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
    print("Looking for data file: " + str(json_path))
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
    print("Today: " + today_str + ", Revenue: " + revenue + ", Orders: " + str(orders))
    print("Units: " + str(units) + ", Fees: " + str(fees))

    if not HTML_FILE.exists():
        print("ERROR: " + str(HTML_FILE) + " not found!")
        sys.exit(1)
    html = HTML_FILE.read_text(encoding="utf-8")
    print("HTML file length: " + str(len(html)))

    # 1. Live badge date
    html, n1 = re.subn(
        r"Live .{1,3} Updated \w+ \d+, \d{4}",
        "Live . Updated " + today_str, html
    )
    # 2. Data snapshot line
    html, n2 = re.subn(
        r"Data snapshot: [^\n<]*</div>",
        "Data snapshot: " + today_str + " . SP-API live pull</div>", html
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
    print("Regex matches: live=" + str(n1) + ", snapshot=" + str(n2) + ", today=" + str(n3))
    if n1 == 0 or n2 == 0 or n3 == 0:
        print("WARNING: one or more patterns did not match!")
        idx1 = html.find('Live')
        if idx1 >= 0:
            print("Live context: " + repr(html[max(0,idx1-5):idx1+60]))
        idx2 = html.find('Data snapshot:')
        if idx2 >= 0:
            print("Snapshot context: " + repr(html[idx2-2:idx2+90]))
        idx3 = html.find("'today':")
        if idx3 >= 0:
            print("Today context: " + repr(html[idx3:idx3+130]))
    idx = html.find('Updated')
    if idx >= 0:
        print("Updated line: " + repr(html[max(0,idx-10):idx+50]))
    return html

def ftp_makedirs(ftp, remote_dir):
    parts = [p for p in remote_dir.split("/") if p]
    path  = "/"
    for part in parts:
        path = path + part + "/"
        try:
            ftp.cwd(path)
        except ftplib.error_perm:
            print("Creating FTP dir: " + path)
            ftp.mkd(path)
            ftp.cwd(path)

def ftp_upload(html_content):
    remote_dir  = "/".join(FTP_REMOTE_PATH.split("/")[:-1])
    remote_file = FTP_REMOTE_PATH.split("/")[-1]
    print("FTP connecting to " + FTP_HOST + ":" + str(FTP_PORT) + " as " + FTP_USER)
    with ftplib.FTP() as ftp:
        ftp.connect(FTP_HOST, FTP_PORT, timeout=30)
        ftp.login(FTP_USER, FTP_PASS)
        print("FTP login OK")
        ftp_makedirs(ftp, remote_dir)
        data = html_content.encode("utf-8")
        ftp.storbinary("STOR " + remote_file, io.BytesIO(data))
        print("FTP upload OK: " + FTP_REMOTE_PATH + " (" + str(len(data)) + " bytes)")

if __name__ == "__main__":
    print("=== build_dashboard.py starting ===")
    try:
        data = load_today_data()
        print("Data keys: " + str(list(data.keys())))
        html = update_html(data)
        try:
            ftp_upload(html)
        except Exception as ftp_err:
            print("FTP ERROR: " + str(ftp_err))
            traceback.print_exc()
            sys.exit(1)
        print("=== Dashboard updated successfully! ===")
    except SystemExit:
        raise
    except Exception as e:
        print("FATAL ERROR: " + str(e))
        traceback.print_exc()
        sys.exit(1)
