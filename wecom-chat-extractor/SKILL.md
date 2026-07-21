---
name: wecom-chat-extractor
description: >-
  企业微信本地聊天数据提取与分析工具。从 Mac 企微 5.x 本地加密数据库中捕获密钥、解密、
  查询会话/联系人/消息、导出结构化 Markdown 和可视化 HTML 分析报告。当用户要解析企业微信
  聊天记录、企微群聊数据、WeCom local database、导出群聊记录、分析销售沟通群时使用。
  依赖 yichen-wecom-local-vault 提供核心解密能力。
---

# wecom-chat-extractor

企业微信 5.x 本地数据提取与分析工具。在 `yichen-wecom-local-vault` 基础上增加内存扫描密钥捕获、结构化 Markdown 导出和 HTML 可视化报告，通过统一 CLI `wecom_pro.py` 串联全流程。

## 前置条件

- macOS，企业微信 5.x 已安装并运行
- Python 3.10+，已安装 `pycryptodome` 和 `frida`（隔离 venv）
- `yichen-wecom-local-vault` skill 已部署

## 工作流

```
企业微信运行中
    │
    ① capture-key   捕获密钥（auto: hooks → 内存扫描 fallback）
    │
    ② decrypt       解密数据库 → 明文快照
    │
    ③ sessions      查找目标群聊
    │
    ④ analyze       一键生成 JSON + 结构化 MD + HTML 报告
```

首次使用依次执行 ①→②→③→④；已有密钥和快照时自动跳过，直接执行 ③→④。

## 入口

```bash
SKILL_DIR="${HOME}/.workbuddy/skills/wecom-chat-extractor"
python3 "$SKILL_DIR/scripts/wecom_pro.py" <command> [options]
```

不要自动安装依赖，先报告缺项。依赖：`pycryptodome`（解密）、`frida`（密钥捕获）。

## 命令

### capture-key — 捕获解密密钥

```bash
python3 wecom_pro.py capture-key \
  [--method auto|hooks|memory-scan] \
  [--hook-duration 60] [--scan-duration 300] \
  [--skip-hooks] [--data-dir DIR]
```

- `auto`（默认）：先 hooks 60s，失败则内存扫描 300s
- `hooks`：仅 hook CC_MD5/CCCrypt/sqlite3_key，需企微活跃解密
- `memory-scan`：扫描进程 RW 内存逐个验证，企微空闲时唯一可靠方式
- 密钥验证通过后保存到私密 Vault（0600），终端不显示

### decrypt — 解密数据库

```bash
python3 wecom_pro.py decrypt [--data-dir DIR]
```

读取密钥，解密所有数据库并合并 WAL，生成明文快照。不改源数据库。

### sessions / contacts / history / search — 查询

```bash
python3 wecom_pro.py sessions [--query Q] [--limit 50]
python3 wecom_pro.py contacts [--query Q] [--limit 100]
python3 wecom_pro.py history "群名" [--start DATE] [--end DATE] [--limit 200]
python3 wecom_pro.py search "关键词" [--chat "群名"] [--start DATE] [--limit 200]
```

### export — 导出聊天记录

```bash
python3 wecom_pro.py export "群名" \
  [--format json|markdown|structured|html] \
  [--limit 10000] [--output PATH]
```

| 格式 | 说明 |
|------|------|
| `json` | 原始 JSON |
| `markdown` | 基础 Markdown（vault_cli 原始格式） |
| `structured` | **默认**。解析引用消息为引用块、日期分组、消息类型标识、图片 hash 清理 |
| `html` | HTML 分析报告（Chart.js 可视化） |

### analyze — 一键分析

```bash
python3 wecom_pro.py analyze "群名" [--limit 10000] [--output-dir DIR]
```

自动生成三个文件：
- `<群名>_chat_records.json` — 原始数据
- `<群名>_chat_records_structured.md` — 结构化 Markdown
- `<群名>_analysis_report.html` — 可视化分析报告

### status — 检查数据库状态

```bash
python3 wecom_pro.py status [--data-dir DIR] [--show-paths]
```

只检查，不附加进程。

## 密钥捕获策略

| 方法 | 成功率 | 耗时 | 适用场景 |
|------|--------|------|----------|
| 标准 hooks | 中（需企微活跃解密） | 60s | 企微正在收发消息 |
| 内存扫描 | 高（直接读进程内存） | 1-5min | 企微空闲、hooks 超时 |

`auto` 模式先 hooks 后扫描，覆盖大多数场景。Apple Silicon 上重签副本 spawn 可能失败，内存扫描是最可靠的 fallback。

## 结构化导出

WeCom 引用回复原始存储格式：

```
"被引用者：被引用内容"
------
回复者
回复内容
```

结构化后：

```markdown
#### 2026-04-24 16:28:06 · 陈丽茵

> **杨攀：**
> 照相亭，1票2件，航空箱包装...
>
> *（被引用消息）*

SN318-加拿大-空运普货(含税)-卡派：头程￥58.5/KG...
```

同时处理：图片 hash → `[图片]`，截图文件名 → `[截图]`，系统消息 → 斜体，联系人名片 → 表格行，日期按天分组。

## 安全边界

继承 `yichen-wecom-local-vault` 的全部强制边界：

- 只读源数据库（`mode=ro`），不写回企微容器
- 不发送企业微信消息，不点击 UI，不重启客户端
- 密钥不显示在终端，文件权限 0600
- 明文快照和导出文件权限 0600，拒绝覆盖已有文件
- 不在回复或日志中显示 raw key、完整账号目录、联系人内部 ID
- 明文数据不放进项目、桌面、云盘或 Git

## 已知限制

- 只处理本机已同步的消息；换设备后历史可能不全
- 图片/语音/视频只输出类型占位，不解密媒体
- 内存扫描速度取决于企微进程 RW 内存大小（典型 1-5 分钟）
- 企微版本升级可能改变密钥调用或表结构；先运行 `status` 再处理真实数据

## 架构

```
wecom-chat-extractor/
├── SKILL.md                    # 本文档
├── scripts/
│   ├── wecom_pro.py            # 统一 CLI（capture-key/decrypt/sessions/export/analyze）
│   ├── key_memory_scan.py      # Frida 内存扫描（密钥捕获 fallback）
│   ├── structured_export.py    # 结构化 Markdown 导出
│   └── html_report.py          # HTML 分析报告生成
└── references/
    └── workflow.md             # 工作流详解（密钥策略、数据库结构、消息类型对照）
```

核心解密/查询委托给 `yichen-wecom-local-vault` 的 `vault_cli.py`，本 skill 在其基础上增加三项能力：内存扫描密钥捕获、结构化 Markdown 导出、HTML 可视化报告。

## 验证

```bash
cd "$SKILL_DIR/scripts"
python3 -m py_compile *.py
python3 wecom_pro.py --help
python3 wecom_pro.py status
```
