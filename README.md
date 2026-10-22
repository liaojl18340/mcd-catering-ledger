# 麦麦团餐台账 · mcd-catering-ledger

一个给「替全组点饭的人」用的团餐决策与报销台账工具，基于麦当劳中国官方 MCP 能力构建。

> 场景：周五 18:30，群里说「今晚加班，47 个人，人均 40，有两位不吃牛肉，吃完要报销」。
> 这个 Skill 在 30 秒内给出**一份可解释的配餐方案**、**一份能直接交给财务的分摊台账**，以及**一份打印出来能贴在茶水间的台账卡片**。

**[▶ 在线体验（无需登录）](https://workbuddy.link/p/4fNeDLEtvwFJHz8bHKjF6F)** ｜ 拖动人数、预算、忌口，方案与台账实时重算。

### 真实运行结果（2026-10-22，不是样例数据）

| 验证项 | 结果 |
|---|---|
| 数据来源 | 麦当劳 MCP `mcd-mcp 1.0.0`，协议 `2025-06-18`，门店 `1950564`（北京建外SOHO A 座） |
| 取数 | 15 个分类、114 个餐品条目 → 筛出 27 个可用单品：主食 11 / 配餐 5 / 饮品 11 |
| 求解 | 47 人 · 人均 ¥40 · 目标 700 kcal → 麦香鸡 + 圆筒冰淇淋 + 中杯怡泉+C |
| 金额复核 | 本地合计 ¥1574.50 ｜ 官方 `calculate-price` ¥1574.50 ｜ **差额 ¥0.00** |
| 拆单 | 141 件超过单笔上限，拆 2 单：99 件 ¥1091.50 + 42 件 ¥483.00 |
| 证据文件 | [`data/menu_snapshot.json`](data/menu_snapshot.json)、[`data/plan_real.json`](data/plan_real.json)、[`data/verify_real.json`](data/verify_real.json) |

> 顺手记下两个实测约束：**单笔订单总件数上限 99 件**（100 件返回 `600019`）；**单价不能用混合订单的行小计反推**，门店「第二份半价」会把小计摊薄（我第一版因此少算 ¥180）。详见 [§6](#6-真实运行记录2026-10-22)。

---

## 1. 它解决什么问题

团餐的真实难点不是「哪份套餐最便宜」，而是四件事同时成立：

1. **预算要卡住**：人均预算是硬上限，超一分钱财务就不给报。
2. **每个人都要能吃**：忌口必须按并集处理，否则会出现「有人没得吃」的事故。
3. **钱要分摊得清**：47 人 × 35 元 = 1645 元，按人均平摊会出现分位误差，合计必须与订单金额严格相等。
4. **决策要能复盘**：为什么选这一份？如果领导说「预算降到 30」，能不能立刻给出第二方案？

市面上大量参赛作品在做「省钱助手」「热量助手」，解决的是 1 人份的最优解；团餐是**多人约束下的可行解**，这是一个不同的问题。

## 2. 它怎么工作

```
用户自然语言（人数 / 预算 / 忌口 / 场景）
        │
        ▼
[Agent 层] 调用麦当劳 MCP 取真实菜单与价格 ── query-meals → query-meal-detail → list-nutrition-foods
        │                                     （可选）query-nearby-stores / query-meal-assistance
        ▼
[计算内核] scripts/catering_plan.py  ← 纯标准库、不联网、可单测
        │   枚举 (主食 × 配餐/无 × 饮品/无)，过滤忌口，按预算求解，输出理由
        ▼
[交付物] ① 控制台摘要  ② ledger.csv 分摊台账  ③ index.html 单文件台账卡片
        │
        ▼
[Agent 层] 用 calculate-price 复核金额 → 用户确认后才 create-order（支付始终由本人完成）
```

**分工原则**：取数用 MCP（会变的数据），算账用本地脚本（不该变、必须可复现的逻辑）。所有金额一律用「分」做整数运算，不出现浮点误差。

## 3. 安装与使用示例

环境要求：命令行部分需 Python 3.9+；交互版只需一个现代浏览器。两者均**无第三方依赖**。

### 3.1 安装

```bash
git clone https://github.com/liaojl18340/mcd-catering-ledger.git mcd-catering-ledger
cd mcd-catering-ledger
# 无需 pip install：命令行只依赖 Python 标准库
```

本项目提供两种形态，用途不同：

| 形态 | 文件 | 用途 |
|---|---|---|
| **交互版（推荐）** | `web/app.html` | 打开即可拖动人数、预算、热量、忌口，结果与台账**实时重算**；可切换备选方案、导出 CSV |
| 静态快照 | `demo/index.html` | Python 一次性渲染的台账卡片，适合邮件附件、打印、存档 |

### 3.2 使用示例一：交互版

在线体验（无需登录）：<https://workbuddy.link/p/4fNeDLEtvwFJHz8bHKjF6F>

```bash
# 或本地直接打开，无需服务器、无需联网、无需 MCP Token
open web/app.html          # macOS
start web/app.html         # Windows
```

页面上可操作的四类参数：

- **人数**（3–200 滑块）
- **人均预算**（¥15–¥90）
- **目标人均热量**（300–1100 kcal）
- **忌口**（10 个标签多选，按全组并集过滤）

任一参数改动后，右侧的推荐配比、五项指标、预算进度条、决策依据、备选方案、分摊台账会同步刷新；点击备选行可把它切成主方案；「导出 CSV 台账」下载的表格带 BOM，Excel 直接打开不乱码。

页面内的求解器是 `scripts/catering_plan.py` 的 JavaScript 同规则实现：评分权重、排序 tie-break、零头补足规则逐条一致。已用真实门店菜单（27 个单品）在 Node 中跑过对照：同一组参数（47 人 / ¥40 / 700 kcal）下，两边都给出 `麦香鸡 + 圆筒冰淇淋 + 中杯怡泉+C`，总价 ¥1574.50，人均 ¥33.50，572 kcal，792 个候选中排序结果一致。

### 3.3 使用示例二：命令行 / 批量场景

```bash
# 跑一遍演示（内置样例数据，不需要 MCP Token）
python scripts/catering_plan.py --demo --out demo

# 打开交付物
#   demo/index.html  ← 静态台账卡片（可直接打印/截图）
#   demo/ledger.csv  ← 分摊台账（Excel 可直接打开，已带 BOM 防乱码）

# 用自己的数据跑
python scripts/catering_plan.py --input spec.json --out out
```

演示输出（47 人 · 人均 ¥40 · 2 人忌牛肉）：

```
人数 47 · 人均预算 ¥40.0 · 总预算 ¥1880.0
方案：麦香鸡 + 玉米杯（每人1份） + 可口可乐(中)（每人1份）
总价 ¥1645.0 · 人均 ¥35.0 · 预算占用 87.5% · 人均 690.0 kcal
可行：True · 超预算：False
· 预算内共有 88 个可行组合，按「热量贴合 40% + 品类覆盖 30% + 预算余量 30%」加权取优；
  预算余量达到 15% 即封顶，顶格花完不加分。
```

### 输入格式（`spec.json`）

```json
{
  "people": 47,
  "budget_per_person_cents": 4000,
  "avoid_tags": ["beef"],
  "target_kcal": 700,
  "menu": [
    {"code": "M02", "name": "麦香鸡", "category": "main", "unit_price_cents": 1800,
     "kcal": 400, "tags": ["chicken"]},
    {"code": "S03", "name": "麦乐鸡(20块分享装)", "category": "side", "unit_price_cents": 5200,
     "kcal": 880, "tags": ["chicken", "fried"], "share_per": 4}
  ],
  "people_names": ["张三", "李四"],
  "per_person_avoid": [["beef"], []],
  "meta": {"title": "团队晚餐台账", "subtitle": "47 人 · 人均 ¥40"}
}
```

- `category`：`main`（主食，必选）/ `side`（配餐）/ `drink`（饮品）。
- `share_per`：`1` 表示每人 1 份，`4` 表示每 4 人 1 份（分享装），份数按 `ceil(人数 / share_per)` 计算。
- 金额优先读 `unit_price_cents`（分）；也接受 `unit_price_yuan` 自动换算。
- `avoid_tags` 是**全组并集**：只要有一人忌某个标签，整份方案都不会出现该标签，宁可牺牲最优解也不制造「有人没得吃」。

## 4. 决策算法：为什么是这一份

团餐的决策变量只有三个槽位（主食、配餐、饮品），因此直接**穷举全部候选**而不是上整数规划——好处是每个方案都能被逐条追溯，也方便写测试。

候选的加权得分（权重写死，同一输入永远得到同一方案）：

| 维度 | 权重 | 计算方式 |
|---|---|---|
| 热量贴合 | 40% | `1 - |人均热量 - 目标热量| / 目标热量` |
| 品类覆盖 | 30% | 三类覆盖数 / 3 |
| 预算余量 | 30% | `min(1, 预算余量率 / 15%)` |

「预算余量」这一项值得单独说：**顶格花完预算不加分**。因为团餐最常见的翻车不是超支，而是「刚好花完、临时多来 2 个人」。余量达到 15% 即封顶，再多也不加分——省钱不是目的，别在开饭前 10 分钟慌。

排序规则：得分降序 → 总价升序 → 餐品编码字典序，三级 tie-break 保证确定性。

**不可行时不硬凑**：预算内无解时，输出最省组合 + 明确差额（`over_budget: true`、`deficit_yuan`），并给出三条处置建议（降需求 / 减人数 / 砍槽位），绝不输出一个超预算却标成「推荐」的方案。

## 5. 用了哪些麦当劳 MCP 能力

MCP Server：`https://mcp.mcd.cn`（Streamable HTTP，`Authorization: Bearer <TOKEN>`）。
详细调用流程、参数约束与降级策略见 [MCP_INTEGRATION.md](./MCP_INTEGRATION.md)。

| Tool | 在链路中的作用 |
|---|---|
| `query-meals` | 取当前门店可售餐品（编码、分类、标签），作为候选集 |
| `query-meal-detail` | 取套餐组成与可替换项，决定主食品类的可选范围 |
| `list-nutrition-foods` | 取热量等营养数据，喂给「热量贴合」这一维 |
| `query-nearby-stores` / `delivery-query-stores` | 确认配送范围，避免「算完了才发现不送」 |
| `query-meal-assistance` | 团餐场景下的助餐服务能力确认 |
| `calculate-price` | **金额复核**：本地算出的总价必须与官方算价一致才允许进入下单 |
| `create-order` | 仅在用户明确确认后建单；支付链接交回用户本人 |
| `campaign-calendar` | 判断当日是否有活动/优惠可叠加，避免台账金额与实付不一致 |

## 6. 真实运行记录（2026-10-22）

以下每一个数字都可在 `data/` 目录里的产物中核对，未做任何修饰。

**取数**：门店「麦当劳北京建外SOHO(A座)餐厅」（`storeCode 1950564`），到店自取（`beType=1, orderType=1`），服务器时间 `2026-10-22 15:03:41`（取自 `now-time-info`）。

调用链共 6 个 Tool：`now-time-info` → `query-nearby-stores` → `query-meals` → `query-meal-detail`（27 次）→ `list-nutrition-foods` → `calculate-price`（27 次单价询价）。

**取数结果**：15 个分类、114 个餐品条目；剔除套餐、周边搭售品与无官方热量数据的条目后，得到 27 个可用单品——主食 11、配餐 5、饮品 11。快照见 `data/menu_snapshot.json`。

**求解**（47 人 · 人均 ¥40 · 目标 700 kcal · 无忌口）：麦香鸡 + 圆筒冰淇淋 + 中杯怡泉+C；总价 ¥1574.50，人均 ¥33.50，预算占用 83.8%，人均 572 kcal；预算内可行组合 178 个。

**金额复核**（`scripts/verify_order.py`）：本地按单品单价合计 ¥1574.50，官方 `calculate-price` 合计 ¥1574.50，**差额 ¥0.00**。因单笔件数上限，141 件被拆成两单：99 件 ¥1091.50 + 42 件 ¥483.00。复核结果见 `data/verify_real.json`。

### 两条实测约束：比代码本身更有价值

1. **单笔总件数上限 99 件**。47 人 × 3 件 = 141 件，一次算价返回 `600019 商品超过数量限制`。我实测了边界：99 件通过、100 件被拒。所以团餐不是"算一次价"能解决的，必须拆单，且拆单后要保证合计等于总价。

2. **单价不能用混合订单的行小计反推**。该门店存在「第二份半价」类阶梯优惠：热牛奶小杯单件 ¥15.00，两件 ¥22.50。混合订单会把优惠摊到某些行上，按「小计 ÷ 数量」反推得到的单价会偏低——我第一版就是这么算的，导致本地合计比官方少 ¥180。正确做法是每个餐品用 `quantity=1` 单独询价，`fetch_menu.py` 里那段注释就是这次踩坑的记录。

3. 即便如此，本地规划金额与官方实付仍可能因阶梯优惠出现差额。因此本项目把 `calculate-price` 定为唯一金额口径：本地只做规划与估算，台账金额以官方算价为准。

## 7. 为什么不选「省钱」和「热量」赛道

这不是审美偏好，是看了官方排行榜之后的选择。官方排行榜 [`RANKING.md`](https://github.com/M-China/mcd-developer-innovation-challenge/blob/main/RANKING.md)（更新于 2026-10-22 14:00:58）共 102 个项目在榜，前 10 名里 `mcd-saver-strategist`、`mcd-coupon-strategist`、`mcd-budget-meal`、`mcd-budget-planner` 等至少 4 个项目直接以「省钱/优惠券组合」为主轴，另有 `walk-kcal`、`mcd-calorie-butler`、`mcd-order-calories` 等一批热量营养类项目。

**可验证的部分**：上述项目名称与该时点 Star 数可在 `RANKING.md` 中逐条核对。
**属于推测的部分**：「团餐/B 端预算」方向竞争者较少——这一判断仅基于 102 个项目的名称与简介关键词，我并未逐个拉取全部仓库源码核验，因此只能作为选题倾向，不作为事实断言。

## 8. 目录结构

```
mcd-catering-ledger/
├── SKILL.md                  # WorkBuddy Skill 定义（触发词、流程、边界）
├── README.md
├── CONTEST_DECLARATION.md    # 参赛声明（官方原文）
├── MCP_INTEGRATION.md        # MCP 接入、Tool 调用流程、业务价值
├── mcp-config.example.json   # 脱敏配置（仅环境变量占位）
├── workbuddy.md              # WorkBuddy 开发对话上下文
├── scripts/
│   ├── catering_plan.py      # 计算内核 + CLI
│   ├── fetch_menu.py         # 从 MCP 取真实菜单快照
│   ├── verify_order.py       # 用官方算价复核，超 99 件自动拆单
│   ├── mcp_client.py         # 最小 MCP 客户端（Streamable HTTP，零依赖）
│   ├── demo_data.py          # 演示样例数据（非官方实时数据）
│   └── preflight.py          # 提交前自检：逐条核对赛事硬性要求
├── web/
│   └── app.html              # 交互版页面（真实菜单，参数联动重算）
├── data/
│   ├── menu_snapshot.json    # 真实菜单快照（含门店、时间、工具链元信息）
│   ├── spec_real.json        # 基于真实快照的求解输入
│   ├── plan_real.json        # 求解结果
│   └── verify_real.json      # 官方算价复核记录（含拆单明细）
├── tests/
│   └── test_catering_plan.py # 13 个单元测试，零依赖
└── demo/
    ├── index.html            # Python 生成的静态台账卡片
    └── ledger.csv            # 分摊台账
```

## 9. 测试

```bash
python -m unittest discover -s tests -v
# Ran 13 tests ... OK
```

覆盖：预算充足时三类覆盖、忌口全槽位过滤、无可用主食的显式报错、预算不足的诚实降级、分享装份数向上取整、结果确定性、分摊台账合计等于总价（含除不尽的零头）、CSV 结构、页面零外链。

**提交前自检**：`python scripts/preflight.py` 会逐条核对赛事硬性要求（5 个文件是否齐全、参赛声明是否与官方原文逐字一致、是否残留真实 Token、页面是否含外链、测试是否通过），输出 PASS / FAIL / SKIP 表格，有失败项时退出码非 0。

**双实现对照**：`web/app.html` 内的 JS 求解器与 Python 内核必须给出同一结果。校验方式是把页面脚本抽出后用 Node 运行，比对配方、总价、人均与热量——在真实菜单上两者完全一致（见 §3.2 与 §6）。这是一次性人工核对，尚未固化为自动化测试；如需长期维护，建议把它加进 CI。

## 10. 目标用户

- **团队组织者**：每周要替 20–80 人订加班餐、下午茶、会议茶歇的行政、HR、Tech Lead。
- **需要报销的人**：拿到订单后要交一份「谁吃了什么、每人多少钱」的凭证。
- **做团餐决策的 Agent 开发者**：想要一个可复用的「多人预算约束求解 + 台账生成」内核。

## 11. 边界与免责

- 本仓库的 `scripts/` **不联网、不持有任何凭证**；所有实时数据由 Agent 通过 MCP 取得后写入 JSON。
- `demo_data.py` 中的价格与热量是**演示样例**，不是麦当劳官方数据，不构成任何报价。
- 本工具不代替用户完成支付；`create-order` 返回的支付链接始终由用户本人操作。
- 餐品信息、价格、供应状态与优惠以麦当劳官方渠道的实时结果为准。
- 本项目为个人参赛作品，非麦当劳官方产品。

## 12. 许可

MIT License。详见仓库 `LICENSE`。
