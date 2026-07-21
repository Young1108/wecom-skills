#!/usr/bin/env python3
"""Scan WeCom process memory for the database raw key via Frida."""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
import time
import queue
from pathlib import Path

SKILL_DIR = Path(os.path.expanduser("~/.workbuddy/skills/yichen-wecom-local-vault"))
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from wecom_common import (  # noqa: E402
    choose_dataset,
    dataset_id,
    iter_databases,
    save_validated_key,
    validate_candidate,
)
from wecom_crypto import PAGE_SIZE, database_format  # noqa: E402


def _lcg_step(value: int) -> int:
    quotient = value // 52774
    value = 40692 * (value - 52774 * quotient) - 3791 * quotient
    return value if value >= 0 else value + 2147483399


def page_iv_bytes(page_number: int) -> bytes:
    value = page_number + 1
    output = bytearray()
    for _ in range(4):
        value = _lcg_step(value)
        output.extend(struct.pack("<I", value & 0xFFFFFFFF))
    return hashlib.md5(output).digest()


SCAN_AGENT = r"""
'use strict';

const PAGE_SALT = [0x01, 0x00, 0x00, 0x00, 0x73, 0x41, 0x6c, 0x54];

const ccMD5Addr = Module.findGlobalExportByName('CC_MD5');
const ccCryptAddr = Module.findGlobalExportByName('CCCrypt');
const ccMD5 = new NativeFunction(ccMD5Addr, 'pointer', ['pointer', 'uint32', 'pointer']);
const ccCrypt = new NativeFunction(ccCryptAddr, 'int32',
    ['int32','int32','int32','pointer','uint32','pointer','pointer','uint32','pointer','uint32','pointer']);

const seen = new Set();
let stats = {regions: 0, bytes: 0, candidates: 0, validated: 0, done: false, found: false};

function md5(ptr_in, len) {
    const out = Memory.alloc(16);
    ccMD5(ptr_in, len, out);
    return out;
}

function tryKey(keyAddr, encPage, encLen, headerFrag, ivAddr) {
    try {
        const material = Memory.alloc(24);
        Memory.copy(material, keyAddr, 16);
        material.add(16).writeByteArray(PAGE_SALT);
        const pageKey = md5(material, 24);

        const outBuf = Memory.alloc(encLen);
        const outMoved = Memory.alloc(8);
        const rc = ccCrypt(
            1, 0, 0,
            pageKey, 16,
            ivAddr,
            encPage, encLen,
            outBuf, encLen, outMoved
        );
        if (rc !== 0) return false;
        const plain = outBuf.readByteArray(8);
        const plainBytes = new Uint8Array(plain);
        for (let i = 0; i < 8; i++) {
            if (plainBytes[i] !== headerFrag[i]) return false;
        }
        return true;
    } catch (e) {
        return false;
    }
}

function scanRegion(base, size, encPage, encLen, headerFrag, ivAddr) {
    if (size > 64 * 1024 * 1024) return false;
    const step = 8;
    let lastReport = 0;
    for (let offset = 0; offset + 16 <= size; offset += step) {
        stats.bytes += step;
        try {
            const keyAddr = base.add(offset);
            const keyHex = Array.from(new Uint8Array(keyAddr.readByteArray(16)))
                .map(b => ('0'+b.toString(16)).slice(-2)).join('');
            if (seen.has(keyHex)) continue;
            seen.add(keyHex);
            stats.candidates++;
            if (tryKey(keyAddr, encPage, encLen, headerFrag, ivAddr)) {
                stats.validated++;
                stats.found = true;
                send({type: 'key', key: keyHex});
                return true;
            }
        } catch (_) {}
        if (stats.bytes - lastReport > 4 * 1024 * 1024) {
            lastReport = stats.bytes;
            send({type: 'progress', bytes: stats.bytes, candidates: stats.candidates});
        }
    }
    return false;
}

recv('page1', function(value) {
    const page1 = new Uint8Array(value.page1);
    const encLen = value.encLen;
    const headerFrag = new Uint8Array(value.headerFragment);
    const iv = new Uint8Array(value.iv);

    const encData = new Uint8Array(encLen);
    encData.set(page1.subarray(8, 16), 0);
    encData.set(page1.subarray(24), 8);
    const encPage = Memory.alloc(encLen);
    encPage.writeByteArray(encData);
    const ivAddr = Memory.alloc(16);
    ivAddr.writeByteArray(iv);

    const ranges = Process.enumerateRanges({protection: 'rw-', coalesce: true});
    send({type: 'info', regions: ranges.length});
    for (let i = 0; i < ranges.length; i++) {
        if (stats.done || stats.found) break;
        stats.regions++;
        try {
            if (scanRegion(ranges[i].base, ranges[i].size, encPage, encLen, headerFrag, ivAddr)) {
                break;
            }
        } catch (e) {
            send({type: 'error', msg: 'region ' + i + ': ' + e.message});
        }
    }
    stats.done = true;
    send({type: 'done', found: stats.found, regions: stats.regions,
          bytes: stats.bytes, candidates: stats.candidates, validated: stats.validated});
});
"""


def find_wecom_pid() -> int:
    import subprocess
    result = subprocess.run(["pgrep", "-f", "/Applications/企业微信.app/Contents/MacOS/企业微信"],
                          capture_output=True, text=True, check=False)
    for line in result.stdout.splitlines():
        if line.strip().isdigit():
            return int(line.strip())
    raise SystemExit("企业微信未运行")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan WeCom memory for the database key")
    parser.add_argument("--data-dir")
    parser.add_argument("--duration", type=int, default=300)
    args = parser.parse_args()

    dataset = choose_dataset(args.data_dir) if args.data_dir else choose_dataset(None)
    print(f"dataset: {dataset_id(dataset)}")

    target_db = None
    for relative, path in iter_databases(dataset):
        with path.open("rb") as f:
            first_page = f.read(PAGE_SIZE)
        if database_format(first_page) == "wecom-wxsqlite3-aes128":
            target_db = path
            break
    if not target_db:
        raise SystemExit("未找到加密数据库")
    print(f"validation database: {target_db.name}")

    with target_db.open("rb") as f:
        page1 = f.read(PAGE_SIZE)

    header_fragment = list(page1[16:24])
    ciphertext = page1[8:16] + page1[24:]
    iv = list(page_iv_bytes(1))
    enc_len = len(ciphertext)

    print(f"ciphertext length: {enc_len}, iv: {bytes(iv).hex()}")

    import frida
    pid = find_wecom_pid()
    print(f"attaching to WeCom PID={pid}")
    device = frida.get_local_device()
    session = device.attach(pid)

    messages: queue.Queue = queue.Queue()

    def on_message(msg, data):
        if msg.get("type") == "send":
            payload = msg.get("payload") or {}
            if isinstance(payload, dict):
                messages.put(payload)
        elif msg.get("type") == "error":
            messages.put({"type": "error", "msg": msg.get("description", str(msg))})

    script = session.create_script(SCAN_AGENT)
    script.on("message", on_message)
    script.load()
    print("agent loaded, sending page1 data...")

    script.post({
        "type": "page1",
        "page1": list(page1),
        "encLen": enc_len,
        "headerFragment": header_fragment,
        "iv": iv,
    })

    found_key = None
    deadline = time.monotonic() + args.duration

    while time.monotonic() < deadline:
        try:
            payload = messages.get(timeout=1.0)
        except queue.Empty:
            continue

        ptype = payload.get("type")
        if ptype == "key":
            found_key = payload.get("key")
            print(f"  KEY FOUND: {found_key}")
            break
        elif ptype == "progress":
            mb = payload.get("bytes", 0) // 1024 // 1024
            print(f"  scanned {mb}MB, {payload.get('candidates', 0)} candidates")
        elif ptype == "info":
            print(f"  scanning {payload.get('regions', 0)} RW regions...")
        elif ptype == "done":
            mb = payload.get("bytes", 0) // 1024 // 1024
            print(f"  done: found={payload.get('found')}, regions={payload.get('regions')}, "
                  f"scanned={mb}MB, candidates={payload.get('candidates')}, validated={payload.get('validated')}")
            break
        elif ptype == "error":
            print(f"  error: {payload.get('msg')}", file=sys.stderr)

    try:
        script.unload()
    except Exception:
        pass
    try:
        session.detach()
    except Exception:
        pass

    if not found_key:
        print("scan complete, no key found")
        return 1

    candidate = bytes.fromhex(found_key)
    validated = validate_candidate(candidate, dataset)
    if not validated:
        print(f"candidate did not validate against databases")
        return 1

    saved = save_validated_key(candidate, dataset, validated)
    print(f"VALIDATED_AND_SAVED: {saved} ({len(validated)} databases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
