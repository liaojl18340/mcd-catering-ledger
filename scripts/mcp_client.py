#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最小可用的麦当劳 MCP 客户端（Streamable HTTP，仅标准库）。

Token 只从环境变量 MCD_MCP_TOKEN 读取，绝不落盘、绝不写进仓库。

用法：
  export MCD_MCP_TOKEN=xxxx            # 不要提交到仓库
  python scripts/mcp_client.py --list-tools
  python scripts/mcp_client.py --call list-nutrition-foods --args '{}'
  python scripts/mcp_client.py --call query-meals --args '{"beCode":"..."}' --dump out.json

设计取舍：不引入官方 SDK，是因为本项目要求零第三方依赖；
Streamable HTTP 的握手只有 initialize / notifications/initialized / tools/list / tools/call 四步，
手写一次比背一个依赖更可控，也方便审阅。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ENDPOINT = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "mcd-catering-ledger", "version": "0.1.0"}


class McpError(RuntimeError):
    pass


def _parse_body(raw: bytes, content_type: str):
    """兼容两种返回：application/json 与 text/event-stream（SSE）。"""
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    if "text/event-stream" in content_type:
        payloads = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if chunk and chunk != "[DONE]":
                    payloads.append(json.loads(chunk))
        return payloads[-1] if payloads else None
    return json.loads(text)


class McpClient:
    def __init__(self, token: str, endpoint: str = ENDPOINT, timeout: int = 30):
        if not token:
            raise McpError("缺少 MCD_MCP_TOKEN 环境变量")
        self.endpoint = endpoint
        self.token = token
        self.timeout = timeout
        self.session_id = None
        self._id = 0

    def _post(self, payload: dict, expect_response: bool = True):
        self._id += 1
        if expect_response:
            payload["id"] = self._id
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + self.token,
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            if exc.code == 401:
                raise McpError("Token 无效或已过期（401）。请到 open.mcd.cn/mcp 控制台重新激活。") from exc
            if exc.code == 429:
                raise McpError("触发限流（429，约 600 次/分钟）。请降低调用频率后重试。") from exc
            raise McpError("HTTP %s: %s" % (exc.code, detail)) from exc
        if not expect_response:
            return None
        msg = _parse_body(raw, ctype)
        if isinstance(msg, dict) and msg.get("error"):
            err = msg["error"]
            raise McpError("工具返回错误：%s %s" % (err.get("code"), err.get("message")))
        return msg

    def initialize(self):
        msg = self._post({
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        })
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                   expect_response=False)
        return (msg or {}).get("result", {})

    def list_tools(self):
        msg = self._post({"jsonrpc": "2.0", "method": "tools/list", "params": {}})
        return (msg or {}).get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict):
        msg = self._post({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        result = (msg or {}).get("result", {})
        return result


def _content_text(result: dict) -> str:
    chunks = []
    for part in result.get("content") or []:
        if part.get("type") == "text":
            chunks.append(part.get("text", ""))
        else:
            chunks.append(json.dumps(part, ensure_ascii=False))
    return "\n".join(chunks)


def first_json(text: str):
    """工具返回常是「JSON + 一段给人看的说明文字」，这里只取第一个完整 JSON 对象。"""
    idx = text.find('{"')
    while idx != -1:
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[idx:])
            return obj
        except ValueError:
            idx = text.find('{"', idx + 1)
    return None


def call_json(client: "McpClient", name: str, arguments: dict):
    """调用 Tool 并把结果解析成 dict（失败返回 None）。"""
    result = client.call_tool(name, arguments)
    return first_json(_content_text(result))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="麦当劳 MCP 最小客户端（Streamable HTTP）")
    parser.add_argument("--list-tools", action="store_true", help="列出全部 Tool 及入参 schema")
    parser.add_argument("--call", help="调用指定 Tool")
    parser.add_argument("--args", default="{}", help="Tool 入参 JSON")
    parser.add_argument("--dump", help="把结果写入指定文件（不含 Token）")
    parser.add_argument("--raw", action="store_true", help="输出原始 JSON，不折叠")
    args = parser.parse_args(argv)

    token = os.environ.get("MCD_MCP_TOKEN", "").strip()
    try:
        client = McpClient(token)
        info = client.initialize()
        if args.list_tools:
            tools = client.list_tools()
            rows = []
            for tool in tools:
                schema = tool.get("inputSchema") or {}
                rows.append({
                    "name": tool.get("name"),
                    "title": (tool.get("annotations") or {}).get("title") or tool.get("title") or "",
                    "required": schema.get("required") or [],
                    "properties": list((schema.get("properties") or {}).keys()),
                })
            print("server:", json.dumps(info.get("serverInfo", {}), ensure_ascii=False))
            print("protocol:", info.get("protocolVersion"))
            print("tools:", len(rows))
            for row in rows:
                print("- %-28s required=%s props=%s" % (
                    row["name"], ",".join(row["required"]) or "-", ",".join(row["properties"])[:120]))
            if args.dump:
                with open(args.dump, "w", encoding="utf-8") as fh:
                    json.dump(tools, fh, ensure_ascii=False, indent=2)
            return 0

        if args.call:
            result = client.call_tool(args.call, json.loads(args.args))
            text = _content_text(result)
            if args.raw:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(text[:4000])
            if args.dump:
                with open(args.dump, "w", encoding="utf-8") as fh:
                    fh.write(text)
            return 0

        parser.error("需要 --list-tools 或 --call")
    except McpError as exc:
        print("调用失败：%s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
