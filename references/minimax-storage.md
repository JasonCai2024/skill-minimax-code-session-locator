# MiniMax Code 会话存储结构参考

本文档汇总 MiniMax Code（由 Mavis / OpenCode 运行时驱动）的本地会话存储架构、目录组织规范与文件命名约定，作为 `skill-minimax-code-session-locator` 的底层参考。

## 1. 存储总览

MiniMax Code 采用 **“基于文件系统的按日期分层存储（JSON/JSONL）+ 全局 SQLite 关系与全文检索引擎（FTS5）+ 跨会话长期记忆”** 的混合架构。

主目录解析优先级：
1. 命令行 `--minimax-home` 参数
2. 环境变量 `MINIMAX_HOME`
3. 默认路径：`~/.minimax/`（Windows 下为 `C:\Users\<用户名>\.minimax\`）

---

## 2. 目录树说明

```text
C:\Users\<用户名>\.minimax\
├── v2\                                 # v2 核心运行时数据
│   ├── sessions\                       # 【核心】按日期分层归档的所有会话详情
│   │   └── {YYYY}\{MM}\{DD}\
│   │       └── {HH-MM-SS-mmm-session_<Base64编码ID>}\
│   │           ├── manifest.json       # 会话清单（时间戳、物理路径映射）
│   │           ├── messages.jsonl      # 完整交互日志（User/Assistant/Tool/Thinking）
│   │           ├── display.jsonl       # UI 渲染轻量流
│   │           ├── ledger.jsonl        # 事件溯源账本流水
│   │           ├── snapshot.json       # 会话最新状态快照
│   │           └── reports\            # 成果物报告与 Diff 归档
│   ├── sqlite\
│   │   ├── runtime-state.sqlite        # 【核心】全局运行时数据库（会话索引、FTS5检索等）
│   │   └── backups\                    # 数据库版本迁移自动备份
│   ├── logs\                           # 运行时滚动日志
│   └── observability\                  # 性能监控统计
├── memory\                             # 跨会话持久化记忆（user.md）
├── context-snapshots\                  # 上下文窗口裁剪快照
└── config.yaml                         # 核心配置与模型定义
```

---

## 3. 会话路径与时间归档特性

1. **路径命名规则**：
   - 格式：`v2\sessions\{YYYY}\{MM}\{DD}\{HH-MM-SS-mmm-session_<Base64编码ID>}\`
   - 目录时间代表会话的**首次创建时间**（Creation Time）。
2. **就地追加不迁移**：
   - 历史会话后续继续对话时，依然追加在初始创建目录下的 `messages.jsonl` 中，物理路径不变。
   - 更新时间 `updated_at_ms` 在全局数据库 `runtime-state.sqlite` 和 `manifest.json` 中持续刷新。
