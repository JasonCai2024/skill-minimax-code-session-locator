# 安装与手动调用说明

本文档说明 `skill-minimax-code-session-locator` 的本地安装、配置与无需 AI 助理时的独立 CLI 调用方式。

---

## 一、安装位置

### Claude Code

#### 1. 项目级（仅当前项目可见）
```text
.claude/skills/skill-minimax-code-session-locator/
```

#### 2. 全局（所有项目可用）
```text
~/.claude/skills/skill-minimax-code-session-locator/
```

### OpenCode

```text
.opencode/skills/skill-minimax-code-session-locator/
# 或全局
~/.config/opencode/skills/skill-minimax-code-session-locator/
```

---

## 二、验证发现

1. 启动或重启 Claude Code。
2. 在对话框输入 `/`，确认出现 `skill-minimax-code-session-locator`。
3. 若未出现，检查：
   - 技能目录名与 `SKILL.md` 中的 `name` 严格一致；
   - frontmatter 格式无 YAML 语法错误。

---

## 三、直接命令行调用（无需 Agent）

### 1. 定位会话
```powershell
# 按工作区路径模糊匹配与自然语言时间定位
python scripts/locate_session.py --workspace "ForAgent" --time "yesterday"

# 仅查找已归档会话
python scripts/locate_session.py --archived-only --limit 5

# 输出机器可读 JSON
python scripts/locate_session.py --workspace "社交媒体" --json
```

### 2. 读取会话与快照
```powershell
# 查看会话基本摘要与轮次列表
python scripts/read_session.py --session-id <session_id> --summary

# 查看会话快照信息 (snapshot.json)
python scripts/read_session.py --session-id <session_id> --snapshots

# 查看指定轮次的详细交互内容与思考过程
python scripts/read_session.py --session-id <session_id> --turn 1
```

---

## 四、Python 环境要求

- Python 3.8+
- 仅使用 Python 标准库（`sqlite3`、`json`、`re`、`base64`、`datetime`、`pathlib`），无需通过 `pip` 安装任何依赖。
