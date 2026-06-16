"""
LooReady — Amazon SP-API KPI Pull
Reads credentials from environment variables (set as GitHub Secrets).
Saves daily JSON to kpi_data/YYYY-MM-DD.json
"""

import json
import os
import datetime
import requests
import time
import traceback
from pathlib import Path

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
    if resp.status_code != 200:
        print(f"❌ Token error {resp.status_code}: {resp.text}")
        resp.raise_for_status()
    return resp.json()["access_token"]


def sp_request(access_token, method, path, params=None):
    url = ENDPOINT + path
    headers = {
        "x-amz-access-token": access_token,
        "x-amz-date": datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
        "content-type": "application/json",
    }
    resp = requests.request(method, url, headers=headers, params=params)
    if resp.status_code == 429:
        time.sleep(3)
        resp = requests.request(method, url, headers=headers, params=params)
    return resp


def get_orders(token, days=1):
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    params = {
        "MarketplaceIds": MARKETPLACE_ID,
        "CreatedAfter":   since,
        "OrderStatuses":  "Shipped,Unshipped,PartiallyShipped",
    }
    all_orders = []
    page = 0
    while True:
        resp = sp_request(token, "GET", "/orders/v0/orders", params)
        if resp.status_code != 200:
            print(f"⚠️ Orders page {page} {resp.status_code}: {resp.text[:200]}")
            break
        payload = resp.json().get("payload", {})
        batch = payload.get("Orders", [])
        all_orders.extend(batch)
        page += 1
        print(f"   page {page}: {len(batch)} orders (total so far: {len(all_orders)})")
        next_token = payload.get("NextToken")
        if not next_token:
            break
        params = {"NextToken": next_token, "MarketplaceIds": MARKETPLACE_ID}
        time.sleep(1)
    return all_orders


def get_sales_metrics(token, days=1):
    end   = datetime.datetime.utcnow()
    start = end - datetime.timedelta(days=days)
    resp = sp_request(token, "GET", "/sales/v1/orderMetrics", {
        "marketplaceIds": MARKETPLACE_ID,
        "interval":       f"{start.strftime('%Y-%m-%dT00:00:00Z')}--{end.strftime('%Y-%m-%dT00:00:00Z')}",
        "granularity":    "DAY",
        "granularityTimeZone": "US/Pacific",
    })
    if resp.status_code != 200:
        print(f"⚠️ Sales metrics {resp.status_code}: {resp.text[:200]}")
        return {}
    payload = resp.json().get("payload", [])
    return payload[0] if payload else {}


def get_order_items(token, order_id):
    resp = sp_request(token, "GET", f"/orders/v0/orders/{order_id}/orderItems")
    if resp.status_code == 429:
        time.sleep(5)
        resp = sp_request(token, "GET", f"/orders/v0/orders/{order_id}/orderItems")
    if resp.status_code != 200:
        print(f"⚠️ OrderItems {order_id} {resp.status_code}")
        return []
    return resp.json().get("payload", {}).get("OrderItems", [])


def get_sku_breakdown(token, orders):
    """Returns {SellerSKU: units_ordered} across all orders.
    Uses 2s sleep to stay within 0.5 req/s sustained rate limit."""
    sku_units = {}
    for i, order in enumerate(orders):
        order_id = order.get("AmazonOrderId")
        if not order_id:
            continue
        items = get_order_items(token, order_id)
        for item in items:
            sku = item.get("SellerSKU", "Unknown")
            qty = int(item.get("QuantityOrdered", 0))
            sku_units[sku] = sku_units.get(sku, 0) + qty
        # 0.5 req/s sustained — 2s sleep avoids 429 penalty (5s each)
        time.sleep(2)
        if (i + 1) % 20 == 0:
            print(f"   ... {i+1}/{len(orders)} orders processed")
    return sku_units


def load_or_fetch_7d(token):
    """Fetch 7d revenue + SKU breakdown once per day and cache it."""
    today = datetime.date.today().isoformat()
    cache_path = DATA_DIR / f"7d_cache_{today}.json"
    if cache_path.exists():
        print("   ⚡ 7d cache hit — loading from file")
        with open(cache_path) as f:
            return json.load(f)
    print("🏷️  Pulling 7d data (orders + SKU breakdown, paginated)...")
    orders_7d = get_orders(token, days=7)
    print(f"   📦 {len(orders_7d)} total orders in last 7 days")
    revenue_7d = sum(float(o.get("OrderTotal", {}).get("Amount", 0)) for o in orders_7d if o.get("OrderTotal"))
    print(f"   💰 7d revenue: ${revenue_7d:,.2f}")
    sku_units_7d = get_sku_breakdown(token, orders_7d)
    cache = {
        "sku_units_7d": sku_units_7d,
        "revenue_7d": round(revenue_7d, 2),
        "orders_7d": len(orders_7d),
    }
    with open(cache_path, "w") as f:
        json.dump(cache, f)
    print(f"   ✅ 7d cache saved: {cache}")
    return cache


def get_finance(token, days=1):
    end   = datetime.datetime.utcnow()
    start = end - datetime.timedelta(days=days)
    resp = sp_request(token, "GET", "/finances/v0/financialEvents", {
        "PostedAfter":  start.strftime("%Y-%m-%dT00:00:00Z"),
        "PostedBefore": end.strftime("%Y-%m-%dT00:00:00Z"),
    })
    if resp.status_code != 200:
        print(f"⚠️ Finance {resp.status_code}: {resp.text[:200]}")
        return {}
    events = resp.json().get("payload", {}).get("FinancialEvents", {})
    total_fees = total_sales = 0
    for order in events.get("ShipmentEventList", []):
        for item in order.get("ShipmentItemList", []):
            for charge in item.get("ItemChargeList", []):
                if charge.get("ChargeType") == "Principal":
                    total_sales += float(charge.get("ChargeAmount", {}).get("CurrencyAmount", 0))
            for fee in item.get("ItemFeeList", []):
                total_fees += abs(float(fee.get("FeeAmount", {}).get("CurrencyAmount", 0)))
    return {"total_sales": round(total_sales, 2), "total_fees": round(total_fees, 2)}


def main():
    today     = datetime.date.today().isoformat()
    save_path = DATA_DIR / f"{today}.json"

    print(f"\n📊 LooReady KPI Pull — {today}")
    print("=" * 45)

    print("🔑 Getting access token...")
    token = get_access_token()
    print("   ✅ Token obtained")

    kpi = {"date": today, "pulled_at": datetime.datetime.utcnow().isoformat()}

    print("📦 Pulling today's orders (with pagination)...")
    orders = get_orders(token, days=1)
    revenue = sum(float(o.get("OrderTotal", {}).get("Amount", 0)) for o in orders if o.get("OrderTotal"))
    kpi["orders_today"]  = len(orders)
    kpi["revenue_today"] = round(revenue, 2)
    print(f"   ✅ {len(orders)} orders · ${revenue:,.2f}")

    print("📈 Pulling sales metrics...")
    metrics = get_sales_metrics(token, days=1)
    kpi["units_ordered"] = metrics.get("unitCount", 0)
    print(f"   ✅ {kpi['units_ordered']} units")

    print("💰 Pulling finance events...")
    finance = get_finance(token, days=1)
    kpi["finance"] = finance
    print(f"   ✅ Fees ${finance.get('total_fees', 0):,.2f}")

    print("🏷️  Pulling SKU breakdown (today)...")
    sku_units = get_sku_breakdown(token, orders)
    kpi["sku_units"] = sku_units
    print(f"   ✅ SKU breakdown today: {sku_units}")

    data_7d = load_or_fetch_7d(token)
    kpi["sku_units_7d"] = data_7d["sku_units_7d"]
    kpi["revenue_7d"]   = data_7d["revenue_7d"]
    kpi["orders_7d"]    = data_7d["orders_7d"]

    with open(save_path, "w") as f:
        json.dump(kpi, f, indent=2, default=str)
    print(f"\n💾 Saved → {save_path}")
    print("🎉 Pull complete!")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ CRASH: {e}")
        traceback.print_exc()
        raise
