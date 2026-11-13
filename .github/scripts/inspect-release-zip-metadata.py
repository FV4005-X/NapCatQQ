#!/usr/bin/env python3
"""Read-only archive structure and metadata audit for historical ZIP reproducibility."""
import hashlib
import json
import os
import struct
import sys
import zipfile
from collections import Counter
from pathlib import Path

OUT = Path("comparison") / "ZIP-METADATA.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
NAMES = [
    "NapCat.Framework.zip",
    "NapCat.Shell.zip",
    "NapCat.Shell.Windows.Node.zip",
]

def payload_digest(fp, info):
    fp.seek(info.header_offset)
    header = fp.read(30)
    if len(header) != 30 or header[:4] != b"PK\x03\x04":
        raise RuntimeError("Bad local ZIP header")
    _, _, _, _, _, _, _, _, _, fname_len, extra_len = struct.unpack("<IHHHHHIIIHH", header)
    fp.seek(info.header_offset + 30 + fname_len + extra_len)
    remaining = info.compress_size
    sha = hashlib.sha256()
    while remaining:
        buf=fp.read(min(65536, remaining))
        if not buf: raise RuntimeError("Truncated deflate stream")
        sha.update(buf)
        remaining -= len(buf)
    return sha.hexdigest()

report={}
lines=["# 历史 ZIP 元数据对比",""]
for name in NAMES:
    report[name]={}
    for label,dirname in (("ours","ours"),("official","third_party")):
        path=Path(dirname)/name
        with zipfile.ZipFile(path) as z, open(path,"rb") as src:
            infos=z.infolist()
            entries={}
            for info in infos:
                entries[info.filename]={
                    "datetime":"-".join(map(str,info.date_time)),
                    "permission_octal":oct((info.external_attr>>16)&0xffff),
                    "external_attr":info.external_attr,
                    "internal_attr":info.internal_attr,
                    "create_system":info.create_system,
                    "create_version":info.create_version,
                    "extract_version":info.extract_version,
                    "flag_bits":info.flag_bits,
                    "compress_type":info.compress_type,
                    "extra_hex":info.extra.hex(),
                    "comment_hex":info.comment.hex(),
                    "is_dir":info.is_dir(),
                    "compress_size":info.compress_size,
                    "file_size":info.file_size,
                    "compressed_sha256":None if info.is_dir() else payload_digest(src,info),
                }
            # print path names and timestamps; retain full per-file metadata for matching.
            report[name][label]={
                "file_count":len(infos),
                "archive_comment_hex":z.comment.hex(),
                "leading_entries":[x.filename for x in infos[:25]],
                "trailing_entries":[x.filename for x in infos[-20:]],
                "entry_timestamps":dict(Counter(e["datetime"] for e in entries.values()).most_common(20)),
                "create_systems":dict(Counter(str(e["create_system"]) for e in entries.values())),
                "permission_modes":dict(Counter(e["permission_octal"] for e in entries.values())),
                "compression_types":dict(Counter(str(e["compress_type"]) for e in entries.values())),
                "flags":dict(Counter(str(e["flag_bits"]) for e in entries.values())),
                "extra_field_patterns":dict(Counter(e["extra_hex"][:8] for e in entries.values()).most_common(10)),
                "entries":entries,
            }
    ours=report[name]["ours"]
    official=report[name]["official"]
    common=set(ours["entries"])&set(official["entries"])
    compressed_same=0
    non_directory=0
    for x in common:
        a=ours["entries"][x]
        b=official["entries"][x]
        if not a["is_dir"] and not b["is_dir"] and a["file_size"]==b["file_size"]:
            non_directory+=1
            compressed_same+=(a["compressed_sha256"]==b["compressed_sha256"])
    report[name]["comparison"]={
        "common_names":len(common),
        "common_compressed_sha256_equal_with_equal_uncompressed_sizes":compressed_same,
        "common_equal_uncompressed_size_comparisons":non_directory,
    }
    lines.extend([
        f"## {name}","",
        f"我方项目数：{ours['file_count']}；原版项目数：{official['file_count']}",
        f"原版文件时间戳 TOP 20：\u0060{official['entry_timestamps']}\u0060",
        f"原版 Unix 文件模式：\u0060{official['permission_modes']}\u0060",
        f"原版压缩方法：\u0060{official['compression_types']}\u0060",
        f"原版额外字段开头：\u0060{official['extra_field_patterns']}\u0060",
        f"原版头部文件名：\u0060{official['leading_entries'][:12]}\u0060",
        f"相同相对路径、相同未压缩文件大小时，压缩流字节一致的数量："
        f"{compressed_same} / {non_directory}",
        "",
    ])
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
Path("comparison/ZIP-METADATA.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
print("\n".join(lines))
