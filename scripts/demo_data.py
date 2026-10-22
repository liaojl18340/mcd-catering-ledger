#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""演示用样例数据（非官方实时数据）。

重要说明：
  1. 下列餐品名称取自麦当劳公开菜单的常见品类，但**价格与热量均为演示样例**，
     不是麦当劳官方实时数据，也不构成任何报价。
  2. 真实运行时，菜单快照由 Agent 通过麦当劳 MCP 的 query-meals / query-meal-detail /
     list-nutrition-foods 取得后写入 spec JSON，本文件不会被使用。
"""

from __future__ import annotations


def build_menu() -> list:
    return [
        # 主食（每人 1 份）
        {"code": "M01", "name": "巨无霸", "category": "main", "unit_price_cents": 2450,
         "kcal": 550, "tags": ["beef"]},
        {"code": "M02", "name": "麦香鸡", "category": "main", "unit_price_cents": 1800,
         "kcal": 400, "tags": ["chicken"]},
        {"code": "M03", "name": "双层吉士汉堡", "category": "main", "unit_price_cents": 2000,
         "kcal": 450, "tags": ["beef"]},
        {"code": "M04", "name": "板烧鸡腿堡", "category": "main", "unit_price_cents": 2300,
         "kcal": 480, "tags": ["chicken"]},
        {"code": "M05", "name": "麦辣鸡腿堡", "category": "main", "unit_price_cents": 2200,
         "kcal": 500, "tags": ["chicken", "spicy"]},
        {"code": "M06", "name": "吉士汉堡", "category": "main", "unit_price_cents": 1400,
         "kcal": 300, "tags": ["beef"]},
        {"code": "M07", "name": "鱼肉汉堡", "category": "main", "unit_price_cents": 1900,
         "kcal": 380, "tags": ["fish"]},
        {"code": "M08", "name": "蔬菜沙拉卷", "category": "main", "unit_price_cents": 1600,
         "kcal": 260, "tags": ["vegetarian"]},

        # 配餐（可共享：share_per=2 表示每 2 人 1 份）
        {"code": "S01", "name": "中份薯条", "category": "side", "unit_price_cents": 1200,
         "kcal": 320, "tags": ["fried", "vegetarian"]},
        {"code": "S02", "name": "麦乐鸡(5块)", "category": "side", "unit_price_cents": 1500,
         "kcal": 220, "tags": ["chicken", "fried"]},
        {"code": "S03", "name": "麦乐鸡(20块分享装)", "category": "side",
         "unit_price_cents": 5200, "kcal": 880, "tags": ["chicken", "fried"], "share_per": 4},
        {"code": "S04", "name": "玉米杯", "category": "side", "unit_price_cents": 800,
         "kcal": 90, "tags": ["vegetarian"]},

        # 饮品（每人 1 份）
        {"code": "D01", "name": "可口可乐(中)", "category": "drink", "unit_price_cents": 900,
         "kcal": 200, "tags": ["caffeine"]},
        {"code": "D02", "name": "雪碧(中)", "category": "drink", "unit_price_cents": 900,
         "kcal": 190, "tags": []},
        {"code": "D03", "name": "鲜煮咖啡", "category": "drink", "unit_price_cents": 1000,
         "kcal": 5, "tags": ["caffeine"]},
        {"code": "D04", "name": "橙汁", "category": "drink", "unit_price_cents": 1100,
         "kcal": 150, "tags": []},
        {"code": "D05", "name": "纯牛奶", "category": "drink", "unit_price_cents": 1000,
         "kcal": 130, "tags": ["dairy"]},
    ]


def build_spec() -> dict:
    """1024 程序员节团队晚餐：47 人、人均 40 元、2 位同事不吃牛肉。"""
    names = [f"工程师{i:02d}" for i in range(1, 48)]
    per_person_avoid = [["beef"], [], ["beef"]] + [[] for _ in range(44)]
    return {
        "scenario": "1024 程序员节团队晚餐（演示）",
        "people": 47,
        "budget_per_person_cents": 4000,
        "avoid_tags": ["beef"],
        "target_kcal": 700,
        "menu": build_menu(),
        "people_names": names,
        "per_person_avoid": per_person_avoid,
        "meta": {
            "title": "麦麦团餐台账 · 1024 团队晚餐",
            "subtitle": "47 人 · 人均预算 ¥40.00 · 2 位同事忌牛肉 · 目标人均 700 kcal",
            "sample_data": True,
        },
    }
