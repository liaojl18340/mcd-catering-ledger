#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提交前自检：逐条核对赛事硬性要求，输出 PASS / FAIL / SKIP。

用途：在 git push 之前跑一次，避免「内容没问题但材料不合规」导致进不了评审。
用法：python scripts/preflight.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 文件 -> (用途说明, 必须出现的关键内容, 最小字节数)
REQUIRED = {
    "README.md": ("项目介绍、安装方法、使用示例、目标用户", ["安装", "使用示例", "目标用户"], 800),
    "CONTEST_DECLARATION.md": ("参赛声明，官方原文", ["原创性声明", "合规声明", "信息安全声明"], 800),
    "MCP_INTEGRATION.md": ("MCP Server / Tool / 调用流程 / 业务价值", ["Tool", "调用流程", "业务价值"], 800),
    "mcp-config.example.json": ("脱敏配置，仅环境变量占位", [], 80),
    "workbuddy.md": ("WorkBuddy 对话上下文", ["WorkBuddy"], 800),
}

results = []


def add(level, name, detail):
    results.append((level, name, detail))


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def check_required_files():
    for rel, (desc, keywords, min_bytes) in REQUIRED.items():
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            add("FAIL", rel, "文件缺失（要求：%s）" % desc)
            continue
        size = os.path.getsize(path)
        if size < min_bytes:
            add("FAIL", rel, "仅 %d 字节，少于要求的 %d 字节" % (size, min_bytes))
            continue
        text = read(rel)
        missing = [k for k in keywords if k not in text]
        if missing:
            add("FAIL", rel, "缺少关键内容：%s" % "、".join(missing))
        else:
            add("PASS", rel, "%d 字节，关键内容齐全" % size)


def check_secrets():
    pat = re.compile(r"Bearer\s+(?!\$\{)[A-Za-z0-9_\-\.]{16,}")
    hits = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "_tmp", "_verify"}]
        for fn in filenames:
            if not fn.endswith((".md", ".py", ".json", ".html", ".txt", ".yml", ".yaml")):
                continue
            full = os.path.join(dirpath, fn)
            try:
                text = open(full, "r", encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for m in pat.finditer(text):
                hits.append("%s: %s..." % (os.path.relpath(full, ROOT), m.group(0)[:24]))
    if hits:
        add("FAIL", "凭证泄露", "疑似真实 Token：%s" % "; ".join(hits[:3]))
    else:
        add("PASS", "凭证泄露", "未发现真实 Token / 密钥")


def check_mcp_config():
    rel = "mcp-config.example.json"
    try:
        data = json.loads(read(rel))
    except Exception as exc:  # noqa: BLE001
        add("FAIL", rel, "JSON 无法解析：%s" % exc)
        return
    servers = data.get("mcpServers") or {}
    if not servers:
        add("FAIL", rel, "缺少 mcpServers 节点")
        return
    auth = ""
    for cfg in servers.values():
        auth += str((cfg.get("headers") or {}).get("Authorization", ""))
    if "${" in auth:
        add("PASS", rel, "使用环境变量占位符，未硬编码 Token")
    else:
        add("FAIL", rel, "Authorization 未使用环境变量占位符")


def check_declaration_matches_official():
    url = ("https://raw.githubusercontent.com/M-China/mcd-developer-innovation-challenge/"
           "main/CONTEST_DECLARATION.md")
    try:
        remote = urllib.request.urlopen(url, timeout=15).read().decode("utf-8")
    except Exception:
        add("SKIP", "参赛声明原文比对", "无法访问网络，请自行确认与官方一致")
        return
    local = read("CONTEST_DECLARATION.md")
    if local.strip() == remote.strip():
        add("PASS", "参赛声明原文比对", "与官方文件逐字一致")
    else:
        add("FAIL", "参赛声明原文比对", "与官方文件存在差异，须改回原文")


def check_no_external_links():
    for rel in ("web/app.html", "demo/index.html"):
        if not os.path.isfile(os.path.join(ROOT, rel)):
            add("FAIL", rel, "文件缺失")
            continue
        text = read(rel)
        n = len(re.findall(r"https?://", text))
        if n:
            add("FAIL", rel, "存在 %d 处外链，发布后可能变死链" % n)
        else:
            add("PASS", rel, "零外链，无失效图片/字体风险")


def check_tests():
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if proc.returncode == 0:
        add("PASS", "单元测试", "全部通过")
    else:
        add("FAIL", "单元测试", (proc.stderr or proc.stdout).strip().splitlines()[-1] if (proc.stderr or proc.stdout) else "失败")


def check_hygiene():
    bad = []
    for name in (".env", "token.txt", "id_rsa", "id_ed25519"):
        if os.path.exists(os.path.join(ROOT, name)):
            bad.append(name)
    if bad:
        add("FAIL", "敏感文件", "存在：%s" % "、".join(bad))
    else:
        add("PASS", "敏感文件", "无 .env / 私钥文件")


def main() -> int:
    print("提交前自检 · %s\n" % ROOT)
    check_required_files()
    check_mcp_config()
    check_secrets()
    check_declaration_matches_official()
    check_no_external_links()
    check_hygiene()
    check_tests()

    width = max(len(r[1]) for r in results)
    for level, name, detail in results:
        mark = {"PASS": "[PASS]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}[level]
        print("%-6s %-*s  %s" % (mark, width, name, detail))

    fails = [r for r in results if r[0] == "FAIL"]
    print("\n结论：%d 项通过，%d 项失败，%d 项跳过" % (
        len([r for r in results if r[0] == "PASS"]), len(fails),
        len([r for r in results if r[0] == "SKIP"])))
    if fails:
        print("必须先修复失败项，再提交报名。")
        return 1
    print("材料齐备，可以推送仓库并提交报名 Issue。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
