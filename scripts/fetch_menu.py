#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取数脚本：从麦当劳 MCP 拉一份真实菜单快照，供 catering_plan.py 求解。

调用链（全部为真实 MCP 调用）：
    now-time-info → query-nearby-stores → query-meals → query-meal-detail
    → list-nutrition-foods（热量）→ calculate-price（官方单价）

Token 只从环境变量 MCD_MCP_TOKEN 读取，不落盘。

用法：
    python scripts/fetch_menu.py --city 北京 --keyword 国贸 --out data/menu_snapshot.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import McpClient, McpError, call_json, first_json, _content_text  # noqa: E402

# 菜单位置 → 规划槽位
CATEGORY_TO_SLOT = {
    "巨无霸/牛鱼肉堡": "main",
    "鸡肉汉堡//卷": "main",
    "安格斯MAX/厚牛堡": "main",
    "小食甜品//其他": "side",
    "小食拼盘//多人餐": "side",
    "蘸酱炸鸡": "side",
    "炸鸡": "side",
    "饮品": "drink",
    "麦咖啡™": "drink",
}

TAG_RULES = [
    ("beef", r"巨无霸|牛堡|吉士汉堡|安格斯|不素之霸|牛肉|牛气"),
    ("chicken", r"麦香鸡|麦辣鸡|板烧|鸡腿堡|麦乐鸡|脆汁鸡|V翅|鸡翅|鸡球|鸡排|鸡肉"),
    ("fish", r"鳕鱼|麦香鱼|鱼排|薯鱼"),
    ("fried", r"薯条|麦乐鸡|脆汁鸡|V翅|鸡翅|鸡排|鸡球|油条|脆薯"),
    ("spicy", r"麦辣|辣|龙焰|蒜了"),
    ("caffeine", r"可乐|咖啡|美式|拿铁|奶铁|玛奇朵|卡布奇诺|红茶|伯爵"),
    ("dairy", r"牛奶|奶铁|拿铁|玛奇朵|卡布奇诺|朱古力|芝士条|新地|麦旋风"),
    ("vegetarian", r"玉米杯|苹果片|薯条|沙拉"),
]

SHARE_RULES = [(r"十翅|四宫格|分享|全家|双人|多人|拼盘", 4)]

# 套餐按「份」卖，不适合按人配比；周边是搭售商品，不是餐品
COMBO_RX = r"件套|套餐|双人|全家|多人|分享餐|组合|随心拼|四宫格"
MERCH_RX = r"丝巾|按摩|单肩包|玩具|徽章|盲盒|手办|挂件"


def slot_of(category_name: str) -> str:
    key = category_name.replace("\n", "/")
    return CATEGORY_TO_SLOT.get(key, "")


def tags_of(name: str):
    picked = [tag for tag, pattern in TAG_RULES if re.search(pattern, name)]
    # 牛肉/鸡肉/鱼肉互斥时以更具体的品类为准，避免同一餐品同时被标成多种肉类
    meats = [t for t in picked if t in ("beef", "chicken", "fish")]
    if len(meats) > 1:
        for extra in meats[1:]:
            picked.remove(extra)
    return picked


def share_of(name: str) -> int:
    for pattern, share in SHARE_RULES:
        if re.search(pattern, name):
            return share
    return 1


def parse_nutrition(raw: str):
    """营养表是「[160]{字段}:\n  名称,null,kJ,kcal,...」这种紧凑文本，这里解析成字典。"""
    table = {}
    for line in (raw or "").splitlines()[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        name = parts[0]
        try:
            kcal = int(float(parts[3]))
        except ValueError:
            continue
        table[name] = kcal
    return table


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="从麦当劳 MCP 取一份真实菜单快照")
    parser.add_argument("--city", default="北京", help="城市名，用于搜索门店")
    parser.add_argument("--keyword", default="国贸", help="门店关键词")
    parser.add_argument("--store-code", help="已知 storeCode 时可直接指定，跳过门店搜索")
    parser.add_argument("--be-type", type=int, default=1, help="1-到店取餐 2-外送 5-得来速 6-团餐")
    parser.add_argument("--order-type", type=int, default=1, help="1-到店 2-外送")
    parser.add_argument("--out", default="data/menu_snapshot.json")
    parser.add_argument("--max-items", type=int, default=95, help="最多查询多少条餐品明细")
    args = parser.parse_args(argv)

    token = os.environ.get("MCD_MCP_TOKEN", "").strip()
    started = time.time()
    try:
        client = McpClient(token)
        info = client.initialize()

        now = call_json(client, "now-time-info", {}) or {}
        server_time = (now.get("data") or {}).get("formatted", "")

        store = {}
        if args.store_code:
            store = {"storeCode": args.store_code, "storeName": "(手动指定)", "address": ""}
        else:
            stores = call_json(client, "query-nearby-stores", {
                "beType": args.be_type, "searchType": 2,
                "city": args.city, "keyword": args.keyword,
            }) or {}
            rows = stores.get("data") or []
            if not rows:
                print("未找到门店：%s %s" % (args.city, args.keyword), file=sys.stderr)
                return 3
            store = rows[0]
        store_code = store["storeCode"]
        be_code = store.get("beCode") or ""

        base = {"storeCode": store_code, "orderType": args.order_type, "beType": args.be_type}
        if be_code:
            base["beCode"] = be_code

        meals = call_json(client, "query-meals", base) or {}
        categories = (meals.get("data") or {}).get("categories") or []

        candidates = []  # (code, slot, category)
        for cat in categories:
            slot = slot_of(cat.get("name", ""))
            if not slot:
                continue
            for item in cat.get("meals") or []:
                candidates.append((item["code"], slot, cat.get("name", "").replace("\n", "/")))

        seen, picked = set(), []
        for code, slot, cat in candidates:
            if code in seen:
                continue
            seen.add(code)
            picked.append({"code": code, "slot": slot, "category": cat})
        picked = picked[: args.max_items]

        nutrition = parse_nutrition(
            ((call_json(client, "list-nutrition-foods", {}) or {}).get("data") or "")
        )

        items, missing_kcal, failed = [], [], 0
        for row in picked:
            detail = call_json(client, "query-meal-detail", dict(base, code=row["code"])) or {}
            data = detail.get("data") or {}
            name = data.get("name")
            if not name:
                failed += 1
                continue
            if re.search(COMBO_RX, name) or re.search(MERCH_RX, name):
                continue
            kcal = nutrition.get(name)
            if kcal is None:
                missing_kcal.append(name)
                continue
            items.append({
                "code": row["code"],
                "name": name,
                "category": row["slot"],
                "kcal": kcal,
                "tags": tags_of(name),
                "share_per": share_of(name),
                "_menu_category": row["category"],
            })

        if not items:
            print("没有取到可用餐品（明细失败 %d 条）" % failed, file=sys.stderr)
            return 4

        # 单价必须「单品单件」单独询价：门店存在第二份半价等阶梯优惠，
        # 混合订单的行小计会被优惠摊薄，用「小计 ÷ 数量」反推会得到错误的单价。
        price_map = {}
        for item in items:
            one = call_json(client, "calculate-price", dict(
                base, items=[{"productCode": item["code"], "quantity": 1}]
            )) or {}
            price = (one.get("data") or {}).get("price")
            if price:
                price_map[item["code"]] = int(price)

        final = []
        for item in items:
            cents = price_map.get(item["code"])
            if not cents:
                continue
            item["unit_price_cents"] = cents
            final.append(item)

        snapshot = {
            "meta": {
                "source": "麦当劳 MCP（https://mcp.mcd.cn）",
                "server": info.get("serverInfo", {}),
                "protocol": info.get("protocolVersion"),
                "server_time": server_time,
                "fetched_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
                "elapsed_seconds": round(time.time() - started, 1),
                "store": {
                    "storeCode": store_code,
                    "storeName": store.get("storeName", ""),
                    "address": store.get("address", ""),
                    "city": args.city,
                },
                "be_type": args.be_type,
                "order_type": args.order_type,
                "counts": {
                    "categories": len(categories),
                    "detail_ok": len(items),
                    "priced": len(final),
                    "kcal_missing": len(missing_kcal),
                    "detail_failed": failed,
                },
                "tools_used": [
                    "now-time-info", "query-nearby-stores", "query-meals",
                    "query-meal-detail", "list-nutrition-foods", "calculate-price",
                ],
                "note": "价格为该门店该时刻的真实可售价；热量取自官方营养数据表。",
            },
            "menu": [
                {k: v for k, v in item.items() if not k.startswith("_")}
                for item in sorted(final, key=lambda x: (x["category"], x["unit_price_cents"]))
            ],
        }

        out = args.out if os.path.isabs(args.out) else os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), args.out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=2)

        print("门店：%s（%s）" % (store.get("storeName", ""), store_code))
        print("服务器时间：%s" % server_time)
        print("分类 %d 个｜明细成功 %d｜带价 %d｜热量缺失 %d｜明细失败 %d"
              % (len(categories), len(items), len(final), len(missing_kcal), failed))
        slots = {}
        for item in final:
            slots[item["category"]] = slots.get(item["category"], 0) + 1
        print("槽位分布：%s" % json.dumps(slots, ensure_ascii=False))
        print("已写入 %s" % out)
        return 0
    except McpError as exc:
        print("取数失败：%s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
