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
    resp = sp_request(token, "GET", "/orders/v0/orders", {
        "MarketplaceIds": MARKETPLACE_ID,
        "CreatedAfter":   since,
        "OrderStatuses":  "Shipped,Unshipped,PartiallyShipped",
    })
    if resp.status_code != 200:
        print(f"⚠️ Orders {resp.status_code}: {resp.text[:200]}")
        return []
    return resp.json().get("payload", {}).get("Orders", [])


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

    print("📦 Pulling orders...")
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
