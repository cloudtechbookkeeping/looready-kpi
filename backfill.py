"""
LooReady — Historical Data Backfill
Fetches daily KPI data for a past date range and saves to kpi_data/.
Run via GitHub Actions workflow_dispatch with start_date and end_date inputs.

Usage:
  python backfill.py --start 2026-01-01 --end 2026-01-31

Skips dates that already have data files.
"""

import argparse
import datetime
import json
import os
import time
import traceback
from pathlib import Path

import requests

# ── Credentials from GitHub Secrets ──────────────────────────────────────────
CLIENT_ID      = os.environ["AMAZON_CLIENT_ID"]
CLIENT_SECRET  = os.environ["AMAZON_CLIENT_SECRET"]
REFRESH_TOKEN  = os.environ["AMAZON_REFRESH_TOKEN"]
MARKETPLACE_ID = "ATVPDKIKX0DER"
ENDPOINT       = "https://sellingpartnerapi-na.amazon.com"

DATA_DIR = Path("kpi_data")
DATA_DIR.mkdir(exist_ok=True)


def get_access_token():
    resp = requests.post(
        "https://api.amazon.com/auth/o2/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": REFRESH_TOKEN,
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        }
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def sp_request(token, method, path, params=None):
    url = ENDPOINT + path
    headers = {
        "x-amz-access-token": token,
        "x-amz-date": datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
        "content-type": "application/json",
    }
    resp = requests.request(method, url, headers=headers, params=params)
    if resp.status_code == 429:
        print("   ⏳ Rate limited — sleeping 10s...")
        time.sleep(10)
        resp = requests.request(method, url, headers=headers, params=params)
    return resp


def get_orders_for_day(token, date_str):
    """Fetch all orders for a single calendar day (UTC)."""
    after  = date_str + "T00:00:00Z"
    before = date_str + "T23:59:59Z"
    params = {
        "MarketplaceIds": MARKETPLACE_ID,
        "CreatedAfter":   after,
        "CreatedBefore":  before,
        "OrderStatuses":  "Shipped,Unshipped,PartiallyShipped",
    }
    all_orders = []
    page = 0
    while True:
        resp = sp_request(token, "GET", "/orders/v0/orders", params)
        if resp.status_code != 200:
            print(f"   ⚠️ Orders page {page} → {resp.status_code}: {resp.text[:200]}")
            break
        payload = resp.json().get("payload", {})
        batch = payload.get("Orders", [])
        all_orders.extend(batch)
        page += 1
        next_token = payload.get("NextToken")
        if not next_token:
            break
        params = {"NextToken": next_token, "MarketplaceIds": MARKETPLACE_ID}
        time.sleep(1)
    return all_orders


def get_order_items(token, order_id):
    resp = sp_request(token, "GET", f"/orders/v0/orders/{order_id}/orderItems")
    if resp.status_code != 200:
        print(f"   ⚠️ OrderItems {order_id} → {resp.status_code}")
        return []
    return resp.json().get("payload", {}).get("OrderItems", [])


def get_sku_breakdown(token, orders):
    sku_units = {}
    total = len(orders)
    for i, order in enumerate(orders):
        order_id = order.get("AmazonOrderId")
        if not order_id:
            continue
        items = get_order_items(token, order_id)
        for item in items:
            sku = item.get("SellerSKU", "Unknown")
            qty = int(item.get("QuantityOrdered", 0))
            sku_units[sku] = sku_units.get(sku, 0) + qty
        time.sleep(2)   # 0.5 req/s sustained rate limit
        if (i + 1) % 10 == 0:
            print(f"   ... {i+1}/{total} orders processed")
    return sku_units


def get_units_for_day(token, date_str):
    """Get total units ordered for a single day via sales metrics."""
    after  = date_str + "T00:00:00Z"
    before = date_str + "T23:59:59Z"
    resp = sp_request(token, "GET", "/sales/v1/orderMetrics", {
        "marketplaceIds":      MARKETPLACE_ID,
        "interval":            f"{after}--{before}",
        "granularity":         "TOTAL",
        "granularityTimeZone": "US/Pacific",
    })
    if resp.status_code != 200:
        print(f"   ⚠️ Sales metrics → {resp.status_code}: {resp.text[:200]}")
        return 0
    payload = resp.json().get("payload", [])
    return payload[0].get("unitCount", 0) if payload else 0


def backfill_day(token, date_str):
    save_path = DATA_DIR / f"{date_str}.json"
    if save_path.exists():
        print(f"   ⏭️  {date_str} already exists — skipping")
        return

    print(f"\n📅 Backfilling {date_str}...")

    orders = get_orders_for_day(token, date_str)
    revenue = sum(
        float(o.get("OrderTotal", {}).get("Amount", 0))
        for o in orders if o.get("OrderTotal")
    )
    print(f"   📦 {len(orders)} orders · ${revenue:,.2f}")

    units = get_units_for_day(token, date_str)
    print(f"   📈 {units} units (from sales metrics)")

    sku_units = {}
    if orders:
        print(f"   🏷️  Fetching SKU breakdown ({len(orders)} orders × 2s = ~{len(orders)*2}s)...")
        sku_units = get_sku_breakdown(token, orders)
        print(f"   ✅ SKU breakdown: {sku_units}")

    data = {
        "date":         date_str,
        "pulled_at":    datetime.datetime.utcnow().isoformat() + "Z",
        "orders_today": len(orders),
        "revenue_today": round(revenue, 2),
        "units_ordered": units,
        "finance":      {},
        "sku_units":    sku_units,
    }
    with open(save_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"   💾 Saved → {save_path}")


def daterange(start_str, end_str):
    start = datetime.date.fromisoformat(start_str)
    end   = datetime.date.fromisoformat(end_str)
    delta = (end - start).days + 1
    return [(start + datetime.timedelta(days=i)).isoformat() for i in range(delta)]


def main():
    parser = argparse.ArgumentParser(description="Backfill historical KPI data")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end",   required=True, help="End date YYYY-MM-DD")
    args = parser.parse_args()

    dates = daterange(args.start, args.end)
    print(f"\n📊 LooReady Backfill — {args.start} to {args.end} ({len(dates)} days)")
    print("=" * 55)

    print("🔑 Getting access token...")
    token = get_access_token()
    print("   ✅ Token obtained")

    skipped = 0
    filled  = 0
    failed  = []

    for date_str in dates:
        try:
            save_path = DATA_DIR / f"{date_str}.json"
            if save_path.exists():
                skipped += 1
                print(f"   ⏭️  {date_str} already exists")
                continue
            backfill_day(token, date_str)
            filled += 1
        except Exception as e:
            print(f"   ❌ {date_str} FAILED: {e}")
            traceback.print_exc()
            failed.append(date_str)

    print(f"\n🎉 Backfill complete!")
    print(f"   ✅ Filled:   {filled} days")
    print(f"   ⏭️  Skipped:  {skipped} days (already had data)")
    if failed:
        print(f"   ❌ Failed:   {len(failed)} days: {failed}")


if __name__ == "__main__":
    main()
