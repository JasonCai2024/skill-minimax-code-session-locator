#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
read_session.py — 读取并解析 MiniMax Code (Mavis / OpenCode 运行时) 会话消息与快照。

用法:
    python read_session.py --session-id <session_id>
    python read_session.py --session-id <session_id> --summary
    python read_session.py --session-id <session_id> --turn 3
    python read_session.py --session-id <session_id> --snapshots
    python read_session.py --path "C:\\Users\\pc\\.minimax\\v2\\sessions\\...\\messages.jsonl"
    python read_session.py --session-id <session_id> --json
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def resolve_minimax_home(explicit: Optional[str] = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("MINIMAX_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".minimax"


def extract_content_text(content_obj: Any) -> str:
    if isinstance(content_obj, str):
        return content_obj
    if isinstance(content_obj, list):
        parts = []
        for item in content_obj:
            if isinstance(item, dict):
                t = item.get("text") or item.get("content") or item.get("rawContent")
                if t:
                    parts.append(str(t))
                elif item.get("type") == "tool_use":
                    parts.append(f"[Tool Call: {item.get('name', 'tool')}]")
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    if isinstance(content_obj, dict):
        return content_obj.get("text") or content_obj.get("content") or json.dumps(content_obj, ensure_ascii=False)
    return str(content_obj) if content_obj is not None else ""


@dataclass
class MiniMaxTurn:
    index: int
    turn_id: Optional[str]
    message_id: Optional[str]
    role: str
    content: str
    thinking: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    def preview(self, max_len: int = 100) -> str:
        s = self.content.replace("\n", " ").strip()
        if not s and self.tool_calls:
            names = [tc.get("name", "tool") for tc in self.tool_calls]
            s = f"[Tool Call: {', '.join(names)}]"
        elif not s and self.thinking:
            s = f"[Thinking: {self.thinking[:40]}...]"
        return s if len(s) <= max_len else s[: max_len - 3] + "..."

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "turn_id": self.turn_id,
            "message_id": self.message_id,
            "role": self.role,
            "content_preview": self.preview(),
            "has_thinking": bool(self.thinking),
            "tool_call_count": len(self.tool_calls),
            "tool_calls": self.tool_calls,
        }


def parse_minimax_message_line(obj: Dict[str, Any], index: int) -> Optional[MiniMaxTurn]:
    msg_id = obj.get("message_id") or obj.get("id")
    turn_id = obj.get("turn_id")
    inner_msg = obj.get("message") or obj

    role = inner_msg.get("role") or obj.get("role") or "unknown"
    content_raw = inner_msg.get("content") or obj.get("content")
    content = extract_content_text(content_raw)

    thinking = inner_msg.get("thinking") or obj.get("thinking")
    if not thinking and isinstance(content_raw, list):
        for part in content_raw:
            if isinstance(part, dict) and part.get("type") in ("thinking", "reasoning"):
                thinking = part.get("text") or part.get("thinking")

    tool_calls = []
    if isinstance(content_raw, list):
        for part in content_raw:
            if isinstance(part, dict) and part.get("type") in ("tool_use", "tool_call"):
                tool_calls.append({
                    "name": part.get("name"),
                    "args": part.get("input") or part.get("arguments"),
                })
    if "tool_calls" in inner_msg:
        tool_calls.extend(inner_msg["tool_calls"])

    return MiniMaxTurn(
        index=index,
        turn_id=str(turn_id) if turn_id else None,
        message_id=str(msg_id) if msg_id else None,
        role=role,
        content=content,
        thinking=thinking,
        tool_calls=tool_calls,
    )


def read_minimax_session(session_dir: Path, session_id: Optional[str] = None) -> Dict[str, Any]:
    if not session_dir.exists():
        raise FileNotFoundError(f"MiniMax 会话目录不存在: {session_dir}")

    manifest_file = session_dir / "manifest.json"
    messages_file = session_dir / "messages.jsonl"
    snapshot_file = session_dir / "snapshot.json"
    reports_dir = session_dir / "reports"

    manifest_data = {}
    if manifest_file.exists():
        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
        except Exception:
            pass

    sid = session_id or manifest_data.get("sessionId") or session_dir.name
    turns: List[MiniMaxTurn] = []
    parse_errors: List[Dict[str, Any]] = []

    if messages_file.exists():
        with open(messages_file, "r", encoding="utf-8", errors="ignore") as f:
            for lineno, raw_line in enumerate(f, 1):
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    obj = json.loads(raw_line)
                except json.JSONDecodeError as e:
                    parse_errors.append({"line": lineno, "error": str(e), "raw": raw_line[:150]})
                    continue

                turn = parse_minimax_message_line(obj, len(turns) + 1)
                if turn:
                    turns.append(turn)

    role_counts: Dict[str, int] = {}
    tool_call_count = 0
    for t in turns:
        role_counts[t.role] = role_counts.get(t.role, 0) + 1
        tool_call_count += len(t.tool_calls)

    reports = []
    if reports_dir.exists() and reports_dir.is_dir():
        reports = [str(p.name) for p in reports_dir.glob("*") if p.is_file()]

    snapshot_info = None
    if snapshot_file.exists():
        try:
            sz = snapshot_file.stat().st_size
            snapshot_info = {"size_bytes": sz, "path": str(snapshot_file)}
        except Exception:
            pass

    return {
        "session_id": sid,
        "session_dir": str(session_dir),
        "manifest": manifest_data,
        "stats": {
            "total_turns": len(turns),
            "role_counts": role_counts,
            "tool_call_count": tool_call_count,
            "has_snapshot": snapshot_file.exists(),
            "reports_count": len(reports),
        },
        "snapshot_info": snapshot_info,
        "reports": reports,
        "turns": turns,
        "parse_errors": parse_errors,
    }


def render_summary(result: Dict[str, Any]) -> str:
    manifest = result.get("manifest", {})
    stats = result["stats"]
    c_ms = manifest.get("createdAtMs")
    u_ms = manifest.get("updatedAtMs")
    c_time = datetime.fromtimestamp(c_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if c_ms else "-"
    u_time = datetime.fromtimestamp(u_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if u_ms else "-"

    lines = []
    lines.append(f"MiniMax Code 会话 ID: {result['session_id']}")
    lines.append(f"会话物理目录:        {result['session_dir']}")
    lines.append(f"创建时间 (UTC):       {c_time}")
    lines.append(f"更新时间 (UTC):       {u_time}")
    lines.append("")
    lines.append("统计信息:")
    lines.append(f"  对话总轮次:         {stats['total_turns']}")
    lines.append(f"  角色消息分布:       {stats['role_counts']}")
    lines.append(f"  工具调用数量:       {stats['tool_call_count']}")
    lines.append(f"  包含状态快照:       {'是' if stats['has_snapshot'] else '否'}")
    lines.append(f"  成果物报告数量:     {stats['reports_count']} 个")

    reports = result.get("reports", [])
    if reports:
        lines.append("")
        lines.append(f"成果物报告清单:")
        for rep in reports:
            lines.append(f"  - {rep}")

    turns = result["turns"]
    lines.append("")
    lines.append(f"交互轨迹列表 (共 {len(turns)} 轮):")
    lines.append(f"{'#':<4} {'角色':<14} {'工具调用':<8} {'内容预览'}")
    lines.append("-" * 90)
    for t in turns:
        tc_str = f"{len(t.tool_calls)} 个" if t.tool_calls else "-"
        lines.append(f"{t.index:<4} {t.role:<14} {tc_str:<8} {t.preview(55)}")

    return "\n".join(lines)


def render_turn_detail(turn: MiniMaxTurn) -> str:
    lines = []
    lines.append(f"Turn #{turn.index} [{turn.role}] (Message ID: {turn.message_id or '-'}, Turn ID: {turn.turn_id or '-'})")
    lines.append("=" * 80)
    if turn.thinking:
        lines.append("【Thinking 思考过程】")
        lines.append(turn.thinking)
        lines.append("-" * 80)
    if turn.content:
        lines.append("【Content 正文】")
        lines.append(turn.content)
    if turn.tool_calls:
        lines.append("-" * 80)
        lines.append(f"【Tool Calls 工具调用 ({len(turn.tool_calls)} 个)】")
        for i, tc in enumerate(turn.tool_calls, 1):
            lines.append(f"  {i}. {tc.get('name')}:")
            lines.append(f"     {json.dumps(tc.get('args') or {}, ensure_ascii=False, indent=2)}")
    lines.append("=" * 80)
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="read_session.py",
        description="读取并解析 MiniMax Code 对话消息与快照",
    )
    p.add_argument("--session-id", "-s", help="MiniMax 会话 ID")
    p.add_argument("--path", "-p", help="messages.jsonl 文件绝对路径")
    p.add_argument("--dir", "-d", help="会话完整物理目录路径")
    p.add_argument("--minimax-home", help="自定义 MiniMax 主目录")
    p.add_argument("--turn", "-t", type=int, help="输出指定 turn 编号的完整内容")
    p.add_argument("--summary", action="store_true", help="输出结构化会话摘要（默认）")
    p.add_argument("--snapshots", action="store_true", help="查看该会话快照信息")
    p.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if not args.session_id and not args.path and not args.dir:
        print("错误: 必须指定 --session-id, --path 或 --dir", file=sys.stderr)
        return 2

    base_dir = resolve_minimax_home(args.minimax_home)
    session_dir = None
    session_id = args.session_id

    if args.dir:
        session_dir = Path(args.dir)
    elif args.path:
        p = Path(args.path)
        session_dir = p.parent
    else:
        # 通过 session_id 探测目录
        v2_sessions_dir = base_dir / "v2" / "sessions"
        b64_part = base64.b64encode(session_id.encode("utf-8")).decode("utf-8").replace("=", "")
        matches = list(v2_sessions_dir.glob(f"*/*/*/*{b64_part}*"))
        if matches:
            session_dir = matches[0]
        else:
            for mf in v2_sessions_dir.glob("*/*/*/manifest.json"):
                try:
                    with open(mf, "r", encoding="utf-8") as f:
                        d = json.load(f)
                        if d.get("sessionId") == session_id:
                            session_dir = mf.parent
                            break
                except Exception:
                    continue

    if not session_dir or not session_dir.exists():
        print(f"错误: 未找到会话 {session_id} 对应的物理目录", file=sys.stderr)
        return 2

    try:
        data = read_minimax_session(session_dir, session_id=session_id)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2

    if args.snapshots:
        snap = data.get("snapshot_info")
        if args.json:
            print(json.dumps(snap or {}, ensure_ascii=False, indent=2))
        else:
            print(f"MiniMax 会话 {data['session_id']} 快照信息:")
            print("=" * 80)
            if snap:
                print(f"快照文件: {snap['path']} ({snap['size_bytes']} 字节)")
            else:
                print("未生成 snapshot.json 快照。")
        return 0

    if args.turn is not None:
        turns = data["turns"]
        if 1 <= args.turn <= len(turns):
            target = turns[args.turn - 1]
            if args.json:
                print(json.dumps(target.to_dict(), ensure_ascii=False, indent=2))
            else:
                print(render_turn_detail(target))
            return 0
        else:
            print(f"错误: turn {args.turn} 超出范围 (共 {len(turns)} 轮交互)", file=sys.stderr)
            return 2

    if args.json:
        out = {
            "session_id": data["session_id"],
            "session_dir": data["session_dir"],
            "manifest": data["manifest"],
            "stats": data["stats"],
            "snapshot_info": data["snapshot_info"],
            "reports": data["reports"],
            "turns": [t.to_dict() for t in data["turns"]],
            "parse_errors": data["parse_errors"],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(render_summary(data))

    return 0


if __name__ == "__main__":
    sys.exit(main())
