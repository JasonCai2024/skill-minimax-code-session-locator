---
name: skill-minimax-code-session-locator
description: 定位 MiniMax Code (Mavis / OpenCode 运行时) 本地会话。通过查询 runtime-state.sqlite 关系与 FTS5 索引并联动 v2/sessions 按日期分层目录，支持按工作区目录(workspace_dir)、时间窗、会话标题、全文关键词、可见性/归档状态过滤，并提取 messages.jsonl 交互轨迹与 snapshot 快照。当用户需要查找或回溯 MiniMax Code 对话历史时使用。触发话术包括 找MiniMax会话, 定位MiniMax历史, resume MiniMax Code session.
disable-model-invocation: true
user-invocable: true
argument-hint: [workspace-dir, time-hint]
---

# Skill MiniMax Code Session Locator

## Goal

根据用户提供的工作区路径（Workspace Dir）、大致更新时间、归档状态或对话关键词，定位 MiniMax Code 全局数据库（`runtime-state.sqlite`）中的匹配会话，并自动映射解析 `v2/sessions/` 物理目录中的 `messages.jsonl` 与 `snapshot.json` 快照，供上下文接力、报告复盘与历史回顾使用。

## Required Inputs

| 参数 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `workspace` | 路径字符串 | 否* | 会话工作区路径关键词（如 `ForAgent`、`社交媒体`），大小写不敏感模糊匹配 |
| `time_hint` | 时间字符串 | 否* | 自然语言时间提示（"昨天" / "yesterday" / "上周" / "3pm"）或 ISO 格式（"2026-08-22"） |
| `title` | 字符串 | 否 | 会话标题关键词过滤 |
| `keyword` | 字符串 | 否 | 在对话日志中全文检索的关键词 |
| `archived_mode` | 枚举 | 否 | `all`（默认，包含活跃与归档）、`archived_only`（仅归档）、`active_only`（仅未归档活跃） |
| `minimax_home` | 路径 | 否 | MiniMax 数据主目录，覆盖 `MINIMAX_HOME` 环境变量；默认 `~/.minimax/` |
| `limit` | 整数 | 否 | 候选返回数量上限，默认 `10` |

> \*注：`workspace`、`time_hint`、`title`、`keyword` 中至少提供一个；若均未提供，默认按最新更新时间列出最近 10 个会话。

## Workflow

### Step 1：定位 MINIMAX_HOME 与数据库
1. 读取 `--minimax-home` 参数或 `MINIMAX_HOME` 环境变量；若未设置使用 `Path.home() / ".minimax"`。
2. 校验 `v2/sqlite/runtime-state.sqlite` 存在性。

### Step 2：时间提示解析为毫秒窗口
1. 调用 `scripts/locate_session.py --time "<hint>"` 将自然语言解析为 UTC 起止时间。
2. 将时间转换为 Unix 毫秒时间戳（13 位数字），以适配 `runtime-state.sqlite` 中的 `updated_at_ms`。
3. 检查时间窗跨度不超过 30 天。

### Step 3：查询 local_runtime_sessions 索引表
1. 连接 SQLite 执行 `PRAGMA integrity_check` 校验。
2. 查询 `local_runtime_sessions` 表：
   - `WHERE workspace_dir LIKE ? AND updated_at_ms BETWEEN ? AND ?`
   - 结合 `--archived-only`（`archived = 1 OR visibility = 'archived'`）进行过滤。
   - `ORDER BY updated_at_ms DESC LIMIT <limit>`。

### Step 4：定位会话物理目录与 messages.jsonl
1. 依据 `session_id` 的 Base64 编码片段或 `v2/sessions/*/*/*/*/manifest.json` 快速映射物理目录。
2. 若指定了 `--keyword`，在对应会话的 `messages.jsonl` 中全文检索确认。

### Step 5：候选确认与读取
1. **1 个候选**：直接读取摘要。
2. **多个候选**：以结构化表格展示 Session ID、状态、Agent、更新时间、标题与工作区，供用户指定。
3. **0 个候选**：输出数据库已记录的高频工作区列表供纠偏。
4. 目标会话确定后，调用 `scripts/read_session.py` 输出交互轮次与快照信息。

## Decision Rules

1. **创建时间 vs 更新时间**：`v2/sessions/` 的目录结构（年/月/日/时分秒）代表**首次创建时间**；会话活跃度与排序必须依据 `updated_at_ms`（更新时间）。
2. **物理文件查找优先级**：先通过 Session ID 的 Base64 编码子串匹配目录名，未匹配时再通过扫描 `manifest.json` 兜底。
3. **多候选不擅自挑选**：匹配到多条记录时，向用户展示完整清单。

## Output Requirements

### 定位命令输出 (`scripts/locate_session.py --json`)
```json
{
  "minimax_home": "C:\\Users\\pc\\.minimax",
  "query": {
    "workspace_keyword": "ForAgent",
    "time_window": {
      "start_utc": "2026-09-04T00:00:00Z",
      "end_utc": "2026-09-05T23:59:59Z"
    },
    "archived_mode": "all"
  },
  "matches": [
    {
      "session_id": "mvs_2c410550b7b44bfd9b4f7bef2399bc26",
      "title": "解读 codex-session-locator 技能",
      "workspace": "E:/BaiduSyncdisk/WorkSpace/ForAgent",
      "agent_name": "mavis",
      "runtime": "pi-agent",
      "status": "idle",
      "is_archived": false,
      "updated_at": "2026-09-05 10:07:18",
      "session_dir": "C:\\Users\\pc\\.minimax\\v2\\sessions\\...",
      "messages_path": "C:\\Users\\pc\\.minimax\\v2\\sessions\\...\\messages.jsonl"
    }
  ],
  "match_count": 1
}
```

### 读取命令输出 (`scripts/read_session.py --summary`)
输出会话 ID、创建/更新时间、对话总轮次、各角色消息分布、工具调用统计及包含的快照与报告。

## Validation

1. **SQLite 完整性**：执行查询前验证 `PRAGMA integrity_check`。
2. **Base64 物理目录映射**：校验目录名与 `sessionId` 的一致性。
3. **时间窗跨度校验**：时间窗不得超过 30 天。
4. **消息格式容错**：解析多层级 `message.content` 时兼容纯文本与复杂 JSON 数组。

## Fallback

| 异常情况 | 降级处理策略 |
| :--- | :--- |
| `runtime-state.sqlite` 不存在或损坏 | 自动切换为文件系统扫描模式，遍历 `v2/sessions/**/manifest.json` |
| 时间窗内 0 匹配 | 列出该工作区下最近的 5 个会话供用户挑选 |
| 工作区路径无匹配 | 输出数据库中出现过的高频工作区列表供用户核对 |
| 无法解析自然语言时间 | 回退到最近 7 天时间窗并告警提示 |

## Examples

### 触发示例
- `帮我找昨天在 E:/BaiduSyncdisk/WorkSpace/ForAgent 启动的 MiniMax 会话`
- `查找 MiniMax Code 中包含关键词“codex-session-locator”的会话`
- `列出最近 5 个已归档的 MiniMax 会话`
- `查看会话 mvs_2c410550... 的对话摘要与快照状态`

### 执行命令示例
```powershell
# 1. 查找指定工作区的会话
python scripts/locate_session.py --workspace "ForAgent" --time "yesterday"

# 2. 仅查找已归档的会话并输出 JSON
python scripts/locate_session.py --archived-only --limit 5 --json

# 3. 读取会话摘要与快照详情
python scripts/read_session.py --session-id <session_id> --summary
python scripts/read_session.py --session-id <session_id> --snapshots
```

## Reference

- 存储介质与目录分层细节：`references/minimax-storage.md`
- 全局 SQLite 表结构与字段：`references/sqlite-schema.md`
