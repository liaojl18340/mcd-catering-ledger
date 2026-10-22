#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""catering_plan 的单元测试：不联网、不依赖第三方库。

运行：python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from catering_plan import (  # noqa: E402
    Item,
    build_ledger,
    parse_items,
    plan,
    to_csv,
    to_html,
)

MENU = [
    Item("M1", "甲汉堡", "main", 2000, 500, ("beef",)),
    Item("M2", "乙汉堡", "main", 1500, 400, ("chicken",)),
    Item("S1", "薯条", "side", 1000, 300, ("vegetarian",)),
    Item("S2", "分享装鸡块", "side", 4000, 800, ("chicken",), share_per=4),
    Item("D1", "可乐", "drink", 800, 150, ("caffeine",)),
    Item("D2", "橙汁", "drink", 900, 140, ()),
]

PEOPLE = 10


class TestPlan(unittest.TestCase):
    def test_sufficient_budget_covers_three_categories(self):
        res = plan(PEOPLE, 4000, MENU, avoid_tags=[], target_kcal=700)
        self.assertTrue(res.feasible)
        self.assertIsNotNone(res.combo.side)
        self.assertIsNotNone(res.combo.drink)
        self.assertLessEqual(res.combo.total_cents, 4000 * PEOPLE)
        self.assertEqual(
            res.combo.total_cents,
            res.combo.main.unit_price_cents * res.combo.qty_main
            + res.combo.side.unit_price_cents * res.combo.qty_side
            + res.combo.drink.unit_price_cents * res.combo.qty_drink,
        )

    def test_avoid_tags_filter_every_slot(self):
        res = plan(PEOPLE, 4000, MENU, avoid_tags=["beef"], target_kcal=700)
        self.assertTrue(res.feasible)
        codes = {res.combo.main.code}
        if res.combo.side:
            codes.add(res.combo.side.code)
        if res.combo.drink:
            codes.add(res.combo.drink.code)
        self.assertNotIn("M1", codes)  # 牛肉汉堡已被忌口过滤

    def test_all_mains_excluded_reports_reason(self):
        res = plan(PEOPLE, 4000, MENU, avoid_tags=["beef", "chicken"], target_kcal=700)
        self.assertIsNone(res.combo)
        self.assertFalse(res.feasible)
        self.assertTrue(any("无可用主食" in r for r in res.reasons))

    def test_budget_too_low_returns_honest_degradation(self):
        res = plan(PEOPLE, 1000, MENU, avoid_tags=[], target_kcal=700)
        self.assertFalse(res.feasible)
        self.assertTrue(res.over_budget)
        self.assertEqual(res.deficit_cents, res.combo.total_cents - 1000 * PEOPLE)
        self.assertGreater(res.deficit_cents, 0)

    def test_shared_side_quantity_rounds_up(self):
        res = plan(7, 6000, [Item("M1", "甲汉堡", "main", 1000, 400),
                             Item("S2", "分享装", "side", 4000, 800, (), share_per=4)], target_kcal=0)
        self.assertTrue(res.feasible)
        self.assertEqual(res.combo.qty_side, 2)  # ceil(7/4)

    def test_result_is_deterministic(self):
        first = plan(PEOPLE, 3000, MENU, target_kcal=650).to_dict()
        second = plan(PEOPLE, 3000, MENU, target_kcal=650).to_dict()
        self.assertEqual(first, second)

    def test_non_positive_people_rejected(self):
        with self.assertRaises(ValueError):
            plan(0, 2000, MENU)


class TestLedger(unittest.TestCase):
    def test_ledger_sum_equals_total_with_remainder(self):
        menu = [Item("M1", "汉堡", "main", 1000, 400), Item("S1", "薯条", "side", 700, 300, (), share_per=2)]
        res = plan(3, 2000, menu, target_kcal=0)
        rows = build_ledger(res)
        total_from_rows = sum(int(round(float(r["应付金额(元)"]) * 100)) for r in rows)
        self.assertEqual(len(rows), 3)
        self.assertEqual(total_from_rows, res.combo.total_cents)

    def test_ledger_keeps_personal_avoid_notes(self):
        menu = [Item("M2", "乙汉堡", "main", 1500, 400, ("chicken",))]
        res = plan(2, 2000, menu, target_kcal=0)
        rows = build_ledger(res, ["张三", "李四"], [["beef"], []])
        self.assertEqual(rows[0]["姓名"], "张三")
        self.assertEqual(rows[0]["忌口备注"], "beef")
        self.assertEqual(rows[1]["忌口备注"], "")

    def test_csv_has_header_and_all_rows(self):
        menu = [Item("M2", "乙汉堡", "main", 1500, 400, ("chicken",))]
        res = plan(4, 2000, menu, target_kcal=0)
        text = to_csv(build_ledger(res))
        lines = [ln for ln in text.strip().split("\n") if ln]
        self.assertEqual(len(lines), 5)
        self.assertTrue(lines[0].startswith("序号,姓名,套餐组合"))


class TestParseAndRender(unittest.TestCase):
    def test_parse_items_accepts_yuan_price(self):
        items = parse_items([{"code": "X", "name": "样品", "category": "main", "unit_price_yuan": 18.5}])
        self.assertEqual(items[0].unit_price_cents, 1850)

    def test_parse_items_rejects_unknown_category(self):
        with self.assertRaises(ValueError):
            parse_items([{"name": "样品", "category": "dessert", "unit_price_cents": 100}])

    def test_html_is_self_contained(self):
        res = plan(PEOPLE, 4000, MENU, target_kcal=700)
        html = to_html(res, build_ledger(res), {"title": "测试", "sample_data": True})
        self.assertIn("<!DOCTYPE html>", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)  # 无任何外链资源，避免死链与刷量嫌疑
        self.assertIn("样例数据", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
