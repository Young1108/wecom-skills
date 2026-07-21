#!/usr/bin/env python3
"""Structured markdown export module — parses WeCom reply messages into blockquotes,
adds date grouping, message type labels, and image-hash cleanup.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

# Reply message pattern: "quoted_sender: quoted_content"\n------\nreply_sender\nreply_content
REPLY_PATTERN = re.compile(
    r'^["\u201c]([^：:]+)[：:]\s*(.*?)["\u201d]\s*\n------\s*\n([^\n]*)\n?(.*)',
    re.DOTALL,
)

IMG_PATTERN = re.compile(r'[0-9a-f]{32}\.(?:jpg|jpeg|png|gif|bmp|webp)', re.IGNORECASE)
SCREENSHOT_PATTERN = re.compile(r'企业微信截图_\d+\.png')

TYPE_LABELS = {
    0: ("📝", "混合"),
    2: ("💬", "文本"),
    4: ("🖼️", "图片"),
    7: ("🎙️", "语音"),
    14: ("📎", "文件"),
    15: ("📎", "图片/文件"),
    23: ("📋", "名片"),
    29: ("📊", "卡片"),
    38: ("🔧", "应用"),
    40: ("📞", "通话"),
    123: ("📝", "图文"),
    503: ("📌", "状态"),
    570: ("🔗", "链接"),
    1002: ("👤", "联系人"),
    1011: ("📅", "会议"),
    1052: ("📌", "置顶"),
    1055: ("📌", "取消置顶"),
}


def clean_content(text: str) -> str:
    text = IMG_PATTERN.sub("[图片]", text)
    text = SCREENSHOT_PATTERN.sub("[截图]", text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def parse_reply(content: str) -> dict | None:
    m = REPLY_PATTERN.match(content)
    if not m:
        return None
    quoted_sender = m.group(1).strip()
    quoted_text = clean_content(m.group(2).strip())
    reply_sender = m.group(3).strip()
    reply_text = clean_content(m.group(4).strip())
    if not quoted_text and not reply_text:
        return None
    return {
        "quoted_sender": quoted_sender,
        "quoted_text": quoted_text,
        "reply_sender": reply_sender,
        "reply_text": reply_text,
    }


def format_message(msg: dict) -> str:
    time_str = msg["time"]
    sender = msg["sender"]
    content_type = msg["content_type"]
    raw_content = msg["content"]
    emoji, type_label = TYPE_LABELS.get(content_type, ("❓", msg.get("type_name", "未知")))

    if content_type in (1011, 1052, 1055):
        return f"> *{time_str} · {sender} {raw_content}*"

    if content_type == 1002:
        return f"| {time_str} | {sender} | {emoji} 分享了联系人 |"

    if "[二进制内容" in raw_content:
        size_match = re.search(r'\[二进制内容 (\d+) 字节\]', raw_content)
        size_info = f"({size_match.group(1)}字节)" if size_match else ""
        return f"| {time_str} | {sender} | {emoji} {type_label} {size_info} |"

    content = clean_content(raw_content)
    reply = parse_reply(raw_content)

    if reply:
        lines = [f"#### {time_str} · {sender}", ""]
        if reply["quoted_text"]:
            lines.append(f"> **{reply['quoted_sender']}：**")
            for ql in reply["quoted_text"].split("\n"):
                lines.append(f"> {ql}")
            lines.append(">")
            lines.append("> *（被引用消息）*")
            lines.append("")
        if reply["reply_text"]:
            for rl in reply["reply_text"].split("\n"):
                lines.append(rl)
        else:
            lines.append("*（仅引用，无回复内容）*")
        lines.append("")
        return "\n".join(lines)

    lines = [f"#### {time_str} · {sender} `{type_label}`", ""]
    for cl in content.split("\n"):
        lines.append(cl)
    lines.append("")
    return "\n".join(lines)


def export_structured_md(input_json: str, output_md: str) -> None:
    """Convert a vault_cli JSON export into a structured Markdown file."""
    with Path(input_json).open(encoding="utf-8") as f:
        data = json.load(f)

    session = data["session"]
    messages = data["messages"]

    output = [
        f"# {session['display_name']}",
        "",
        f"> 群聊记录结构化导出 · 共 {len(messages):,} 条消息",
        f"> conversation_id: `{session['conversation_id']}`",
        "",
    ]

    current_date = None
    for msg in messages:
        msg_date = msg["time"][:10] if msg["time"] else "未知日期"
        if msg_date != current_date:
            current_date = msg_date
            day_msgs = [m for m in messages if m["time"] and m["time"][:10] == msg_date]
            try:
                dt = datetime.strptime(msg_date, "%Y-%m-%d")
                weekday = "周" + "一二三四五六日"[dt.weekday()]
            except (ValueError, TypeError):
                weekday = ""
            output.append(f"\n---\n")
            output.append(f"## 📅 {msg_date} {weekday}（{len(day_msgs)} 条）\n")
        output.append(format_message(msg))

    md_text = "\n".join(output)
    Path(output_md).write_text(md_text, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 structured_export.py <input.json> <output.md>")
        sys.exit(1)
    export_structured_md(sys.argv[1], sys.argv[2])
    print(f"Done: {sys.argv[2]}")
