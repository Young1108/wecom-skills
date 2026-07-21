# 工作流详解

## 完整流程

```
企业微信.app (运行中)
    │
    ▼
┌─────────────────────────────────────────┐
│  1. status    检查数据库状态              │
│     ↓ 发现加密的 message.db / session.db │
├─────────────────────────────────────────┤
│  2. capture-key  捕获解密密钥             │
│     ├─ 阶段 A: Frida hooks (60s)        │
│     │  hook CC_MD5 / CCCrypt / sqlite3_key │
│     │  企微活跃解密时 → 捕获到 key        │
│     │                                    │
│     └─ 阶段 B: 内存扫描 (300s)  [fallback]│
│        枚举 RW 内存区域                   │
│        每个候选 → CC_MD5 → CCCrypt → 验证 │
│        找到通过验证的 16 字节 key          │
├─────────────────────────────────────────┤
│  3. decrypt   解密数据库 → 明文快照       │
│     读取 key 文件 (0600)                  │
│     解密 message.db / session.db / user.db│
│     合并 WAL → ~/Library/.../snapshots/  │
├─────────────────────────────────────────┤
│  4. sessions  查找目标群聊                │
│     按名称搜索 conversation_table         │
├─────────────────────────────────────────┤
│  5. analyze   一键分析                    │
│     ├─ JSON 原始数据                      │
│     ├─ 结构化 Markdown (解析引用/日期分组) │
│     └─ HTML 报告 (Chart.js 可视化)        │
└─────────────────────────────────────────┘
```

## 密钥捕获方法对比

### 标准 Frida Hooks
- **原理**：hook CommonCrypto 函数 (CC_MD5, CCCrypt, CCCryptorCreate)，捕获传入的密钥参数
- **触发条件**：企业微信必须在此期间解密数据库页（收发消息、同步数据）
- **成功率**：中等 — 企微空闲时 60s 内可能不触发任何解密
- **耗时**：60 秒

### Frida 内存扫描
- **原理**：枚举进程所有 RW 内存区域，逐个尝试 16 字节候选值作为密钥
- **验证方式**：在进程内调用 CC_MD5 派生页密钥 → CCCrypt 解密第一页 → 检查 SQLite header
- **成功率**：高 — 只要密钥在内存中就能找到（密钥必然在内存中，否则企微无法访问数据）
- **耗时**：1-5 分钟（取决于 RW 内存大小，典型 60-170MB）
- **限制**：需要 Frida 能 attach 到进程（SIP 启用时可能需要特殊处理）

### 重签副本捕获
- **原理**：复制企微 app，ad-hoc 重签，Frida spawn 启动副本
- **触发条件**：副本启动时必然读取数据库
- **成功率**：高（但 Apple Silicon 上 Frida spawn 可能被断点拒绝）
- **耗时**：240 秒
- **限制**：需要手动登录副本；原企微需退出（单实例机制）

## WeCom 数据库结构

| 数据库 | 主要表 | 关键字段 |
|--------|--------|----------|
| message.db | message_table, message_small_table | message_id, sender_id, conversation_id, content_type, send_time, content |
| session.db | conversation_table, conversation_user_table | id (R:群聊/S:单聊), name, nick_name |
| user.db | user_table, external_user_relation_v3 | id, name, real_name, account, remarks |

### 消息类型对照

| content_type | 含义 | 导出处理 |
|-------------|------|----------|
| 0 | 文本/混合 | 清理 + 输出 |
| 2 | 纯文本 | 清理 + 输出 |
| 4 | 图片 | [图片] 占位 |
| 14 | 文件/图片 | hash 文件名 → [图片] |
| 123 | 图文混合 | 清理文本 + [图片] |
| 1002 | 联系人名片 | 表格行 |
| 1011 | 会议通知 | 斜体系统消息 |
| 1052 | 置顶 | 斜体系统消息 |
| 1055 | 取消置顶 | 斜体系统消息 |

### 引用消息格式

WeCom 存储引用回复时，把被引用内容和回复拼接为一个字符串：

```
"被引用者名字：被引用内容"
------
回复者名字
回复内容
```

结构化导出脚本用正则解析这个格式：
- `"被引用者：内容"` → markdown 引用块 `> **被引用者：** 内容`
- `------` 后的内容 → 正文

## 安全边界

- 只读源数据库（`mode=ro`），不写回企微容器
- 不发送消息、不点击 UI、不重启客户端
- 密钥文件权限 0600，终端不显示密钥
- 明文快照标记 `contains_plaintext_wecom_data: true`
- 导出文件权限 0600，拒绝覆盖已有文件
- 不在日志中显示 raw key、完整账号目录、联系人内部 ID
