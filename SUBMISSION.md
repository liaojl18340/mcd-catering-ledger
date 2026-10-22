# 下一步操作手册

从「本地有一套完整材料」到「报名成功进入排行榜」，共 5 步。**标 ★ 的步骤只能你本人完成**，涉及账号、手机号与对外发布，我不代为操作。

时间基准：今天 2026-10-22，报名与排名截止 **2026-10-25 23:59（北京时间）**，剩约 3 天。

---

## 第 1 步 ★ 申请麦当劳 MCP Token

1. 打开 `https://open.mcd.cn/mcp`。
2. 右上角「登录」，用手机号验证登录。
3. 点击右上角「控制台」→「激活」→ 同意服务协议 → 复制 Token。

> Token 只能放在环境变量里，不要写进仓库任何文件。`mcp-config.example.json` 里的 `Bearer ${MCD_MCP_TOKEN}` 是占位符，保持原样。

## 第 2 步 ★ 在 WorkBuddy 里接上麦当劳 MCP，跑一次真实数据

> 状态：**已完成**（2026-10-22 15:03）。真实门店 27 个单品、真实单价与热量、官方算价复核差额 ¥0.00，产物在 `data/`。以下步骤保留，供换城市/换门店时重跑。

1. 在 WorkBuddy 连接器管理页打开自定义连接器入口，粘贴以下配置，并把 `${MCD_MCP_TOKEN}` 换成本机环境变量引用或真实 Token（只在本地配置里用，不进仓库）：

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": { "Authorization": "Bearer ${MCD_MCP_TOKEN}" }
    }
  }
}
```

2. 保存后点「信任」，确认连接状态正常。
3. 回到对话里，让我按 `SKILL.md` 的流程取一次**真实菜单**（`query-meals` → `query-meal-detail` → `list-nutrition-foods`），生成一份真实 `spec.json` 跑出结果。
4. 把这次的输出贴回对话，我帮你写进 README 的「真实运行记录」一节，并附上截图。

> 为什么必须先做这一步：现在在线演示链接用的是内置样例数据。评委会检查仓库是否真的接了 MCP；仓库里如果只有样例数据、没有一次真实运行痕迹，很容易被判为「套模板」。

## 第 3 步 ★ 本地仓库初始化并推送

```bash
cd mcd-catering-ledger
python scripts/preflight.py        # 先自检，必须 0 项失败

git init -b main
git add -A
git commit -m "feat: 麦麦团餐台账 - 团餐预算求解与分摊台账"
git remote add origin https://github.com/liaojunlin/mcd-catering-ledger.git
git push -u origin main
```

注意事项：

- 仓库必须**公开可访问**，否则无法进入榜单统计。
- 仓库创建时间需落在北京时间 2025-12-25 00:00 至 2026-10-25 23:59 之间——新仓库天然满足。
- 推送前确认 `git status` 里没有 `.env`、`spec.json` 之类含本地数据的文件（`.gitignore` 已覆盖）。
- 同一 GitHub 账号有多个参赛项目时，只有 Star 最高的那个进榜，不要分散兵力。

## 第 4 步 ★ 自检通过后再提交报名 Issue

官方渠道：`https://github.com/M-China/mcd-developer-innovation-challenge/issues`

点击 New issue，若列表里出现专用模板就选它；没有模板则用下面这段正文（三段结构，不多写）：

```text
【参赛申请】
项目名称：麦麦团餐台账（mcd-catering-ledger）
项目地址：https://github.com/liaojunlin/mcd-catering-ledger
项目简介：替全组点饭的人用的团餐决策与报销台账。在人均预算与全员忌口约束下求解可解释的配餐组合，并输出可直接交财务的分摊台账（CSV）与可打印台账卡片（HTML）。核心计算本地完成、零第三方依赖，取数走麦当劳 MCP，金额以官方算价复核。
```

提交后官方系统会回复是否报名成功。**没有这条 Issue，仓库推得再漂亮也不进榜。**

## 第 5 步 拉 Star（合规前提下）

排名**只看 GitHub 公开 Star 数**，截止 2026-10-26 00:00。可验证的事实：官方 `RANKING.md`（2026-10-22 14:00 更新）显示头部项目在 800+ Star 量级，前 10 名中至少 4 个是「省钱/优惠券」方向。

合规且有效的做法：

1. **README 首屏就有可点的在线体验**——已加：`https://workbuddy.link/p/4fNeDLEtvwFJHz8bHKjF6F`
2. **陌生人 30 秒能跑起来**——`python scripts/catering_plan.py --demo --out demo` 不需要 Token。
3. **讲一个具体场景**，不要讲架构。47 人、人均 ¥40、两人不吃牛肉、要报销，这个场景比任何形容词都有用。
4. **把开发过程写成一篇公开文章**（掘金/腾讯云社区），文末放仓库链接。现有参赛者的公开记录显示，文章带来的 Star 通常多于仓库自然流量（此条属经验判断，非官方数据）。

**绝对不能做**：买 Star、互刷、批量小号、脚本操作。规则明确写了操纵 Star 数据会取消资格与奖品，并可能被追究赔偿。

---

## 提交前 3 分钟自查

```bash
python scripts/preflight.py
python -m unittest discover -s tests
```

自检覆盖：5 个必需文件是否齐全、参赛声明是否与官方原文逐字一致、是否残留真实 Token、页面是否含外链（避免死链）、敏感文件、单元测试。当前状态：**11 项通过，0 项失败，1 项跳过**（跳过项是联网比对原文，已另外用 `cmp` 手工确认与官方逐字一致）。

## 当前材料状态

| 项目 | 状态 |
|---|---|
| 5 个必需文件 | 齐全 |
| 参赛声明 | 与官方原文 `cmp` 一致 |
| 在线演示 | 已发布（交互版） |
| 真实 MCP 调用 | **已完成**：北京建外SOHO店，27 个真实单品，官方算价复核差额 ¥0.00（见 `data/`） |
| GitHub 仓库 | 本地已提交（commit 1261ab4，24 个文件），远端未创建、未推送 |
| 报名 Issue | **未提交，卡在第 4 步** |
