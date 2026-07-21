#!/usr/bin/env python3
"""wecom_pro — Unified WeCom local chat data extraction CLI.

Orchestrates the full pipeline: key capture → decrypt → query → structured export → analysis.
Wraps yichen-wecom-local-vault's vault_cli.py and adds memory-scan key capture,
structured markdown export, and HTML analysis report generation.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# --- Paths ---
SKILL_DIR = Path(__file__).resolve().parent
VAULT_SKILL_DIR = Path.home() / ".workbuddy" / "skills" / "yichen-wecom-local-vault"
VAULT_SCRIPTS = VAULT_SKILL_DIR / "scripts"
VAULT_CLI = VAULT_SCRIPTS / "vault_cli.py"

# Ensure vault scripts are importable
sys.path.insert(0, str(VAULT_SCRIPTS))
sys.path.insert(0, str(SKILL_DIR))


def _python() -> str:
    """Return the managed Python path."""
    managed = Path.home() / ".workbuddy" / "binaries" / "python" / "envs" / "default" / "bin" / "python3"
    return str(managed) if managed.exists() else sys.executable


def _run_vault(args: list[str]) -> int:
    """Run vault_cli.py with the given args, streaming output."""
    cmd = [_python(), str(VAULT_CLI)] + args
    env = {**os.environ, "PYTHONPATH": str(VAULT_SCRIPTS)}
    result = subprocess.run(cmd, env=env)
    return result.returncode


# ─── status ──────────────────────────────────────────────────────────────────

def cmd_status(args) -> int:
    """Check WeCom databases and encryption status."""
    vault_args = ["status"]
    if args.data_dir:
        vault_args += ["--data-dir", args.data_dir]
    if args.show_paths:
        vault_args += ["--show-paths"]
    return _run_vault(vault_args)


# ─── capture-key ─────────────────────────────────────────────────────────────

def cmd_capture_key(args) -> int:
    """Capture the WeCom database decryption key.

    Strategy:
      auto  (default): Try Frida hooks first; if no key in 60s, fallback to memory scan.
      hooks:           Standard Frida attach + hook CC_MD5/CCCrypt/sqlite3_key.
      memory-scan:     Frida attach + scan all RW memory for 16-byte key candidates.
    """
    if args.method == "hooks" or (args.method == "auto" and not args.skip_hooks):
        print("=== 阶段 1/2: 标准 Frida hooks 捕获 ===")
        hook_args = [
            _python(),
            str(VAULT_SCRIPTS / "capture_key_macos.py"),
            "capture", "--confirm-attach", "--duration", str(args.hook_duration),
        ]
        if args.data_dir:
            hook_args += ["--data-dir", args.data_dir]
        env = {**os.environ, "PYTHONPATH": str(VAULT_SCRIPTS)}
        result = subprocess.run(hook_args, env=env)
        if result.returncode == 0:
            print("✅ hooks 捕获成功")
            return 0
        print(f"⚠️  hooks 捕获未成功 (exit={result.returncode})")

    if args.method == "hooks":
        return 1

    print("\n=== 阶段 2/2: Frida 内存扫描 ===")
    scan_script = SKILL_DIR / "key_memory_scan.py"
    scan_args = [
        _python(), str(scan_script),
        "--duration", str(args.scan_duration),
    ]
    if args.data_dir:
        scan_args += ["--data-dir", args.data_dir]
    env = {**os.environ, "PYTHONPATH": str(VAULT_SCRIPTS)}
    result = subprocess.run(scan_args, env=env)
    return result.returncode


# ─── decrypt ─────────────────────────────────────────────────────────────────

def cmd_decrypt(args) -> int:
    """Decrypt all databases into a plaintext snapshot."""
    vault_args = ["decrypt"]
    if args.data_dir:
        vault_args += ["--data-dir", args.data_dir]
    return _run_vault(vault_args)


# ─── sessions / contacts / history / search ──────────────────────────────────

def cmd_sessions(args) -> int:
    vault_args = ["sessions"]
    if args.query:
        vault_args += ["--query", args.query]
    vault_args += ["--limit", str(args.limit)]
    return _run_vault(vault_args)


def cmd_contacts(args) -> int:
    vault_args = ["contacts"]
    if args.query:
        vault_args += ["--query", args.query]
    vault_args += ["--limit", str(args.limit)]
    return _run_vault(vault_args)


def cmd_history(args) -> int:
    vault_args = ["history", args.chat, "--limit", str(args.limit)]
    if args.start:
        vault_args += ["--start", args.start]
    if args.end:
        vault_args += ["--end", args.end]
    return _run_vault(vault_args)


def cmd_search(args) -> int:
    vault_args = ["search", args.keyword, "--limit", str(args.limit)]
    if args.chat:
        vault_args += ["--chat", args.chat]
    if args.start:
        vault_args += ["--start", args.start]
    return _run_vault(vault_args)


# ─── export ──────────────────────────────────────────────────────────────────

def cmd_export(args) -> int:
    """Export chat records in the specified format.

    Formats:
      json:       Raw JSON (via vault_cli)
      markdown:   Basic markdown (via vault_cli)
      structured: Structured markdown with parsed replies, date grouping (default)
      html:       HTML analysis report with Chart.js visualizations
    """
    if args.format in ("json", "markdown"):
        vault_args = ["export", args.chat, "--format", args.format, "--limit", str(args.limit)]
        if args.output:
            vault_args += ["--output", args.output]
        return _run_vault(vault_args)

    # For structured and html, first export JSON, then transform
    import tempfile
    tmp_json = tempfile.mktemp(suffix=".json")
    vault_args = ["export", args.chat, "--format", "json", "--limit", str(args.limit), "--output", tmp_json]
    rc = _run_vault(vault_args)
    if rc != 0:
        os.unlink(tmp_json)
        return rc

    if args.format == "structured":
        from structured_export import export_structured_md
        output_path = args.output or args.chat.replace(" ", "_") + "_structured.md"
        export_structured_md(tmp_json, output_path)
        print(f"\n✅ 结构化 Markdown 已导出: {output_path}")
    elif args.format == "html":
        from html_report import generate_html_report
        output_path = args.output or args.chat.replace(" ", "_") + "_report.html"
        generate_html_report(tmp_json, output_path)
        print(f"\n✅ HTML 分析报告已生成: {output_path}")

    os.unlink(tmp_json)
    return 0


# ─── analyze ─────────────────────────────────────────────────────────────────

def cmd_analyze(args) -> int:
    """Full analysis pipeline: export JSON + structured MD + HTML report.

    Produces three files:
      <chat>_chat_records.json       — raw data
      <chat>_chat_records_structured.md — structured markdown
      <chat>_analysis_report.html    — visual analysis report
    """
    chat_slug = args.chat.replace(" ", "_").replace("/", "_")
    output_dir = Path(args.output_dir) if args.output_dir else Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / f"{chat_slug}_chat_records.json"
    md_path = output_dir / f"{chat_slug}_chat_records_structured.md"
    html_path = output_dir / f"{chat_slug}_analysis_report.html"

    # Step 1: Export JSON
    print(f"=== 1/3 导出 JSON 原始数据 ===")
    vault_args = ["export", args.chat, "--format", "json", "--limit", str(args.limit), "--output", str(json_path)]
    rc = _run_vault(vault_args)
    if rc != 0:
        print(f"❌ JSON 导出失败 (exit={rc})")
        return rc
    print(f"✅ {json_path}")

    # Step 2: Structured markdown
    print(f"\n=== 2/3 生成结构化 Markdown ===")
    from structured_export import export_structured_md
    export_structured_md(str(json_path), str(md_path))
    print(f"✅ {md_path}")

    # Step 3: HTML report
    print(f"\n=== 3/3 生成 HTML 分析报告 ===")
    from html_report import generate_html_report
    generate_html_report(str(json_path), str(html_path))
    print(f"✅ {html_path}")

    print(f"\n🎉 全部完成！三个文件已生成在: {output_dir}")
    return 0


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="wecom_pro",
        description="企业微信本地聊天数据提取与分析工具 (Unified WeCom Local Vault Pro)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # status
    p = sub.add_parser("status", help="检查数据库状态和加密格式")
    p.add_argument("--data-dir")
    p.add_argument("--show-paths", action="store_true")
    p.set_defaults(func=cmd_status)

    # capture-key
    p = sub.add_parser("capture-key", help="捕获数据库解密密钥")
    p.add_argument("--data-dir")
    p.add_argument("--method", choices=["auto", "hooks", "memory-scan"], default="auto",
                   help="auto=先hooks后扫描(默认), hooks=仅hooks, memory-scan=仅内存扫描")
    p.add_argument("--hook-duration", type=int, default=60, help="hooks 捕获时长(秒)")
    p.add_argument("--scan-duration", type=int, default=300, help="内存扫描时长(秒)")
    p.add_argument("--skip-hooks", action="store_true", help="跳过 hooks 直接内存扫描")
    p.set_defaults(func=cmd_capture_key)

    # decrypt
    p = sub.add_parser("decrypt", help="解密所有数据库到明文快照")
    p.add_argument("--data-dir")
    p.set_defaults(func=cmd_decrypt)

    # sessions
    p = sub.add_parser("sessions", help="列出会话")
    p.add_argument("--query")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_sessions)

    # contacts
    p = sub.add_parser("contacts", help="列出联系人")
    p.add_argument("--query")
    p.add_argument("--limit", type=int, default=100)
    p.set_defaults(func=cmd_contacts)

    # history
    p = sub.add_parser("history", help="查询指定会话历史")
    p.add_argument("chat")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--limit", type=int, default=200)
    p.set_defaults(func=cmd_history)

    # search
    p = sub.add_parser("search", help="全文搜索已解密消息")
    p.add_argument("keyword")
    p.add_argument("--chat")
    p.add_argument("--start")
    p.add_argument("--limit", type=int, default=200)
    p.set_defaults(func=cmd_search)

    # export
    p = sub.add_parser("export", help="导出聊天记录")
    p.add_argument("chat")
    p.add_argument("--format", choices=["json", "markdown", "structured", "html"], default="structured",
                   help="json/markdown/structured(默认)/html")
    p.add_argument("--limit", type=int, default=10000)
    p.add_argument("--output")
    p.set_defaults(func=cmd_export)

    # analyze
    p = sub.add_parser("analyze", help="一键分析: JSON + 结构化MD + HTML报告")
    p.add_argument("chat")
    p.add_argument("--limit", type=int, default=10000)
    p.add_argument("--output-dir", help="输出目录(默认当前目录)")
    p.set_defaults(func=cmd_analyze)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
