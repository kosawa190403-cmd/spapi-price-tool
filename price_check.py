#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))
TOKEN_URL = "https://api.amazon.co.jp/auth/o2/token"
API_HOST = "https://sellingpartnerapi-fe.amazon.com"
MARKETPLACE_ID = "A1VC38T7YXB528"


def load_config():
    cfg = {
        "client_id": os.environ.get("SPAPI_CLIENT_ID", ""),
        "client_secret": os.environ.get("SPAPI_CLIENT_SECRET", ""),
        "refresh_token": os.environ.get("SPAPI_REFRESH_TOKEN", ""),
    }
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        sys.exit("環境変数が未設定です: " + ", ".join(missing))
    return cfg


def get_access_token(cfg):
    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": cfg["refresh_token"],
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
        }
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    return body["access_token"]


def get_offers(token, asin):
    qs = urllib.parse.urlencode(
        {
            "MarketplaceId": MARKETPLACE_ID,
            "ItemCondition": "New",
            "CustomerType": "Consumer",
        }
    )
    url = (
        f"{API_HOST}/products/pricing/v0/items/"
        f"{urllib.parse.quote(asin)}/offers?{qs}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "x-amz-access-token": token,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def summarize(payload):
    p = payload.get("payload", {}) or {}
    summary = p.get("Summary", {}) or {}
    offers = p.get("Offers", []) or []

    buybox_landed = ""
    buybox_prices = summary.get("BuyBoxPrices", []) or []
    if buybox_prices:
        buybox_landed = buybox_prices[0].get("LandedPrice", {}).get("Amount", "")

    landed_prices = []
    for o in offers:
        amt = o.get("Price", {}).get("LandedPrice", {}).get("Amount")
        if amt is not None:
            landed_prices.append(amt)
    lowest_new = min(landed_prices) if landed_prices else ""

    if lowest_new == "":
        for lp in summary.get("LowestPrices", []) or []:
            if lp.get("condition") == "new":
                lowest_new = lp.get("LandedPrice", {}).get("Amount", "")
                break

    return {
        "buybox_landed": buybox_landed,
        "lowest_new_landed": lowest_new,
        "offer_count": len(offers),
    }


def read_asins():
    path = BASE / "asins.txt"
    if not path.exists():
        sys.exit("asins.txt がありません。")
    asins = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                asins.append(s.split()[0])
    return asins


def main():
    cfg = load_config()
    asins = read_asins()
    if not asins:
        sys.exit("asins.txt に ASIN がありません。")
    print(f"対象 {len(asins)} 件の価格を確認します。")
    token = get_access_token(cfg)
    print("アクセストークン取得 OK")

    checked_at = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for i, asin in enumerate(asins):
        if i > 0:
            time.sleep(2.1)
        try:
            payload = get_offers(token, asin)
            s = summarize(payload)
            rows.append(
                {
                    "asin": asin,
                    "checked_at": checked_at,
                    "buybox_landed": s["buybox_landed"],
                    "lowest_new_landed": s["lowest_new_landed"],
                    "offer_count": s["offer_count"],
                    "status": "ok",
                }
            )
            print(f"  {asin}: 最安新品(送料込) {s['lowest_new_landed']} / BuyBox {s['buybox_landed']}")
        except urllib.error.HTTPError as e:
            rows.append(
                {
                    "asin": asin,
                    "checked_at": checked_at,
                    "buybox_landed": "",
                    "lowest_new_landed": "",
                    "offer_count": "",
                    "status": f"http_{e.code}",
                }
            )
            print(f"  {asin}: エラー HTTP {e.code}")
        except Exception as e:
            rows.append(
                {
                    "asin": asin,
                    "checked_at": checked_at,
                    "buybox_landed": "",
                    "lowest_new_landed": "",
                    "offer_count": "",
                    "status": f"error: {type(e).__name__}",
                }
            )
            print(f"  {asin}: エラー {type(e).__name__}")

    results_dir = BASE / "results"
    results_dir.mkdir(exist_ok=True)
    stamp = datetime.now(JST).strftime("%Y%m%d-%H%M")
    fields = ["asin", "checked_at", "buybox_landed", "lowest_new_landed", "offer_count", "status"]
    for out in (results_dir / f"prices-{stamp}.csv", results_dir / "prices-latest.csv"):
        with out.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    print("完了")


if __name__ == "__main__":
    main()
