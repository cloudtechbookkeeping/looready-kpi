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

TOKEN_URL     = "https://identity.xero.com/connect/token"
CONN_URL      = "https://api.xero.com/connections"
REPORT_URL    = "https://api.xero.com/api.xro/2.0/Reports/ProfitAndLoss"
BS_REPORT_URL = "https://api.xero.com/api.xro/2.0/Reports/BalanceSheet"

# The broad reports scope covers both Profit & Loss and Balance Sheet. If the
# app was only granted the granular P&L scope, we fall back to it so P&L keeps
# working (Balance Sheet is simply skipped in that case).
SCOPE_BROAD = "accounting.reports.read"
SCOPE_PNL   = "accounting.reports.profitandloss.read"
SCOPE       = SCOPE_PNL   # retained for backwards reference

MONTHS_BACK = 12          # current month + previous 11
CURRENCY    = "USD"       # LooReady, LLC base currency (US org)
PARSER_VERSION = 3        # bump to force a re-fetch/re-parse (busts daily cache)


# ── Auth ─────────────────────────────────────────────────────────────────────
def get_access_token():
    """Return (access_token, new_refresh, granted_scope) or (None, None, None).
    Prefers OAuth2 refresh when a refresh token is present; otherwise uses the
    custom-connection client_credentials grant, trying the broad reports scope
    (P&L + Balance Sheet) first and falling back to the granular P&L scope."""
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if REFRESH_TOKEN:
        print("   Auth: OAuth2 refresh_token grant")
        r = requests.post(TOKEN_URL, headers=headers, timeout=30,
                          data={"grant_type": "refresh_token", "refresh_token": REFRESH_TOKEN})
        if r.status_code != 200:
            print(f"   Token request failed: {r.status_code} {r.text[:200]}")
            return None, None, None
        tok = r.json()
        # A refresh grant carries whatever scopes were authorised; assume the
        # broad reports scope is available and let a 403 on the report say otherwise.
        return tok.get("access_token"), tok.get("refresh_token"), "refresh"
    for sc in (SCOPE_BROAD, SCOPE_PNL):
        r = requests.post(TOKEN_URL, headers=headers, timeout=30,
                          data={"grant_type": "client_credentials", "scope": sc})
        if r.status_code == 200:
            print(f"   Auth: client_credentials grant (scope: {sc})")
            return r.json().get("access_token"), None, sc
        print(f"   Token request ({sc}) failed: {r.status_code} {r.text[:120]}")
    return None, None, None


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


def _append_row(rows, r):
    """Append a single Xero data row (Row or SummaryRow) to the flat list."""
    cells = r.get("Cells", [])
    if not cells:
        return
    label = cells[0].get("Value", "")
    value = _num(cells[1].get("Value")) if len(cells) > 1 else None
    if not label and value is None:
        return
    rows.append({
        "t": "summary" if r.get("RowType") == "SummaryRow" else "row",
        "label": label,
        "value": value,
    })


# Headline totals can be labelled differently depending on the org's chart of
# accounts / report layout. LooReady, LLC (US org) uses "Total Revenue",
# "Gross Profit" and "Net Income" as plain rows rather than the UK-style
# "Total Income" / "Net Profit" summary rows, so we match a set of aliases.
INCOME_LABELS = ("total revenue", "total income", "total operating income",
                 "total trading income")
GROSS_LABELS  = ("gross profit",)
NET_LABELS    = ("net income", "net profit")            # exact match preferred
NET_FALLBACK  = ("net income", "net profit")            # substring fallback


def _derive_summary(rows):
    """Pull the headline income / gross profit / net profit figures out of the
    flattened rows, tolerant of US- and UK-style P&L labels."""
    summary = {}
    for r in rows:
        if r.get("t") == "section" or r.get("value") is None:
            continue
        low = (r.get("label") or "").strip().lower()
        val = r["value"]
        if low in INCOME_LABELS:
            summary["income"] = val
        elif low in GROSS_LABELS:
            summary["gross_profit"] = val
        elif low in NET_LABELS:
            summary["net_profit"] = val          # last exact match wins (bottom line)
    if "net_profit" not in summary:
        for r in rows:
            if r.get("t") == "section" or r.get("value") is None:
                continue
            low = (r.get("label") or "").strip().lower()
            if any(t in low for t in NET_FALLBACK):
                summary["net_profit"] = r["value"]
    return summary


def parse_pnl(report):
    """Flatten a single-period Xero ProfitAndLoss report into ordered display
    rows plus the headline summary figures. Handles both section-nested rows
    and top-level Gross Profit / Net Income rows."""
    rows = []
    for section in report.get("Rows", []):
        rtype = section.get("RowType")
        if rtype == "Section":
            title = section.get("Title") or ""
            if title:
                rows.append({"t": "section", "label": title})
            for r in section.get("Rows", []):
                _append_row(rows, r)
        elif rtype in ("Row", "SummaryRow"):
            # Some layouts emit Gross Profit / Net Income as top-level rows.
            _append_row(rows, section)
    summary = _derive_summary(rows)
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


# ── Balance Sheet ────────────────────────────────────────────────────────────
BS_ASSET_LABELS  = ("total assets",)
BS_LIAB_LABELS   = ("total liabilities",)
BS_EQUITY_LABELS = ("total equity",)
BS_NET_LABELS    = ("net assets",)


def _derive_bs_summary(rows):
    """Pull Total Assets / Liabilities / Equity / Net Assets from the flattened
    Balance Sheet rows. Net Assets falls back to Assets − Liabilities."""
    s = {}
    for r in rows:
        if r.get("t") == "section" or r.get("value") is None:
            continue
        low = (r.get("label") or "").strip().lower()
        if low in BS_ASSET_LABELS:
            s["assets"] = r["value"]
        elif low in BS_LIAB_LABELS:
            s["liabilities"] = r["value"]
        elif low in BS_EQUITY_LABELS:
            s["equity"] = r["value"]
        elif low in BS_NET_LABELS:
            s["net_assets"] = r["value"]
    if "net_assets" not in s and "assets" in s and "liabilities" in s:
        s["net_assets"] = round(s["assets"] - s["liabilities"], 2)
    return s


def parse_bs(report):
    """Flatten a single-date Xero BalanceSheet report into ordered display rows
    (Assets / Liabilities / Equity sections) plus the headline totals."""
    rows = []
    for section in report.get("Rows", []):
        rtype = section.get("RowType")
        if rtype == "Section":
            title = section.get("Title") or ""
            if title:
                rows.append({"t": "section", "label": title})
            for r in section.get("Rows", []):
                _append_row(rows, r)
        elif rtype in ("Row", "SummaryRow"):
            _append_row(rows, section)
    return rows, _derive_bs_summary(rows)


def fetch_balance_sheet(token, tenant, as_of):
    """Fetch the Balance Sheet as at a single date (point-in-time position)."""
    r = requests.get(
        BS_REPORT_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Xero-tenant-id": tenant,
            "Accept": "application/json",
        },
        params={"date": as_of},
        timeout=45,
    )
    if r.status_code != 200:
        print(f"   BS {as_of} failed: {r.status_code} {r.text[:160]}")
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
            if (existing.get("generated") == today_str
                    and existing.get("connected")
                    and existing.get("parser_version") == PARSER_VERSION):
                print("   Cache hit - already pulled today")
                return
        except Exception:
            pass

    token, new_refresh, granted_scope = get_access_token()
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

    # Balance Sheet (point-in-time as at each month-end). Only attempted when the
    # broad reports scope was granted; a P&L-only scope simply skips it.
    bs_months, bs_order = {}, []
    if granted_scope in (SCOPE_BROAD, "refresh"):
        for key, label, from_date, to_date in month_windows(MONTHS_BACK):
            rep = fetch_balance_sheet(token, tenant, to_date)
            if not rep:
                continue
            bs_rows, bs_summary = parse_bs(rep)
            if not bs_rows:
                continue
            bs_months[key] = {
                "label": label,
                "date": to_date,        # as-of date (month end, or today for MTD)
                "rows": bs_rows,
                "summary": bs_summary,
            }
            bs_order.append(key)
            na = bs_summary.get("net_assets")
            print(f"   BS {label}: {len(bs_rows)} rows, net assets "
                  f"{na if na is not None else '--'}")
    else:
        print("   Balance Sheet scope not granted - skipping (P&L unaffected)")

    out = {
        "connected": True,
        "generated": today_str,
        "parser_version": PARSER_VERSION,
        "currency": CURRENCY,
        "months_order": order,      # newest first
        "months": months,
    }
    if bs_months:
        out["balance_sheet"] = {"months_order": bs_order, "months": bs_months}
    OUT_FILE.write_text(json.dumps(out))
    print(f"   Saved {OUT_FILE} ({len(months)} P&L months, "
          f"{len(bs_months)} BS months)")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Xero pull crashed (non-fatal):")
        traceback.print_exc()
        # Never fail the build over Xero.
        sys.exit(0)
