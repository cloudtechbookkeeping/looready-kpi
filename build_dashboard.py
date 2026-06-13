"""
LooReady - Dashboard Builder
Reads today's KPI JSON, patches looready-kpi.html, writes to docs/index.html.
The workflow then commits docs/index.html back to the repo (GitHub Pages).
"""

import json
import re
import os
import sys
import datetime
import traceback
from pathlib import Path

HTML_FILE = Path("looready-kpi.html")
DATA_DIR  = Path("kpi_data")
DOCS_DIR  = Path("docs")


def load_today_data():
    today = datetime.date.today().isoformat()
    json_path = DATA_DIR / f"{today}.json"
    print("Data file: " + str(json_path) + " exists=" + str(json_path.exists()))
    if not json_path.exists():
        print("No data file for today: " + str(json_path))
        sys.exit(1)
    with open(json_path) as f:
        return json.load(f)


KNOWN_SKUS = ['LR-TSC-30PACK', 'LR-CS-10', 'LR-CS-30', 'LR-TSC-5PACK', 'LR-CS-120']


def update_html(data):
    today_str = datetime.date.today().strftime("%B %-d, %Y")
    revenue   = "$" + f"{data['revenue_today']:,.2f}"
    orders    = data['orders_today']
    units     = data.get('units_ordered', 0)
    fees      = data.get('finance', {}).get('total_fees', 0)
    sku_raw    = data.get('sku_units', {})
    sku_raw_7d = data.get('sku_units_7d', {})

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
        r"Data snapshot: [^\n<]*<\/div>",
        "Data snapshot: " + today_str + " . SP-API live pull<\/div>",
        html
    )

    # 3. today JS data object — replace placeholder line
    sku_parts = []
    for sku in KNOWN_SKUS:
        val = sku_raw.get(sku, 0)
        sku_parts.append(f"'{sku}':{val}")
    sku_units_js = "{" + ",".join(sku_parts) + "}"
    total_units = sum(sku_raw.get(sku, 0) for sku in KNOWN_SKUS)

    today_obj = (
        "'today': { revenue:'" + revenue +
        "', units:'" + str(total_units) +
        "', spend:'--', acos:'--', sessions:'--', ipi:'628'," +
        " rsub:'Today " + today_str + " . SP-API live'" +
        ", usub:'" + str(orders) + " orders . " + str(units) +
        " units . Fees $" + f"{fees:,.2f}'" +
        ", ssub:'Not yet available', asub:'Not yet available'" +
        ", sesub:'Not yet available', isub:'Range 570-686'," +
        " acosColor:'#6b7280', skuUnits:" + sku_units_js +
        " }, /* TODAY_KPI_PLACEHOLDER */"
    )
    placeholder = "'today': { revenue:'--', units:'--', spend:'--', acos:'--', sessions:'--', ipi:'628', rsub:'--', usub:'--', ssub:'Not yet available', asub:'Not yet available', sesub:'Not yet available', isub:'Range 570-686', acosColor:'#6b7280', skuUnits:{'LR-TSC-30PACK':'--','LR-CS-10':'--','LR-CS-30':'--','LR-TSC-5PACK':'--','LR-CS-120':'--'} }, /* TODAY_KPI_PLACEHOLDER */"
    n3 = 1 if placeholder in html else 0
    html = html.replace(placeholder, today_obj)

    # 4. 7d SKU data object — replace placeholder
    sku_parts_7d = []
    for sku in KNOWN_SKUS:
        val = sku_raw_7d.get(sku, 0)
        sku_parts_7d.append(f"'{sku}':{val}")
    sku_units_js_7d = "{" + ",".join(sku_parts_7d) + "}"
    total_units_7d = sum(sku_raw_7d.get(sku, 0) for sku in KNOWN_SKUS)

    sevenday_obj = (
        "'7d':  { revenue:'$3,131', units:'" + str(total_units_7d) +
        "', spend:'~$3,017', acos:'~96.5%', sessions:'~1,727', ipi:'628'," +
        " rsub:'Ad Sales · May 23–29', usub:'NTB purchases: 51'," +
        " ssub:'May 23–29 (estimated)', asub:'May 23–29 (estimated)'," +
        " sesub:'Estimated', isub:'Range 570–686'," +
        " acosColor:'#dc2626', skuUnits:" + sku_units_js_7d +
        " }, /* 7D_KPI_PLACEHOLDER */"
    )
    placeholder_7d = "'7d':  { revenue:'$3,131', units:'51', spend:'~$3,017', acos:'~96.5%', sessions:'~1,727', ipi:'628', rsub:'Ad Sales · May 23–29', usub:'NTB purchases: 51', ssub:'May 23–29 (estimated)', asub:'May 23–29 (estimated)', sesub:'Estimated', isub:'Range 570–686', acosColor:'#dc2626', skuUnits:{'LR-TSC-30PACK':'--','LR-CS-10':'--','LR-CS-30':'--','LR-TSC-5PACK':'--','LR-CS-120':'--'} }, /* 7D_KPI_PLACEHOLDER */"
    n4 = 1 if placeholder_7d in html else 0
    html = html.replace(placeholder_7d, sevenday_obj)

    print("n1=" + str(n1) + " n2=" + str(n2) + " n3=" + str(n3) + " n4=" + str(n4))
    if n1 == 0 or n2 == 0 or n3 == 0 or n4 == 0:
        print("WARNING: one or more patterns did not match!")
    return html, today_str, n1, n2, n3


def write_docs(html, status):
    DOCS_DIR.mkdir(exist_ok=True)
    index_path = DOCS_DIR / "index.html"
    index_path.write_text(html, encoding="utf-8")
    print("Wrote docs/index.html (" + str(len(html)) + " chars)")

    status_path = DOCS_DIR / "status.json"
    status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print("Wrote docs/status.json")


if __name__ == "__main__":
    print("=== START ===")
    data = load_today_data()
    html, today_str, n1, n2, n3 = update_html(data)
    status = {
        "run": datetime.datetime.utcnow().isoformat(),
        "today": today_str,
        "n1": n1, "n2": n2, "n3": n3,
    }
    try:
        write_docs(html, status)
    except Exception as e:
        print("ERROR: " + str(e))
        traceback.print_exc()
        sys.exit(1)
    print("=== DONE ===")
