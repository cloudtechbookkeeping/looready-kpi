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
        print("No data file for today — history-only mode (backfill run)")
        return None
    with open(json_path) as f:
        return json.load(f)


KNOWN_SKUS = ['LR-TSC-30PACK', 'LR-CS-10', 'LR-CS-30', 'LR-TSC-5PACK', 'LR-CS-120']


def update_html(data):
    # US Eastern time (handles DST automatically)
    import zoneinfo
    et = zoneinfo.ZoneInfo("America/New_York")
    now_et = datetime.datetime.now(tz=et)
    today_str  = now_et.strftime("%B %-d, %Y %-I:%M %p ET")
    date_str   = now_et.strftime("%B %-d, %Y")
    time_str   = now_et.strftime("%-I:%M %p ET")
    revenue   = "$" + f"{data['revenue_today']:,.2f}"
    orders    = data['orders_today']
    units     = data.get('units_ordered', 0)
    fees      = data.get('finance', {}).get('total_fees', 0)
    sku_raw      = data.get('sku_units', {})
    sku_raw_7d   = data.get('sku_units_7d', {})
    revenue_7d   = "$" + f"{data.get('revenue_7d', 0):,.2f}"
    orders_7d    = data.get('orders_7d', 0)
    sku_raw_30d  = data.get('sku_units_30d', {})
    revenue_30d  = "$" + f"{data.get('revenue_30d', 0):,.2f}"
    orders_30d   = data.get('orders_30d', 0)
    units_30d    = data.get('units_30d', 0)   # accurate total from sales metrics API
    acos_val     = data.get("acos")
    ad_spend_val = data.get("ad_spend")
    acos_str     = (f"{acos_val:.1f}%" if acos_val is not None else "--")
    spend_str    = ("$" + f"{ad_spend_val:,.2f}" if ad_spend_val is not None else "--")
    days_30d     = data.get('days_30d', 0)

    html = HTML_FILE.read_text(encoding="utf-8")
    print("HTML len=" + str(len(html)))

    # 1. Live badge date+time (spans: <span>Live</span><span>Updated DATE<br>TIME</span>)
    html, n1 = re.subn(
        r"Updated [^<]+<br>[^<]+",
        "Updated " + date_str + "<br>" + time_str,
        html
    )

    # 2. Data snapshot line
    html, n2 = re.subn(
        r"Data snapshot: [^\n<]*</div>",
        "Data snapshot: " + today_str + " · SP-API live pull</div>",
        html
    )

    # 3. today JS data object — replace placeholder line (no regex, no truncation risk)
    # Build skuUnits JS object: {SKU: count, ...}
    sku_parts = []
    for sku in KNOWN_SKUS:
        val = sku_raw.get(sku, 0)
        sku_parts.append(f"'{sku}':{val}")
    sku_units_js = "{" + ",".join(sku_parts) + "}"
    total_units = sum(sku_raw.get(sku, 0) for sku in KNOWN_SKUS)

    today_obj = (
        "'today': { revenue:'" + revenue +
        "', units:'" + str(total_units) +
        "', spend:" + repr(spend_str) + ", acos:" + repr(acos_str) + ", sessions:'--', ipi:'628'," +
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
        "'7d':  { revenue:'" + revenue_7d +
        "', units:'" + str(total_units_7d) +
        "', spend:" + repr(spend_str) + ", acos:" + repr(acos_str) + ", sessions:'--', ipi:'628'," +
        " rsub:'Last 7 Days · SP-API live'" +
        ", usub:'" + str(orders_7d) + " orders . " + str(total_units_7d) + " units'" +
        ", ssub:'Not yet available', asub:'Not yet available'" +
        ", sesub:'Not yet available', isub:'Range 570-686'," +
        " acosColor:'#6b7280', skuUnits:" + sku_units_js_7d +
        " }, /* 7D_KPI_PLACEHOLDER */"
    )
    placeholder_7d = "'7d':  { revenue:'--', units:'--', spend:'--', acos:'--', sessions:'--', ipi:'628', rsub:'--', usub:'--', ssub:'Not yet available', asub:'Not yet available', sesub:'Not yet available', isub:'Range 570-686', acosColor:'#6b7280', skuUnits:{'LR-TSC-30PACK':'--','LR-CS-10':'--','LR-CS-30':'--','LR-TSC-5PACK':'--','LR-CS-120':'--'} }, /* 7D_KPI_PLACEHOLDER */"
    n4 = 1 if placeholder_7d in html else 0
    html = html.replace(placeholder_7d, sevenday_obj)

    # 5. 30d data object — accumulated from daily files
    sku_parts_30d = []
    for sku in KNOWN_SKUS:
        val = sku_raw_30d.get(sku, 0)
        sku_parts_30d.append(f"'{sku}':{val}")
    sku_units_js_30d = "{" + ",".join(sku_parts_30d) + "}"
    days_label = str(days_30d) + " days SKU data" if days_30d < 30 else "Last 30 Days"

    thirtyday_obj = (
        "'30d': { revenue:'" + revenue_30d +
        "', units:'" + str(units_30d) +
        "', spend:" + repr(spend_str) + ", acos:" + repr(acos_str) + ", sessions:'--', ipi:'628'," +
        " rsub:'Last 30 Days · SP-API live'" +
        ", usub:'" + str(orders_30d) + " orders . " + str(units_30d) + " units'" +
        ", ssub:'Not yet available', asub:'Not yet available'" +
        ", sesub:'Not yet available', isub:'Range 570-686'," +
        " acosColor:'#6b7280', skuUnits:" + sku_units_js_30d +
        ", days30d:" + str(days_30d) +
        " }, /* 30D_KPI_PLACEHOLDER */"
    )
    placeholder_30d = "'30d': { revenue:'--', units:'--', spend:'--', acos:'--', sessions:'--', ipi:'628', rsub:'--', usub:'--', ssub:'Not yet available', asub:'Not yet available', sesub:'Not yet available', isub:'Range 570-686', acosColor:'#6b7280', skuUnits:{'LR-TSC-30PACK':'--','LR-CS-10':'--','LR-CS-30':'--','LR-TSC-5PACK':'--','LR-CS-120':'--'}, days30d:30 }, /* 30D_KPI_PLACEHOLDER */"
    n5 = 1 if placeholder_30d in html else 0
    html = html.replace(placeholder_30d, thirtyday_obj)

    # 6. Inventory data — build per-SKU JS object
    fba_inv  = data.get("fba_inventory", {})
    awd_inv  = data.get("awd_inventory", {})
    inv_parts = []
    for sku in KNOWN_SKUS:
        fba = fba_inv.get(sku, {})
        awd = awd_inv.get(sku, {})
        inv_parts.append(
            f"'{sku}':{{fba:{{fulfillable:{fba.get('fulfillable',0)},"
            f"inbound:{fba.get('inbound',0)},"
            f"reserved:{fba.get('reserved',0)},"
            f"researching:{fba.get('researching',0)},"
            f"unfulfillable:{fba.get('unfulfillable',0)}}},"
            f"awd:{{onhand:{awd.get('onhand',0)},"
            f"inbound:{awd.get('inbound',0)},"
            f"outbound:{awd.get('outbound',0)}}}}}"
        )
    inv_js = "{" + ",".join(inv_parts) + "}"
    placeholder_inv = "{ /* INVENTORY_PLACEHOLDER */ }"
    n6 = 1 if placeholder_inv in html else 0
    html = html.replace(placeholder_inv, inv_js)

    # 7. Write inventory totals directly into mini-stat HTML elements
    inv_el_map = [
        ('LR-TSC-30PACK', 'inv-30pack',  False),
        ('LR-CS-10',      'inv-cs10',    False),
        ('LR-CS-30',      'inv-cs30',    False),
        ('LR-TSC-5PACK',  'inv-5pack',   False),
        ('LR-CS-120',     'inv-cs120',   True),
    ]
    for sku, el_id, suppressed in inv_el_map:
        fba = fba_inv.get(sku, {})
        awd = awd_inv.get(sku, {})
        total = (fba.get('fulfillable', 0) + fba.get('inbound', 0) +
                 fba.get('reserved', 0) + fba.get('researching', 0) +
                 fba.get('unfulfillable', 0) + awd.get('onhand', 0) + awd.get('inbound', 0))
        new_text  = f"{total:,} (Suppressed)" if suppressed else f"{total:,} units"
        old_text  = "-- (Suppressed)"         if suppressed else "-- units"
        old_frag  = f'id="{el_id}">{old_text}'
        new_frag  = f'id="{el_id}">{new_text}'
        html = html.replace(old_frag, new_frag)
        print(f"inv {el_id}: {old_text} -> {new_text}")

    print("n1=" + str(n1) + " n2=" + str(n2) + " n3=" + str(n3) + " n4=" + str(n4) + " n5=" + str(n5) + " n6=" + str(n6))
    if n1 == 0 or n2 == 0 or n3 == 0 or n4 == 0 or n5 == 0 or n6 == 0:
        print("WARNING: one or more patterns did not match!")
    return html, today_str, n1, n2, n3


def write_history():
    """Write docs/kpi_history.json with all available daily data for custom date range feature."""
    history = []
    for path in sorted(DATA_DIR.glob("*.json")):
        name = path.stem
        if "cache" in name:
            continue
        try:
            with open(path) as f:
                d = json.load(f)
            if "date" not in d:
                continue
            history.append({
                "date":      d.get("date"),
                "revenue":   d.get("revenue_today", 0),
                "orders":    d.get("orders_today", 0),
                "units":     d.get("units_ordered", 0),
                "sku_units": d.get("sku_units", {}),
                "acos":      d.get("acos"),
                "ad_spend":  d.get("ad_spend"),
                "ad_clicks": d.get("ad_clicks"),
                "ad_orders": d.get("ad_orders"),
            })
        except Exception as e:
            print("Skipping " + str(path) + ": " + str(e))
    history.sort(key=lambda x: x["date"])
    out_path = DOCS_DIR / "kpi_history.json"
    out_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    print("Wrote docs/kpi_history.json (" + str(len(history)) + " days)")


def write_docs(html, status):
    DOCS_DIR.mkdir(exist_ok=True)
    index_path = DOCS_DIR / "index.html"
    index_path.write_text(html, encoding="utf-8")
    print("Wrote docs/index.html (" + str(len(html)) + " chars)")

    status_path = DOCS_DIR / "status.json"
    status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print("Wrote docs/status.json")

    write_history()


if __name__ == "__main__":
    print("=== START ===")
    data = load_today_data()
    if data is None:
        # No today data — backfill run: just regenerate kpi_history.json
        print("History-only mode: writing kpi_history.json without rebuilding index.html")
        DOCS_DIR.mkdir(exist_ok=True)
        write_history()
        status = {"run": datetime.datetime.utcnow().isoformat(), "note": "history-only backfill run"}
        (DOCS_DIR / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
        print("=== DONE (history only) ===")
    else:
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
