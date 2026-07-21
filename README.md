# wecom-skills

企业微信本地聊天数据提取与分析工具集，包含两个互补的 Skill。支持 [WorkBuddy](https://www.codebuddy.cn/)、[Codex](https://openai.com/index/introducing-codex/)、[Claude Code](https://claude.ai/code) 等支持 Skill 机制的 AI Agent 安装使用。

## Skill 列表

| Skill | 说明 | 来源 |
|-------|------|------|
| **wecom-chat-extractor** | 增强工具：统一 CLI、内存扫描密钥捕获、结构化 Markdown 导出、HTML 可视化报告 | 原创 |
| **yichen-wecom-local-vault** | 基础引擎：数据库发现、解密、查询、导出 | ⚠️ 外部开源，源自 [mcncarl/yichen-skills](https://github.com/mcncarl/yichen-skills) |

> **`yichen-wecom-local-vault` 是外部开源 Skill**，由 [mcncarl](https://github.com/mcncarl) 开发，遵循其原始 LICENSE。本仓库仅做打包分发，不修改其核心逻辑。`wecom-chat-extractor` 依赖它提供的基础解密/查询能力。

## 架构关系

```
用户
 │
 ▼
wecom-chat-extractor (增强层)
 │  ├── wecom_pro.py         统一 CLI 入口
 │  ├── key_memory_scan.py   Frida 内存扫描（密钥捕获 fallback）
 │  ├── structured_export.py 结构化 Markdown 导出
 │  └── html_report.py       HTML 分析报告
 │
 ▼ 调用
 │
yichen-wecom-local-vault (基础层)
    ├── vault_cli.py         解密/查询/导出
    ├── capture_key_macos.py 标准 Frida hooks 密钥捕获
    ├── wecom_crypto.py      wxSQLite3 AES-128 解密
    └── wecom_common.py      数据库发现/密钥管理
```

## 安装

### 前置条件

- macOS（Apple Silicon 或 Intel）
- 企业微信 5.x 已安装
- Python 3.10+

### 安装到不同 Agent

本 Skill 遵循通用的 Skill 目录结构（`SKILL.md` + `scripts/` + `references/`），可安装到任何支持该机制的 AI Agent：

#### WorkBuddy

```bash
git clone https://github.com/Young1108/wecom-skills.git /tmp/wecom-skills
mkdir -p ~/.workbuddy/skills
cp -r /tmp/wecom-skills/wecom-chat-extractor ~/.workbuddy/skills/
cp -r /tmp/wecom-skills/yichen-wecom-local-vault ~/.workbuddy/skills/
```

#### Codex (OpenAI)

```bash
git clone https://github.com/Young1108/wecom-skills.git /tmp/wecom-skills
mkdir -p ~/.codex/skills
cp -r /tmp/wecom-skills/wecom-chat-extractor ~/.codex/skills/
cp -r /tmp/wecom-skills/yichen-wecom-local-vault ~/.codex/skills/
```

#### Claude Code

```bash
git clone https://github.com/Young1108/wecom-skills.git /tmp/wecom-skills
mkdir -p ~/.claude/skills
cp -r /tmp/wecom-skills/wecom-chat-extractor ~/.claude/skills/
cp -r /tmp/wecom-skills/yichen-wecom-local-vault ~/.claude/skills/
```

#### 其他 Agent

将两个 skill 目录复制到你的 Agent 对应的 skills 目录即可。Skill 通过 `SKILL.md` 中的 `name` 和 `description` 字段被 Agent 识别和加载。

### 安装 Python 依赖

```bash
pip install pycryptodome frida
```

> 建议在隔离 venv 中安装，避免污染系统 Python 环境。

### 验证安装

```bash
SKILL_DIR=<你的 skills 目录>/wecom-chat-extractor
python3 "$SKILL_DIR/scripts/wecom_pro.py" --help
python3 "$SKILL_DIR/scripts/wecom_pro.py" status
```

## 使用

### 在 AI Agent 中使用

安装到 skills 目录后，在对话中直接说：

> 用 wecom-chat-extractor 解析 XXX 群的聊天记录

Agent 会自动识别 Skill、加载工作流、执行全流程。

### 命令行直接使用

也可以脱离 Agent，直接用命令行：

```bash
# 设置路径（替换为你的 skills 目录）
SKILL_DIR=~/.workbuddy/skills/wecom-chat-extractor
# 或 Codex:  SKILL_DIR=~/.codex/skills/wecom-chat-extractor
# 或 Claude: SKILL_DIR=~/.claude/skills/wecom-chat-extractor

# 首次使用：捕获密钥 → 解密 → 分析
python3 "$SKILL_DIR/scripts/wecom_pro.py" capture-key
python3 "$SKILL_DIR/scripts/wecom_pro.py" decrypt
python3 "$SKILL_DIR/scripts/wecom_pro.py" analyze "群聊名称" --output-dir ~/output
```

后续使用（已有密钥和快照）只需最后一步：

```bash
python3 "$SKILL_DIR/scripts/wecom_pro.py" analyze "群聊名称" --output-dir ~/output
```

### 所有命令

| 命令 | 说明 |
|------|------|
| `status` | 检查数据库状态 |
| `capture-key` | 捕获解密密钥（auto/hooks/memory-scan） |
| `decrypt` | 解密数据库到明文快照 |
| `sessions` | 列出/搜索会话 |
| `contacts` | 列出/搜索联系人 |
| `history` | 查询指定会话历史 |
| `search` | 全文搜索消息 |
| `export` | 导出（json/markdown/structured/html） |
| `analyze` | 一键分析（JSON + 结构化 MD + HTML 报告） |

详细文档见 [wecom-chat-extractor/SKILL.md](wecom-chat-extractor/SKILL.md)。

## 输出示例

`analyze` 命令生成三个文件：

| 文件 | 说明 |
|------|------|
| `<群名>_chat_records.json` | 原始 JSON 数据 |
| `<群名>_chat_records_structured.md` | 结构化 Markdown（解析引用消息、日期分组） |
| `<群名>_analysis_report.html` | HTML 可视化报告（Chart.js 图表） |

HTML 报告包含：消息趋势、活跃度分析、参与者排行、目的国家、物流方式、货物类型、价格关键词等维度。

## 安全说明

- 只读操作，不修改企业微信数据库
- 不发送消息、不点击 UI、不重启客户端
- 密钥不显示在终端，文件权限 0600
- 明文数据不放进项目/桌面/云盘/Git
- 详见各 Skill 的 SKILL.md 安全边界章节

## 致谢

- [mcncarl/yichen-skills](https://github.com/mcncarl/yichen-skills) — `yichen-wecom-local-vault` 的原始作者
