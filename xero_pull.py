"""
LooReady - Xero Profit & Loss pull.

Fetches the Profit and Loss report per calendar month from the Xero
Accounting API and writes kpi_data/xero_pnl.json for build_dashboard.py to
inject into the "Financial Reports" tab.

Auth (auto-detected from env, set as GitHub Secrets):
  * Custom Connection (recommended): XERO_CLIENT_ID + XERO_CLIENT_SECRET
      -> client_credentials grant, no user login, no token rotation.
  * Standard OAuth2 (fallback): XERO_CLIENT_ID + XERO_CLIENT_SECRET
      + XERO_REFRESH_TOKEN  -> refresh_token grant.
  * XERO_TENANT_ID is optional; if unset it is read from /connections.

Everything here is non-fatal: on missing credentials or any API error the
script leaves any existing xero_pnl.json untouched (or writes an empty
"not connected" stub) so the dashboard simply shows a connect-Xero state and
the rest of the build is unaffected.
"""

import base64
import calendar
import datetime
import json
import os
import sys
import traceback
from pathlib import Path

import requests

DATA_DIR = Path("kpi_data")
DATA_DIR.mkdir(exist_ok=True)
OUT_FILE = DATA_DIR / "xero_pnl.json"

CLIENT_ID     = os.environ.get("XERO_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("XERO_CLIENT_SECRET", "").strip()
REFRESH_TOKEN = os.environ.get("XERO_REFRESH_TOKEN", "").strip()
TENANT_ID     = os.environ.get("XERO_TENANT_ID", "").strip()

TOKEN_URL   = "https://identity.xero.com/connect/token"
CONN_URL    = "https://api.xero.com/connections"
REPORT_URL  = "https://api.xero.com/api.xro/2.0/Reports/ProfitAndLoss"
SCOPE       = "accounting.reports.profitandloss.read"

MONTHS_BACK = 12          # current month + previous 11
CURRENCY    = "USD"       # LooReady, LLC base currency (US org)


# ── Auth ─────────────────────────────────────────────────────────────────────
def get_access_token():
    """Return a bearer access token, or None. Prefers OAuth2 refresh when a
    refresh token is present, otherwise uses the custom-connection
    client_credentials grant."""
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if REFRESH_TOKEN:
        print("   Auth: OAuth2 refresh_token grant")
        body = {"grant_type": "refresh_token", "refresh_token": REFRESH_TOKEN}
    else:
        print("   Auth: client_credentials grant (custom connection)")
        body = {"grant_type": "client_credentials", "scope": SCOPE}
    r = requests.post(TOKEN_URL, headers=headers, data=body, timeout=30)
    if r.status_code != 200:
        print(f"   Token request failed: {r.status_code} {r.text[:200]}")
        return None, None
    tok = r.json()
    new_refresh = tok.get("refresh_token")  # only present on refresh grant
    return tok.get("access_token"), new_refresh


def get_tenant_id(token):
    if TENANT_ID:
        return TENANT_ID
    r = requests.get(
        CONN_URL,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"   /connections failed: {r.status_code} {r.text[:200]}")
        return None
    conns = r.json()
    if not conns:
        print("   No Xero connections found for this app")
        return None
    return conns[0].get("tenantId")


# ── Report parsing ───────────────────────────────────────────────────────────
def _num(v):
    try:
        return round(float(str(v).replace(",", "")), 2)
    except (TypeError, ValueError):
        return None


def parse_pnl(report):
    """Flatten a single-period Xero ProfitAndLoss report into ordered display
    rows plus the headline summary figures."""
    rows, summary = [], {}
    for section in report.get("Rows", []):
        if section.get("RowType") != "Section":
            continue
        title = section.get("Title") or ""
        if title:
            rows.append({"t": "section", "label": title})
        for r in section.get("Rows", []):
            cells = r.get("Cells", [])
            if not cells:
                continue
            label = cells[0].get("Value", "")
            value = _num(cells[1].get("Value")) if len(cells) > 1 else None
            is_summary = r.get("RowType") == "SummaryRow"
            rows.append({
                "t": "summary" if is_summary else "row",
                "label": label,
                "value": value,
            })
            low = label.lower()
            if is_summary:
                if "net profit" in low:
                    summary["net_profit"] = value
                elif "gross profit" in low:
                    summary["gross_profit"] = value
                elif low.startswith("total income") or "total operating income" in low:
                    summary["income"] = value
    return rows, summary


def month_windows(n):
    """Yield (key, label, fromDate, toDate) for the last n months, newest first.
    The current month runs to today (month-to-date)."""
    today = datetime.date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        first = datetime.date(y, m, 1)
        last_day = calendar.monthrange(y, m)[1]
        last = datetime.date(y, m, last_day)
        to_date = min(last, today)
        out.append((
            first.strftime("%Y-%m"),
            first.strftime("%B %Y"),
            first.isoformat(),
            to_date.isoformat(),
        ))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return out


def fetch_month(token, tenant, from_date, to_date):
    r = requests.get(
        REPORT_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Xero-tenant-id": tenant,
            "Accept": "application/json",
        },
        params={"fromDate": from_date, "toDate": to_date},
        timeout=45,
    )
    if r.status_code != 200:
        print(f"   P&L {from_date}..{to_date} failed: {r.status_code} {r.text[:160]}")
        return None
    reports = r.json().get("Reports", [])
    return reports[0] if reports else None


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("Xero P&L pull -", datetime.date.today().isoformat())

    if not (CLIENT_ID and CLIENT_SECRET):
        print("   XERO_CLIENT_ID / XERO_CLIENT_SECRET not set - skipping "
              "(dashboard will show a connect-Xero state).")
        if not OUT_FILE.exists():
            OUT_FILE.write_text(json.dumps({"connected": False, "months": {}}))
        return

    # Daily cache: P&L changes slowly; avoid refetching every hourly run.
    today_str = datetime.date.today().isoformat()
    if OUT_FILE.exists():
        try:
            existing = json.loads(OUT_FILE.read_text())
            if existing.get("generated") == today_str and existing.get("connected"):
                print("   Cache hit - already pulled today")
                return
        except Exception:
            pass

    token, new_refresh = get_access_token()
    if not token:
        print("   Could not obtain access token - leaving existing data as-is")
        if not OUT_FILE.exists():
            OUT_FILE.write_text(json.dumps({"connected": False, "months": {}}))
        return
    if new_refresh and new_refresh != REFRESH_TOKEN:
        # OAuth2 refresh tokens rotate; surface it so the secret can be updated.
        print("   NOTE: a new refresh token was issued (rotated). Update "
              "XERO_REFRESH_TOKEN if using the OAuth2 flow.")

    tenant = get_tenant_id(token)
    if not tenant:
        print("   No tenant id - is the org connected/authorised yet?")
        if not OUT_FILE.exists():
            OUT_FILE.write_text(json.dumps({"connected": False, "months": {}}))
        return
    print(f"   Tenant: {tenant}")

    months, order = {}, []
    for key, label, from_date, to_date in month_windows(MONTHS_BACK):
        report = fetch_month(token, tenant, from_date, to_date)
        if not report:
            continue
        rows, summary = parse_pnl(report)
        if not rows:
            continue
        months[key] = {
            "label": label,
            "from": from_date,
            "to": to_date,
            "rows": rows,
            "summary": summary,
        }
        order.append(key)
        np = summary.get("net_profit")
        print(f"   {label}: {len(rows)} rows, net profit "
              f"{np if np is not None else '--'}")

    if not months:
        print("   No P&L data returned - leaving existing data as-is")
        if not OUT_FILE.exists():
            OUT_FILE.write_text(json.dumps({"connected": False, "months": {}}))
        return

    out = {
        "connected": True,
        "generated": today_str,
        "currency": CURRENCY,
        "months_order": order,      # newest first
        "months": months,
    }
    OUT_FILE.write_text(json.dumps(out))
    print(f"   Saved {OUT_FILE} ({len(months)} months)")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Xero pull crashed (non-fatal):")
        traceback.print_exc()
        # Never fail the build over Xero.
        sys.exit(0)
