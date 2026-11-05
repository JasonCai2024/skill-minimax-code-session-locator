# MiniMax Code SQLite Schema 参考

本文档记录 `~/.minimax/v2/sqlite/runtime-state.sqlite` 核心关系表与全文检索表结构。

## 1. 核心表清单

| 表名 | 作用 |
| :--- | :--- |
| `local_runtime_sessions` | **核心会话主表**：会话元数据（ID、标题、工作区、状态、归档标志） |
| `local_runtime_sessions_fts` | **SQLite FTS5 全文检索引擎**：毫秒级多字段关键词搜索 |
| `local_runtime_projects` | 项目工作区与会话映射表 |
| `local_runtime_token_usage` | 每次交互的 Token 消耗统计 |
| `local_runtime_turn_diffs` | 代码变更审计与 Diff 记录 |

---

## 2. `local_runtime_sessions` 表结构

```sql
CREATE TABLE local_runtime_sessions (
  session_id TEXT PRIMARY KEY,       -- 会话 ID (如 mvs_2c410550...)
  record_json TEXT,                  -- 完整元数据 JSON
  updated_at_ms INTEGER,             -- 最近更新时间戳 (Unix 毫秒)
  agent_name TEXT,                   -- 所属 Agent 名称 (如 mavis)
  runtime TEXT,                      -- 运行时框架 (如 pi-agent)
  status TEXT,                       -- 状态 (如 idle / finished)
  archived INTEGER,                  -- 是否归档 (0: 活跃, 1: 归档)
  visibility TEXT,                   -- 可见性 (visible / archived)
  workspace_dir TEXT,                -- 绑定的项目工作区绝对路径
  title TEXT,                        -- 会话标题
  created_at_ms INTEGER              -- 创建时间戳 (Unix 毫秒)
);
```

### 关键过滤字段
- `workspace_dir`: `WHERE workspace_dir LIKE '%<keyword>%'`
- `updated_at_ms`: `WHERE updated_at_ms >= ? AND updated_at_ms <= ?`
- `archived`: `WHERE archived = 1` 或 `WHERE archived = 0`
- `title`: `WHERE title LIKE ?`

---

## 3. `messages.jsonl` 结构

```json
{
  "message_id": "msg_01",
  "turn_id": 1,
  "message": {
    "role": "user",
    "content": "帮我优化这段代码...",
    "thinking": null
  }
}
```
- `role`: `user` / `assistant` / `toolResult`
- `thinking`: 思考推理流
- `tool_calls`: 工具调用序列
