#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦麦团餐台账 · 组合求解与分摊台账生成器（纯标准库，Python 3.9+）

职责边界：
  本模块只做「确定性的本地计算」——给定人数、人均预算、忌口与菜单快照，
  求解一份可解释的团餐组合，并输出分摊台账（CSV）与单文件台账卡片（HTML）。
  它不联网、不持有任何凭证；菜单与价格由 Agent 通过麦当劳 MCP 取得后写入 JSON 喂进来。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

CATEGORY_LABELS = {"main": "主食", "side": "配餐", "drink": "饮品"}

# 评分权重（合计 1.00）。权重写死并可解释，是为了让同一输入永远得到同一方案。
W_KCAL = 0.40      # 人均热量贴合目标
W_COVERAGE = 0.30  # 主食/配餐/饮品三类覆盖度
W_BUDGET = 0.30    # 预算余量（余量 >= 15% 得满分）
BUFFER_TARGET = 0.15  # 健康缓冲：顶格花完预算不加分，因为临时加人加杯会直接超支


@dataclass(frozen=True)
class Item:
    """一个可售餐品。价格一律用「分」存储，避免浮点误差。"""

    code: str
    name: str
    category: str
    unit_price_cents: int
    kcal: int = 0
    tags: Tuple[str, ...] = ()
    share_per: int = 1  # 每 share_per 人 1 份；1 表示每人 1 份

    @property
    def tagset(self) -> frozenset:
        return frozenset(self.tags)

    def qty_for(self, people: int) -> int:
        return people if self.share_per <= 1 else int(math.ceil(people / self.share_per))


@dataclass(frozen=True)
class Combo:
    """一份按人配比的团餐方案：主食必选，配餐与饮品可缺省。"""

    main: Item
    side: Optional[Item]
    drink: Optional[Item]
    people: int
    qty_main: int
    qty_side: int
    qty_drink: int
    total_cents: int
    kcal_total: int

    @property
    def per_person_cents(self) -> float:
        return self.total_cents / self.people

    @property
    def per_person_kcal(self) -> float:
        return self.kcal_total / self.people

    def describe(self) -> str:
        parts = [f"{self.main.name} x{self.qty_main}"]
        if self.side:
            parts.append(f"{self.side.name} x{self.qty_side}")
        if self.drink:
            parts.append(f"{self.drink.name} x{self.qty_drink}")
        return " + ".join(parts)

    def per_person_text(self) -> str:
        parts = [self.main.name]
        if self.side:
            share = "每人1份" if self.side.share_per <= 1 else f"每{self.side.share_per}人1份"
            parts.append(f"{self.side.name}（{share}）")
        if self.drink:
            share = "每人1份" if self.drink.share_per <= 1 else f"每{self.drink.share_per}人1份"
            parts.append(f"{self.drink.name}（{share}）")
        return " + ".join(parts)

    def code_tuple(self) -> Tuple[str, str, str]:
        return (
            self.main.code,
            self.side.code if self.side else "",
            self.drink.code if self.drink else "",
        )


@dataclass
class PlanResult:
    people: int
    budget_per_person_cents: int
    target_kcal: int
    avoid_tags: Tuple[str, ...]
    combo: Optional[Combo] = None
    alternatives: List[Combo] = field(default_factory=list)
    feasible: bool = False
    over_budget: bool = False
    deficit_cents: int = 0
    reasons: List[str] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)

    @property
    def budget_total_cents(self) -> int:
        return self.budget_per_person_cents * self.people

    def to_dict(self) -> dict:
        c = self.combo
        return {
            "people": self.people,
            "budget_per_person_yuan": round(self.budget_per_person_cents / 100, 2),
            "budget_total_yuan": round(self.budget_total_cents / 100, 2),
            "feasible": self.feasible,
            "over_budget": self.over_budget,
            "deficit_yuan": round(self.deficit_cents / 100, 2),
            "avoid_tags": list(self.avoid_tags),
            "plan": None
            if not c
            else {
                "combo": c.describe(),
                "per_person": c.per_person_text(),
                "total_yuan": round(c.total_cents / 100, 2),
                "per_person_yuan": round(c.per_person_cents / 100, 2),
                "utilization": round(c.total_cents / self.budget_total_cents, 4)
                if self.budget_total_cents
                else 0.0,
                "kcal_per_person": round(c.per_person_kcal, 1),
                "score": round(self.scores.get("weighted", 0.0), 4),
            },
            "reasons": self.reasons,
        }


def parse_items(raw: Iterable[dict]) -> List[Item]:
    items: List[Item] = []
    for row in raw:
        cat = str(row.get("category", "")).strip().lower()
        if cat not in CATEGORY_LABELS:
            raise ValueError(f"未知 category: {row.get('name')} -> {cat}")
        price = row.get("unit_price_cents")
        if price is None:
            yuan = row.get("unit_price_yuan")
            if yuan is None:
                raise ValueError(f"缺少价格: {row.get('name')}")
            price = int(round(float(yuan) * 100))
        items.append(
            Item(
                code=str(row.get("code") or row.get("name")),
                name=str(row.get("name")),
                category=cat,
                unit_price_cents=int(price),
                kcal=int(row.get("kcal") or 0),
                tags=tuple(row.get("tags") or ()),
                share_per=int(row.get("share_per") or 1),
            )
        )
    return items


def _score(combo: Combo, budget_cents: int, target_kcal: int) -> Tuple[float, float, float, float]:
    kcal_pp = combo.per_person_kcal
    if target_kcal > 0:
        kcal_fit = max(0.0, 1.0 - abs(kcal_pp - target_kcal) / float(target_kcal))
    else:
        kcal_fit = 1.0

    utilization = combo.total_cents / budget_cents if budget_cents else 1.0
    remaining_ratio = 1.0 - utilization
    budget_fit = max(0.0, min(1.0, remaining_ratio / BUFFER_TARGET))

    present = 1 + (1 if combo.side else 0) + (1 if combo.drink else 0)
    coverage = present / 3.0

    weighted = W_KCAL * kcal_fit + W_COVERAGE * coverage + W_BUDGET * budget_fit
    return weighted, kcal_fit, budget_fit, coverage


def plan(
    people: int,
    budget_per_person_cents: int,
    items: Sequence[Item],
    avoid_tags: Sequence[str] = (),
    target_kcal: int = 700,
    keep_alternatives: int = 3,
) -> PlanResult:
    """枚举 (主食 × 配餐/无 × 饮品/无)，在预算内取加权得分最高的组合。

    选枚举而非整数规划，是因为团餐的真实决策变量只有三个槽位，
    枚举能给出「全部候选 + 排序依据」，结果可复现、可逐条追溯、也便于测试。
    """
    if people <= 0:
        raise ValueError("people 必须为正整数")
    if budget_per_person_cents <= 0:
        raise ValueError("人均预算必须为正数")

    avoid = tuple(sorted({t for t in avoid_tags if t}))
    avoid_set = frozenset(avoid)

    def allowed(item: Item) -> bool:
        return not (item.tagset & avoid_set)

    mains = [i for i in items if i.category == "main" and allowed(i)]
    sides = [i for i in items if i.category == "side" and allowed(i)]
    drinks = [i for i in items if i.category == "drink" and allowed(i)]

    result = PlanResult(
        people=people,
        budget_per_person_cents=budget_per_person_cents,
        target_kcal=target_kcal,
        avoid_tags=avoid,
    )

    if not mains:
        result.reasons.append(
            "在排除忌口标签（" + ("、".join(avoid) if avoid else "无") + "）之后，菜单中已无可用主食。"
        )
        return result

    budget_total = budget_per_person_cents * people
    candidates: List[Tuple[Combo, Tuple[float, float, float, float]]] = []

    for main in mains:
        qm = main.qty_for(people)
        for side in (list(sides) + [None]):
            qs = side.qty_for(people) if side else 0
            for drink in (list(drinks) + [None]):
                qd = drink.qty_for(people) if drink else 0
                total = main.unit_price_cents * qm
                kcal = main.kcal * qm
                if side:
                    total += side.unit_price_cents * qs
                    kcal += side.kcal * qs
                if drink:
                    total += drink.unit_price_cents * qd
                    kcal += drink.kcal * qd
                combo = Combo(
                    main=main,
                    side=side,
                    drink=drink,
                    people=people,
                    qty_main=qm,
                    qty_side=qs,
                    qty_drink=qd,
                    total_cents=total,
                    kcal_total=kcal,
                )
                candidates.append((combo, _score(combo, budget_total, target_kcal)))

    # 排序：得分降序 → 总价升序 → 编码字典序（保证同一输入永远同一方案）
    candidates.sort(key=lambda pair: (-pair[1][0], pair[0].total_cents, pair[0].code_tuple()))

    affordable = [pair for pair in candidates if pair[0].total_cents <= budget_total]

    if affordable:
        best, metrics = affordable[0]
        result.combo = best
        result.feasible = True
        result.scores = {
            "weighted": metrics[0],
            "kcal_fit": round(metrics[1], 4),
            "budget_fit": round(metrics[2], 4),
            "coverage": round(metrics[3], 4),
        }
        result.alternatives = [pair[0] for pair in affordable[1 : 1 + keep_alternatives]]
        result.reasons.append(
            "预算内共有 {} 个可行组合，按「热量贴合 40% + 品类覆盖 30% + 预算余量 30%」加权取优；"
            "预算余量达到 15% 即封顶，顶格花完不加分。".format(len(affordable))
        )
        if not best.side:
            result.reasons.append("配餐槽位为空：加入任一配餐都会突破人均预算。")
        if not best.drink:
            result.reasons.append("饮品槽位为空：加入任一饮品都会突破人均预算。")
        return result

    # 预算内无解：不退化成超预算方案，而是给出最省的可行组合与差额
    cheapest, _ = min(
        candidates, key=lambda pair: (pair[0].total_cents, pair[0].code_tuple())
    )
    result.combo = cheapest
    result.feasible = False
    result.over_budget = True
    result.deficit_cents = cheapest.total_cents - budget_total
    result.alternatives = [
        pair[0]
        for pair in sorted(
            (p for p in candidates if p[0].total_cents > cheapest.total_cents),
            key=lambda pair: (pair[0].total_cents, pair[0].code_tuple()),
        )[:keep_alternatives]
    ]
    result.reasons.append(
        "在最省组合下总价仍超出预算 {:.2f} 元，因此判定为不可行，不输出超预算方案。".format(
            result.deficit_cents / 100
        )
    )
    result.reasons.append(
        "可选处置：下调人均预算需求、减少人数、或取消饮品/配餐槽位后重新求解。"
    )
    return result


def build_ledger(result: PlanResult, people_names: Optional[Sequence[str]] = None,
                 per_person_avoid: Optional[Sequence[Sequence[str]]] = None) -> List[dict]:
    """生成分摊台账。总价按人平均分摊，除不尽的零头由前几位承担，确保合计等于总价。"""
    if not result.combo:
        return []

    n = result.people
    names = list(people_names or [])
    if len(names) < n:
        names += [f"员工{i:02d}" for i in range(len(names) + 1, n + 1)]

    base = result.combo.total_cents // n
    remainder = result.combo.total_cents - base * n

    rows: List[dict] = []
    for idx in range(n):
        share = base + (1 if idx < remainder else 0)
        avoid = ""
        if per_person_avoid and idx < len(per_person_avoid):
            avoid = "、".join(per_person_avoid[idx])
        rows.append(
            {
                "序号": idx + 1,
                "姓名": names[idx],
                "套餐组合": result.combo.per_person_text(),
                "应付金额(元)": f"{share / 100:.2f}",
                "忌口备注": avoid,
            }
        )
    return rows


def to_csv(rows: Sequence[dict]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def _yuan(cents: int) -> str:
    return f"{cents / 100:.2f}"


def to_html(result: PlanResult, rows: Sequence[dict], meta: Optional[dict] = None) -> str:
    """单文件台账卡片：无外链资源、可打印、可截图。"""
    meta = meta or {}
    title = meta.get("title", "麦麦团餐台账")
    subtitle = meta.get("subtitle", "")
    sample = bool(meta.get("sample_data"))
    combo = result.combo

    if combo:
        util = combo.total_cents / result.budget_total_cents if result.budget_total_cents else 0
        headline = (
            f"{combo.per_person_text()}"
            if result.feasible
            else "预算内无可行方案"
        )
        stats = [
            ("人数", f"{result.people}"),
            ("总价", f"¥{_yuan(combo.total_cents)}"),
            ("人均", f"¥{combo.per_person_cents / 100:.2f}"),
            ("预算占用", f"{util * 100:.1f}%"),
            ("人均热量", f"{combo.per_person_kcal:.0f} kcal"),
        ]
    else:
        headline = "无可输出方案"
        util = 0.0
        stats = [("人数", f"{result.people}"), ("总价", "—"), ("人均", "—"),
                 ("预算占用", "—"), ("人均热量", "—")]

    stat_html = "".join(
        f'<div class="stat"><span class="k">{k}</span><span class="v">{v}</span></div>'
        for k, v in stats
    )

    status_class = "ok" if result.feasible else "warn"
    status_text = "预算内可行方案" if result.feasible else "预算不足 · 不可行"
    if result.feasible and result.combo and not (result.combo.side and result.combo.drink):
        status_class = "ok"
        status_text = "预算内可行方案（部分槽位降级）"

    reasons = "".join(f"<li>{r}</li>" for r in result.reasons)
    alt_html = ""
    if result.alternatives:
        items = "".join(
            f'<tr><td>{a.per_person_text()}</td><td>¥{_yuan(a.total_cents)}</td>'
            f'<td>¥{a.per_person_cents / 100:.2f}</td><td>{a.per_person_kcal:.0f}</td></tr>'
            for a in result.alternatives
        )
        alt_html = f"""
    <section class="card">
      <h2>备选方案</h2>
      <table class="grid">
        <thead><tr><th>每人配比</th><th>总价</th><th>人均</th><th>人均热量(kcal)</th></tr></thead>
        <tbody>{items}</tbody>
      </table>
    </section>"""

    ledger_html = ""
    if rows:
        rem = result.combo.total_cents % result.people if result.combo else 0
        remainder_note = (
            f"零头按分位补足：前 {rem} 位各多承担 1 分，台账合计与订单总价严格相等，可直接交财务报销。"
            if rem
            else "总价可被人数整除，每人应付一致；台账合计与订单总价严格相等，可直接交财务报销。"
        )
        body = "".join(
            "<tr>"
            + "".join(f"<td>{row[k]}</td>" for k in rows[0].keys())
            + "</tr>"
            for row in rows
        )
        head = "".join(f"<th>{k}</th>" for k in rows[0].keys())
        ledger_html = f"""
    <section class="card">
      <h2>分摊台账（{len(rows)} 人）</h2>
      <div class="table-wrap">
        <table class="grid">
          <thead><tr>{head}</tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
      <p class="tip">{remainder_note}</p>
    </section>"""

    sample_banner = (
        '<div class="banner">样例数据 · 餐品与价格非麦当劳官方实时数据，仅用于演示计算流程</div>'
        if sample
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root{{
    --ink:#1a1a1a; --sub:#6b6b6b; --line:#e6e2dc; --bg:#f6f4f0;
    --card:#ffffff; --accent:#c8102e; --accent-soft:#fdeef0; --warn:#b26b00; --warn-soft:#fdf3e3;
  }}
  *{{box-sizing:border-box;}}
  body{{margin:0;background:var(--bg);color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
    line-height:1.6;-webkit-font-smoothing:antialiased;}}
  .wrap{{max-width:920px;margin:0 auto;padding:32px 20px 64px;}}
  header{{padding:8px 0 20px;border-bottom:3px solid var(--ink);margin-bottom:24px;}}
  h1{{font-size:26px;margin:0 0 6px;letter-spacing:-.4px;}}
  .sub{{color:var(--sub);font-size:13px;}}
  .banner{{background:var(--accent-soft);color:#8c1226;border:1px solid #f3cdd4;
    border-radius:8px;padding:8px 12px;font-size:12px;margin-bottom:18px;}}
  .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;
    padding:20px 22px;margin-bottom:18px;}}
  h2{{font-size:15px;margin:0 0 14px;padding-bottom:8px;border-bottom:1px solid var(--line);
    letter-spacing:.2px;}}
  .plan{{font-size:17px;font-weight:600;margin:0 0 14px;word-break:break-word;}}
  .badge{{display:inline-block;font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;
    margin-bottom:16px;}}
  .badge.ok{{background:#eef7ee;color:#2f6b33;border:1px solid #cfe6d0;}}
  .badge.warn{{background:var(--warn-soft);color:var(--warn);border:1px solid #f0dcb8;}}
  .stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:12px;}}
  .stat{{background:#faf9f7;border:1px solid var(--line);border-radius:10px;padding:10px 12px;}}
  .stat .k{{display:block;font-size:11px;color:var(--sub);letter-spacing:.4px;}}
  .stat .v{{display:block;font-size:18px;font-weight:600;margin-top:2px;}}
  .bar{{height:8px;background:#eee9e2;border-radius:999px;overflow:hidden;margin-top:16px;}}
  .bar i{{display:block;height:100%;background:var(--accent);width:{min(util, 1) * 100:.1f}%;}}
  .table-wrap{{overflow-x:auto;}}
  table.grid{{width:100%;border-collapse:collapse;font-size:13px;}}
  table.grid th,table.grid td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;
    white-space:nowrap;}}
  table.grid th{{font-size:12px;color:var(--sub);font-weight:600;background:#faf9f7;}}
  table.grid td:first-child{{color:var(--sub);}}
  ul.reasons{{margin:0;padding-left:18px;font-size:13px;color:#3a3a3a;}}
  ul.reasons li{{margin-bottom:6px;}}
  .tip{{font-size:12px;color:var(--sub);margin:12px 0 0;}}
  footer{{margin-top:26px;font-size:11px;color:var(--sub);line-height:1.7;}}
  @media print{{
    body{{background:#fff;}} .card{{break-inside:avoid;box-shadow:none;}}
    .no-print{{display:none;}}
  }}
  @media (max-width:600px){{
    h1{{font-size:21px;}} .wrap{{padding:20px 14px 48px;}}
    .stats{{grid-template-columns:repeat(2,1fr);}}
    .plan{{font-size:15px;}}
  }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{title}</h1>
    <div class="sub">{subtitle}</div>
  </header>
  {sample_banner}
  <section class="card">
    <h2>推荐配比</h2>
    <span class="badge {status_class}">{status_text}</span>
    <p class="plan">{headline}</p>
    <div class="stats">{stat_html}</div>
    <div class="bar"><i></i></div>
  </section>
  <section class="card">
    <h2>决策依据</h2>
    <ul class="reasons">{reasons}</ul>
  </section>
  {alt_html}
  {ledger_html}
  <footer>
    本页由「麦麦团餐台账 mcd-catering-ledger」生成为麦当劳程序员创意开发大赛参赛作品，非麦当劳官方产品。<br>
    输出仅供参考；餐品、价格、可售状态与优惠以麦当劳官方渠道实时结果为准。
  </footer>
</div>
</body>
</html>
"""


def _write(path: str, text: str, encoding: str = "utf-8") -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding=encoding, newline="") as fh:
        fh.write(text)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="麦麦团餐台账：团餐组合求解与分摊台账生成")
    parser.add_argument("--input", help="输入 JSON（人数/预算/忌口/菜单快照）")
    parser.add_argument("--demo", action="store_true", help="用内置样例数据跑一遍")
    parser.add_argument("--out", default="out", help="输出目录")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出求解结果")
    args = parser.parse_args(argv)

    if args.demo:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import demo_data  # noqa: WPS433

        spec = demo_data.build_spec()
    elif args.input:
        with open(args.input, "r", encoding="utf-8") as fh:
            spec = json.load(fh)
    else:
        parser.error("需要 --input 或 --demo")

    items = parse_items(spec.get("menu") or [])
    result = plan(
        people=int(spec["people"]),
        budget_per_person_cents=int(
            spec.get("budget_per_person_cents")
            or round(float(spec["budget_per_person_yuan"]) * 100)
        ),
        items=items,
        avoid_tags=spec.get("avoid_tags") or (),
        target_kcal=int(spec.get("target_kcal") or 700),
    )
    rows = build_ledger(result, spec.get("people_names"), spec.get("per_person_avoid"))

    _write(os.path.join(args.out, "ledger.csv"), to_csv(rows), encoding="utf-8-sig")
    _write(
        os.path.join(args.out, "index.html"),
        to_html(result, rows, spec.get("meta") or {}),
    )

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        d = result.to_dict()
        print(f"人数 {d['people']} · 人均预算 ¥{d['budget_per_person_yuan']} · "
              f"总预算 ¥{d['budget_total_yuan']}")
        if d["plan"]:
            print(f"方案：{d['plan']['per_person']}")
            print(f"总价 ¥{d['plan']['total_yuan']} · 人均 ¥{d['plan']['per_person_yuan']} · "
                  f"预算占用 {d['plan']['utilization'] * 100:.1f}% · "
                  f"人均 {d['plan']['kcal_per_person']} kcal")
        print(f"可行：{d['feasible']} · 超预算：{d['over_budget']}")
        for r in d["reasons"]:
            print("· " + r)
        print(f"已写入 {os.path.join(args.out, 'index.html')} 与 ledger.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
