#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金额复核：把本地求出的组合交给官方 calculate-price 算一遍，比对总价。

为什么必须做这一步：本地算价再准，也只是「我按单价乘数量」；
真正下单时的应付金额可能包含门店差异、优惠、配送费等。金额不一致时，一律以官方算价为准。

用法：
    python scripts/verify_order.py --snapshot data/menu_snapshot.json \\
        --items 1450x47,515837x47,511186x47
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import McpClient, McpError, call_json  # noqa: E402


def parse_items(text: str):
    rows = []
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "x" not in chunk:
            raise SystemExit("商品格式应为 code x 数量，例如 1450x47")
        code, qty = chunk.split("x", 1)
        rows.append({"productCode": code.strip(), "quantity": int(qty)})
    return rows


def split_orders(items, limit):
    """按单笔总件数上限拆单：顺次装满一单再开下一单，保证每单总量不超过 limit。"""
    orders, current, used = [], [], 0
    for item in items:
        remain = item["quantity"]
        while remain > 0:
            room = limit - used
            if room <= 0:
                orders.append(current)
                current, used = [], 0
                continue
            take = min(room, remain)
            current.append({"productCode": item["productCode"], "quantity": take})
            used += take
            remain -= take
    if current:
        orders.append(current)
    return orders


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="用官方算价复核本地组合金额")
    parser.add_argument("--snapshot", required=True, help="menu_snapshot.json")
    parser.add_argument("--items", required=True, help="code x 数量，逗号分隔")
    parser.add_argument("--split", type=int, default=99,
                        help="单笔订单总件数上限，超过则拆单（实测 99 可算价、100 被拒；0 表示不拆）")
    parser.add_argument("--out", help="把复核结果写入 JSON")
    args = parser.parse_args(argv)

    token = os.environ.get("MCD_MCP_TOKEN", "").strip()
    snapshot = json.load(open(args.snapshot, encoding="utf-8"))
    meta = snapshot["meta"]
    store_code = meta["store"]["storeCode"]
    be_type = meta.get("be_type", 1)
    order_type = meta.get("order_type", 1)

    unit_price = {item["code"]: item["unit_price_cents"] for item in snapshot["menu"]}
    items = parse_items(args.items)
    local_total = sum(unit_price.get(i["productCode"], 0) * i["quantity"] for i in items)

    orders = split_orders(items, args.split) if args.split and args.split > 0 else [items]

    try:
        client = McpClient(token)
        client.initialize()
        results = []
        for order in orders:
            payload = {"storeCode": store_code, "orderType": order_type, "beType": be_type, "items": order}
            results.append(call_json(client, "calculate-price", payload) or {})
    except McpError as exc:
        print("复核失败：%s" % exc, file=sys.stderr)
        return 2

    prices = []
    for idx, result in enumerate(results, 1):
        data = result.get("data") or {}
        price = data.get("price")
        if price is None:
            print("第 %d 单官方未返回价格（%s）：%s" % (
                idx, result.get("code"), result.get("message")), file=sys.stderr)
            return 3
        prices.append(price)
    official = sum(prices)

    diff = official - local_total
    print("门店：%s（%s）" % (meta["store"]["storeName"], store_code))
    print("组合：%s" % args.items)
    print("本地按单价合计：¥%.2f" % (local_total / 100))
    print("官方算价合计：  ¥%.2f" % (official / 100))
    print("差额：          ¥%.2f" % (diff / 100))
    if len(orders) > 1:
        print("拆单：共 %d 单（单笔上限 %d 件）" % (len(orders), args.split))
        for idx, (order, price) in enumerate(zip(orders, prices), 1):
            print("  第 %d 单：%d 件，¥%.2f" % (
                idx, sum(o["quantity"] for o in order), price / 100))
    print("明细：")
    for result in results:
        for row in ((result.get("data") or {}).get("productList") or []):
            print("  - %-22s x%-3d 小计 ¥%.2f" % (
                row.get("productName", ""), row.get("quantity", 0), (row.get("subtotal") or 0) / 100))
        discount = (result.get("data") or {}).get("discount")
        if discount:
            print("优惠：¥%.2f" % (discount / 100))

    ok = diff == 0
    print("结论：%s" % ("一致，可进入下单确认" if ok else "不一致，以官方算价为准并回溯台账"))

    if args.out:
        out = args.out if os.path.isabs(args.out) else os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), args.out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({
                "store": meta["store"], "items": items,
                "local_total_cents": local_total, "official_total_cents": official,
                "diff_cents": diff, "consistent": ok,
                "split_limit": args.split, "order_count": len(orders),
                "orders": [
                    {"items": o, "qty": sum(i["quantity"] for i in o), "price_cents": p}
                    for o, p in zip(orders, prices)
                ],
            }, fh, ensure_ascii=False, indent=2)
        print("已写入 %s" % out)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
