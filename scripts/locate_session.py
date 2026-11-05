#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
locate_session.py — 定位 MiniMax Code (Mavis / OpenCode 运行时) 本地会话。

用法:
    python locate_session.py --workspace "ForAgent" --time "yesterday"
    python locate_session.py --workspace "社交媒体" --limit 5
    python locate_session.py --archived-only --limit 10
    python locate_session.py --keyword "解构" --json

输出:
    默认人类可读表格；--json 时输出结构化 JSON。
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_LIMIT = 10
MAX_WINDOW_DAYS = 30


@dataclass
class TimeWindow:
    start_utc: datetime
    end_utc: datetime
    parsed_from: str

    def width_days(self) -> float:
        return (self.end_utc - self.start_utc).total_seconds() / 86400

    def start_ms(self) -> int:
        return int(self.start_utc.timestamp() * 1000)

    def end_ms(self) -> int:
        return int(self.end_utc.timestamp() * 1000)


_CN_TOD = [
    ("凌晨", (0, 6)),
    ("上午", (6, 12)),
    ("中午", (11, 14)),
    ("下午", (12, 18)),
    ("傍晚", (17, 20)),
    ("晚上", (18, 24)),
    ("夜里", (20, 24)),
    ("深夜", (22, 24)),
]

_EN_TOD = [
    ("early morning", (0, 6)),
    ("late night", (22, 24)),
    ("morning", (6, 12)),
    ("noon", (11, 14)),
    ("afternoon", (12, 18)),
    ("evening", (17, 20)),
    ("night", (18, 24)),
]


def parse_time_hint(hint: str, now: Optional[datetime] = None) -> TimeWindow:
    if now is None:
        now = datetime.now().astimezone()

    hint_norm = hint.strip().lower()
    if not hint_norm:
        raise ValueError("时间提示为空")

    iso = _try_parse_iso(hint_norm, now)
    if iso:
        return iso

    day_anchor, consumed = _parse_day_anchor(hint_norm, now)
    if day_anchor is None:
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_anchor, consumed = today, ""

    remainder = hint_norm.replace(consumed, "").strip()
    start_t, end_t = _match_time_of_day(remainder)

    hour_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", remainder)
    if hour_match:
        h = int(hour_match.group(1))
        m = int(hour_match.group(2) or 0)
        ampm = hour_match.group(3)
        if ampm == "pm" and h < 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        if 0 <= h <= 23:
            start_dt = day_anchor.replace(hour=h, minute=m, second=0, microsecond=0)
            end_dt = start_dt + timedelta(hours=4)
            return TimeWindow(start_dt.astimezone(timezone.utc), end_dt.astimezone(timezone.utc), hint)

    end_hour = 23 if end_t == 24 else end_t
    end_minute = 59 if end_t == 24 else 0
    end_second = 59 if end_t == 24 else 0
    start_dt = day_anchor.replace(hour=start_t, minute=0, second=0, microsecond=0)
    end_dt = day_anchor.replace(hour=end_hour, minute=end_minute, second=end_second, microsecond=0)
    return TimeWindow(start_dt.astimezone(timezone.utc), end_dt.astimezone(timezone.utc), hint)


def _try_parse_iso(hint: str, now: datetime) -> Optional[TimeWindow]:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(hint, fmt).replace(tzinfo=now.tzinfo)
            return TimeWindow(
                (dt - timedelta(hours=2)).astimezone(timezone.utc),
                (dt + timedelta(hours=2)).astimezone(timezone.utc),
                hint,
            )
        except ValueError:
            pass
    try:
        d = datetime.strptime(hint, "%Y-%m-%d").replace(tzinfo=now.tzinfo)
        return TimeWindow(
            d.astimezone(timezone.utc),
            (d + timedelta(days=1) - timedelta(seconds=1)).astimezone(timezone.utc),
            hint,
        )
    except ValueError:
        return None


def _parse_day_anchor(hint: str, now: datetime) -> Tuple[Optional[datetime], str]:
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if re.search(r"\btoday\b|今天", hint):
        return today, "today" if "today" in hint else "今天"
    if re.search(r"\byesterday\b|昨天", hint):
        return today - timedelta(days=1), "yesterday" if "yesterday" in hint else "昨天"
    if re.search(r"day before yesterday|前天", hint):
        consumed = "day before yesterday" if "day before yesterday" in hint else "前天"
        return today - timedelta(days=2), consumed
    m = re.search(r"(\d+)\s*days?\s*ago|(\d+)\s*天前", hint)
    if m:
        n = int(m.group(1) or m.group(2))
        return today - timedelta(days=n), m.group(0)
    if re.search(r"\blast\s+week\b|上周", hint):
        consumed = "last week" if "last week" in hint else "上周"
        return today - timedelta(days=7), consumed
    m = re.search(r"\d{4}-\d{2}-\d{2}", hint)
    if m:
        try:
            d = datetime.strptime(m.group(0), "%Y-%m-%d")
            return d.replace(tzinfo=now.tzinfo), m.group(0)
        except ValueError:
            pass
    return None, ""


def _match_time_of_day(remainder: str) -> Tuple[int, int]:
    for kw, (s, e) in _CN_TOD:
        if kw in remainder:
            return s, e
    for kw, (s, e) in _EN_TOD:
        pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(pattern, remainder):
            return s, e
    return 0, 24


def resolve_minimax_home(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("MINIMAX_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".minimax"


@dataclass
class MiniMaxSessionRecord:
    session_id: str
    title: str
    workspace: str
    agent_name: str
    runtime: str
    status: str
    is_archived: bool
    created_at: str
    updated_at: str
    session_dir: Optional[str]
    messages_path: Optional[str]
    manifest_path: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "workspace": self.workspace,
            "agent_name": self.agent_name,
            "runtime": self.runtime,
            "status": self.status,
            "is_archived": self.is_archived,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "session_dir": self.session_dir,
            "messages_path": self.messages_path,
            "manifest_path": self.manifest_path,
        }


def find_session_dir_by_id(v2_sessions_dir: Path, session_id: str) -> Optional[Path]:
    if not v2_sessions_dir.exists():
        return None
    # 路径命名规范: v2/sessions/{YYYY}/{MM}/{DD}/*session_<base64_id>
    # 先尝试 base64 编码匹配
    b64_part = base64.b64encode(session_id.encode("utf-8")).decode("utf-8").replace("=", "")
    matches = list(v2_sessions_dir.glob(f"*/*/*/*{b64_part}*"))
    if matches:
        return matches[0]

    # 兜底直接遍历查找 manifest.json
    for mf in v2_sessions_dir.glob("*/*/*/manifest.json"):
        try:
            with open(mf, "r", encoding="utf-8") as f:
                d = json.load(f)
                if d.get("sessionId") == session_id:
                    return mf.parent
        except Exception:
            continue
    return None


def locate_minimax_sessions(
    base_dir: Path,
    workspace_kw: Optional[str] = None,
    time_window: Optional[TimeWindow] = None,
    title_kw: Optional[str] = None,
    keyword_kw: Optional[str] = None,
    archived_mode: str = "all",
    limit: int = DEFAULT_LIMIT,
) -> Tuple[List[MiniMaxSessionRecord], List[Tuple[str, int]]]:
    db_path = base_dir / "v2" / "sqlite" / "runtime-state.sqlite"
    v2_sessions_dir = base_dir / "v2" / "sessions"

    if not db_path.exists():
        raise FileNotFoundError(f"未找到 MiniMax SQLite 数据库: {db_path}")

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # 健康校验
    integrity = cur.execute("PRAGMA integrity_check").fetchone()
    if not integrity or integrity[0] != "ok":
        conn.close()
        raise RuntimeError(f"MiniMax runtime-state.sqlite 完整性检查失败: {integrity}")

    # 提取高频工作区
    distinct_rows = cur.execute(
        "SELECT workspace_dir, COUNT(*) as c FROM local_runtime_sessions WHERE workspace_dir IS NOT NULL AND workspace_dir != '' GROUP BY workspace_dir ORDER BY c DESC LIMIT 20"
    ).fetchall()
    distinct_ws = [(r[0], r[1]) for r in distinct_rows]

    # 构造 SQL
    sql = """
    SELECT session_id, title, workspace_dir, agent_name, runtime, status, archived, visibility, created_at_ms, updated_at_ms
    FROM local_runtime_sessions
    WHERE 1=1
    """
    params: List[Any] = []

    if workspace_kw:
        sql += " AND workspace_dir LIKE ?"
        params.append(f"%{workspace_kw}%")

    if title_kw:
        sql += " AND title LIKE ?"
        params.append(f"%{title_kw}%")

    if archived_mode == "archived_only":
        sql += " AND (archived = 1 OR visibility = 'archived')"
    elif archived_mode == "active_only":
        sql += " AND (archived = 0 AND visibility != 'archived')"

    if time_window:
        sql += " AND updated_at_ms >= ? AND updated_at_ms <= ?"
        params.append(time_window.start_ms())
        params.append(time_window.end_ms())

    sql += " ORDER BY updated_at_ms DESC"

    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    conn.close()

    results: List[MiniMaxSessionRecord] = []
    # 建立 manifest 缓存映射提高定位性能
    manifest_cache: Dict[str, Path] = {}
    if v2_sessions_dir.exists():
        for mf in v2_sessions_dir.glob("*/*/*/*/manifest.json"):
            # 提取目录名末尾或读取 sessionId
            manifest_cache[mf.parent.name] = mf

    for r in rows:
        sid, title, ws_dir, agent, rt, stat, is_arch, vis, c_ms, u_ms = r
        ws_dir = ws_dir or "(未关联工作区)"

        # 查找物理目录
        s_dir = None
        b64_part = base64.b64encode(sid.encode("utf-8")).decode("utf-8").replace("=", "")
        for dirname, mf_path in manifest_cache.items():
            if b64_part in dirname or sid in dirname:
                s_dir = mf_path.parent
                break

        if not s_dir:
            s_dir = find_session_dir_by_id(v2_sessions_dir, sid)

        msg_file = (s_dir / "messages.jsonl") if s_dir else None
        manifest_file = (s_dir / "manifest.json") if s_dir else None

        # 关键词过滤
        if keyword_kw:
            matched_kw = False
            if msg_file and msg_file.exists():
                try:
                    with open(msg_file, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        if keyword_kw.lower() in content.lower():
                            matched_kw = True
                except Exception:
                    pass
            if not matched_kw:
                continue

        c_str = datetime.fromtimestamp(c_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if c_ms else "(未知)"
        u_str = datetime.fromtimestamp(u_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if u_ms else "(未知)"

        record = MiniMaxSessionRecord(
            session_id=sid,
            title=title or "(无标题)",
            workspace=ws_dir,
            agent_name=agent or "minimax",
            runtime=rt or "pi-agent",
            status=stat or "unknown",
            is_archived=bool(is_arch) or (vis == "archived"),
            created_at=c_str,
            updated_at=u_str,
            session_dir=str(s_dir) if s_dir else None,
            messages_path=str(msg_file) if msg_file and msg_file.exists() else None,
            manifest_path=str(manifest_file) if manifest_file and manifest_file.exists() else None,
        )
        results.append(record)
        if len(results) >= limit:
            break

    return results, distinct_ws


def render_table(records: List[MiniMaxSessionRecord]) -> str:
    if not records:
        return "(无匹配记录)"
    lines = []
    lines.append(f"{'#':<3} {'Session ID':<36} {'状态':<6} {'Agent':<8} {'更新时间(UTC)':<19} {'标题 / 工作区'}")
    lines.append("-" * 130)
    for i, r in enumerate(records, 1):
        status = "[已归档]" if r.is_archived else "[活跃]"
        t = (r.title[:24] + "...") if len(r.title) > 24 else r.title
        ws = (r.workspace[:26] + "...") if len(r.workspace) > 26 else r.workspace
        lines.append(f"{i:<3} {r.session_id:<36} {status:<6} {r.agent_name:<8} {r.updated_at:<19} {t} ({ws})")
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="locate_session.py",
        description="按工作区目录、时间窗、标题与全文关键词定位 MiniMax Code 会话",
    )
    p.add_argument("--workspace", "--cwd", "-w", help="工作区路径关键字（模糊匹配）")
    p.add_argument("--time", "-t", help="自然语言时间提示，如 'yesterday', '上周', 'today', '2026-08-22'")
    p.add_argument("--after", help="时间窗起点 (ISO 格式)")
    p.add_argument("--before", help="时间窗终点 (ISO 格式)")
    p.add_argument("--title", help="按会话标题过滤（模糊匹配）")
    p.add_argument("--keyword", "-k", help="按对话日志全文关键词过滤")
    p.add_argument("--archived-only", action="store_true", help="仅检索已归档会话")
    p.add_argument("--active-only", action="store_true", help="仅检索活跃会话")
    p.add_argument("--minimax-home", help="自定义 MiniMax 主目录路径")
    p.add_argument("--limit", "-n", type=int, default=DEFAULT_LIMIT, help=f"返回上限，默认 {DEFAULT_LIMIT}")
    p.add_argument("--json", action="store_true", help="输出结构化 JSON 格式")
    return p


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    window = None
    try:
        if args.time:
            window = parse_time_hint(args.time)
        elif args.after or args.before:
            now = datetime.now().astimezone()
            after = (
                datetime.fromisoformat(args.after).replace(tzinfo=now.tzinfo)
                if args.after
                else now - timedelta(days=MAX_WINDOW_DAYS)
            )
            before = (
                datetime.fromisoformat(args.before).replace(tzinfo=now.tzinfo)
                if args.before
                else now
            )
            window = TimeWindow(
                after.astimezone(timezone.utc),
                before.astimezone(timezone.utc),
                f"{args.after or ''} ~ {args.before or ''}",
            )
    except ValueError as e:
        print(f"错误: 时间解析失败: {e}", file=sys.stderr)
        return 2

    if window and window.width_days() > MAX_WINDOW_DAYS:
        print(
            f"错误: 时间窗跨度 {window.width_days():.1f} 天超过 {MAX_WINDOW_DAYS} 天上限，请缩窄窗口",
            file=sys.stderr,
        )
        return 2

    arch_mode = "all"
    if args.archived_only:
        arch_mode = "archived_only"
    elif args.active_only:
        arch_mode = "active_only"

    try:
        base_dir = resolve_minimax_home(args.minimax_home)
        matches, distinct_ws = locate_minimax_sessions(
            base_dir=base_dir,
            workspace_kw=args.workspace,
            time_window=window,
            title_kw=args.title,
            keyword_kw=args.keyword,
            archived_mode=arch_mode,
            limit=args.limit,
        )
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2

    if args.json:
        result = {
            "minimax_home": str(base_dir),
            "query": {
                "workspace_keyword": args.workspace,
                "time_window": {
                    "start_utc": window.start_utc.strftime("%Y-%m-%dT%H:%M:%SZ") if window else None,
                    "end_utc": window.end_utc.strftime("%Y-%m-%dT%H:%M:%SZ") if window else None,
                    "parsed_from": window.parsed_from if window else None,
                },
                "archived_mode": arch_mode,
                "title_keyword": args.title,
                "keyword": args.keyword,
            },
            "matches": [m.to_dict() for m in matches],
            "match_count": len(matches),
        }
        if not matches and distinct_ws:
            result["hint_distinct_workspaces"] = [{"workspace": w, "count": c} for w, c in distinct_ws]
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"MINIMAX_HOME:    {base_dir}")
        if window:
            print(f"时间窗口(UTC):   {window.start_utc} ~ {window.end_utc} (来源: {window.parsed_from})")
        if args.workspace:
            print(f"工作区关键词:     {args.workspace}")
        print(f"归档过滤模式:     {arch_mode}")
        print()
        print(f"找到 {len(matches)} 个匹配会话:")
        print(render_table(matches))
        if not matches:
            print()
            print("数据库中已发现的工作区候选（前 20）:")
            for w, c in distinct_ws:
                print(f"  {c:>4} 次会话  {w}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
