"""
LooReady - Dashboard Builder
Reads today's KPI JSON, patches looready-kpi.html, writes to docs/index.html.
The workflow then commits docs/index.html back to the repo (GitHub Pages).
"""
import json, re, os, sys, datetime, traceback
from pathlib import Path

HTML_FILE = Path("looready-kpi.html")
DATA_DIR  = Path("kpi_data")
DOCS_DIR  = Path("docs")

def load_today_data():
    today = datetime.date.today().isoformat()
    json_path = DATA_DIR / f"{today}.json"
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
    html, n1 = re.subn(r"Live .{1,3} Updated \w+ \d+, \d{4}", "Live . Updated " + today_str, html)
    html, n2 = re.subn(r"Data snapshot: [^\n<]*</div>", "Data snapshot: " + today_str + " . SP-API live pull</div>", html)
    today_obj = (
        "'today': { revenue:'" + revenue + "', units:'" + str(orders) +
        "', spend:'--', acos:'--', sessions:'--', ipi:'628',\n" +
        "            rsub:'Today " + today_str + " . SP-API live'" +
        ", usub:'" + str(orders) + " orders . " + str(units) + " units . Fees $" + f"{fees:,.2f}'" +
        ", ssub:'Not yet available', asub:'Not yet available'" +
        ", sesub:'Not yet available', isub:'Range 570-686',\n" +
        "            acosColor:'#6b7280' }"
    )
    html, n3 = re.subn(r"'today':\s*\{[\s\S]*?\}(?=\s*,)", today_obj, html)
    return html, today_str, n1, n2, n3

def write_docs(html, status):
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")
    (DOCS_DIR / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")

if __name__ == "__main__":
    print("=== START ===")
    data = load_today_data()
    html, today_str, n1, n2, n3 = update_html(data)
    status = {"run": datetime.datetime.utcnow().isoformat(), "today": today_str, "n1": n1, "n2": n2, "n3": n3}
    try:
        write_docs(html, status)
    except Exception as e:
        print("ERROR: " + str(e)); traceback.print_exc(); sys.exit(1)
    print("=== DONE ===")
