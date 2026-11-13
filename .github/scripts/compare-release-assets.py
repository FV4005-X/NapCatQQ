#!/usr/bin/env python3
"""Compare v4.18.42 third-party Release ZIPs with this repo's release candidate.

No archive is extracted and no downloaded code is executed.
"""
import argparse
import csv
import hashlib
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ARCHIVES = [
    "NapCat.Framework.zip",
    "NapCat.Shell.zip",
    "NapCat.Shell.Windows.Node.zip",
]
IMPORTANT_NAMES = {
    "express", "ws", "encodeurl", "body-parser", "send", "serve-static",
    "cookie", "path-to-regexp", "router", "finalhandler", "http-errors",
}


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def category(path):
    p = path.lower()
    if "node_modules/" in p or p.startswith("node_modules/"):
        return "production_dependencies"
    if p.endswith("build-provenance.json"):
        return "build_metadata"
    if p == "package.json" or p.endswith("/package.json"):
        return "package_manifest"
    if p.startswith(("static/", "napcat/static/")):
        return "webui"
    if p.startswith(("native/", "napcat/native/")) or p.endswith((".dll", ".node", ".exe")):
        return "native_windows_or_addons"
    if p.endswith((".js", ".mjs", ".cjs", ".map")):
        return "program_code"
    return "other_assets"


def packages(infos, archive):
    found = defaultdict(set)
    direct = defaultdict(set)
    for path in infos:
        if not path.endswith("/package.json") or "node_modules/" not in path:
            continue
        try:
            pkg = json.loads(archive.read(path))
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(pkg, dict) or not pkg.get("name") or not pkg.get("version"):
            continue
        found[pkg["name"]].add(str(pkg["version"]))
        # In the distributable layout, root /node_modules/<package>
        # and /napcat/node_modules/<package> are the direct installed packages.
        if re.match(r"^(?:napcat/)?node_modules/(?:@[^/]+/)?[^/]+/package\.json$", path):
            direct[pkg["name"]].add(str(pkg["version"]))
    return found, direct


def zip_inventory(path):
    entries = {}
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            if item.is_dir():
                continue
            if item.filename in entries:
                raise RuntimeError(f"Duplicate path in {path.name}: {item.filename}")
            digest = hashlib.sha256()
            with archive.open(item) as fp:
                for chunk in iter(lambda: fp.read(1024 * 1024), b""):
                    digest.update(chunk)
            entries[item.filename] = {
                "sha256": digest.hexdigest(),
                "size": item.file_size,
                "compressed_size": item.compress_size,
                "crc32": f"{item.CRC:08x}",
                "zip_timestamp": list(item.date_time),
                "zip_external_attr": item.external_attr,
                "zip_compression": item.compress_type,
            }
        all_packages, direct_packages = packages(entries, archive)
    return entries, all_packages, direct_packages


def display_versions(pkgs, name):
    vals = pkgs.get(name, set())
    return ", ".join(sorted(vals)) if vals else "(absent)"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ours-dir", type=Path, required=True)
    parser.add_argument("--third-party-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    report = {"source_commit": "9335843246e3b7a17944861f3ac8731a259732c2",
              "ours": "FV4005-X/NapCatQQ Actions #43281514637",
              "third_party": "XingYunStar/NapCatQQ Release v4.18.42",
              "archives": {}}
    file_rows = []
    version_rows = []
    md = [
        "# NapCat v4.18.42 双方 Release 逐文件 SHA256 对比",
        "",
        "- 我方：FV4005-X/NapCatQQ 的 Release Publish #43281514637（提交 28741a9）",
        "- 第三方：XingYunStar/NapCatQQ v4.18.42 Release",
        "- 双方源码 tag 均指向 9335843246e3b7a17944861f3ac8731a259732c2。",
        "- 比较方法：读取 ZIP 内文件解压字节，计算 SHA256；不执行第三方文件。",
        "",
        "## 总览",
        "",
        "| 压缩包 | 我方文件 | 第三方文件 | 内容相同 | 同名不同 | 我方独有 | 第三方独有 | ZIP整体相同 |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for archive_name in ARCHIVES:
        ours_file = args.ours_dir / archive_name
        third_file = args.third_party_dir / archive_name
        ours_zip_sha = sha256_file(ours_file)
        third_zip_sha = sha256_file(third_file)
        mine, mine_packages, mine_direct = zip_inventory(ours_file)
        theirs, third_packages, third_direct = zip_inventory(third_file)
        same_names = set(mine) & set(theirs)
        same = sorted(p for p in same_names if mine[p]["sha256"] == theirs[p]["sha256"])
        changed = sorted(p for p in same_names if mine[p]["sha256"] != theirs[p]["sha256"])
        only_mine = sorted(set(mine) - set(theirs))
        only_third = sorted(set(theirs) - set(mine))
        metadata_diff = sorted(
            p for p in same
            if any(mine[p][k] != theirs[p][k] for k in
                   ("zip_timestamp", "zip_external_attr", "zip_compression"))
        )

        cat_stats = defaultdict(Counter)
        for status, items in [
            ("identical", same), ("different_content", changed),
            ("ours_only", only_mine), ("third_party_only", only_third),
        ]:
            for p in items:
                cat_stats[category(p)][status] += 1
                ours = mine.get(p, {})
                third = theirs.get(p, {})
                file_rows.append({
                    "archive": archive_name, "status": status, "category": category(p),
                    "path": p, "ours_sha256": ours.get("sha256", ""),
                    "third_party_sha256": third.get("sha256", ""),
                    "ours_size": ours.get("size", ""),
                    "third_party_size": third.get("size", ""),
                })
        all_names = set(mine_packages) | set(third_packages)
        version_diffs = []
        for name in sorted(all_names):
            mine_versions = mine_packages.get(name, set())
            third_versions = third_packages.get(name, set())
            diff = mine_versions != third_versions
            version_rows.append({
                "archive": archive_name, "package": name,
                "ours_versions": ", ".join(sorted(mine_versions)),
                "third_party_versions": ", ".join(sorted(third_versions)),
                "different": str(diff).lower(),
                "ours_top_level": ", ".join(sorted(mine_direct.get(name, set()))),
                "third_party_top_level": ", ".join(sorted(third_direct.get(name, set()))),
            })
            if diff:
                version_diffs.append({
                    "name": name,
                    "ours": sorted(mine_versions),
                    "third_party": sorted(third_versions),
                })

        summary = {
            "ours_zip": {"size": ours_file.stat().st_size, "sha256": ours_zip_sha},
            "third_party_zip": {"size": third_file.stat().st_size, "sha256": third_zip_sha},
            "ours_files": len(mine), "third_party_files": len(theirs),
            "identical_files": len(same), "different_content_files": len(changed),
            "ours_only_files": len(only_mine), "third_party_only_files": len(only_third),
            "identical_content_with_different_zip_metadata": len(metadata_diff),
            "zip_identical": ours_zip_sha == third_zip_sha,
            "categories": {k: dict(v) for k, v in sorted(cat_stats.items())},
            "different_files": changed,
            "ours_only_paths": only_mine,
            "third_party_only_paths": only_third,
            "runtime_dependency_version_differences": version_diffs,
            "important_runtime_versions": {
                name: {"ours": display_versions(mine_packages, name),
                       "third_party": display_versions(third_packages, name)}
                for name in sorted(IMPORTANT_NAMES)
            },
            "core_file_sha256": {
                p: {"ours": mine[p]["sha256"] if p in mine else None,
                    "third_party": theirs[p]["sha256"] if p in theirs else None,
                    "identical": p in mine and p in theirs and mine[p]["sha256"] == theirs[p]["sha256"]}
                for p in ("napcat.mjs", "napcat/napcat.mjs", "wrapper.node",
                          "NapCatWinBootHook.dll", "napcat/NapCatWinBootHook.dll",
                          "node.exe", "loadNapCat.js", "napcat/loadNapCat.js")
                if p in mine or p in theirs
            },
            "matching_files_differing_in_zip_metadata": metadata_diff[:30],
        }
        report["archives"][archive_name] = summary
        md.append(
            f"| {archive_name} | {len(mine)} | {len(theirs)} | {len(same)} | "
            f"{len(changed)} | {len(only_mine)} | {len(only_third)} | "
            f"{'是' if summary['zip_identical'] else '否'} |"
        )

    md.append("")
    for name, data in report["archives"].items():
        md.extend([
            f"## {name}", "",
            f"- 我方 ZIP：\u0060{data['ours_zip']['sha256']}\u0060（{data['ours_zip']['size']} 字节）",
            f"- 第三方 ZIP：\u0060{data['third_party_zip']['sha256']}\u0060（{data['third_party_zip']['size']} 字节）",
            f"- 同内容但 ZIP 元数据不同的文件：{data['identical_content_with_different_zip_metadata']}",
            f"- **生产依赖版本不同的包：{len(data['runtime_dependency_version_differences'])} 个**",
            "", "### 文件类别差异", "",
            "| 类别 | 内容一致 | 内容不同 | 我方独有 | 第三方独有 |",
            "|---|---:|---:|---:|---:|",
        ])
        for cat, stats in data["categories"].items():
            md.append(
                f"| {cat} | {stats.get('identical',0)} | {stats.get('different_content',0)} "
                f"| {stats.get('ours_only',0)} | {stats.get('third_party_only',0)} |"
            )
        md.extend(["", "### 关键依赖版本", "",
                   "| 包 | 我方版本 | 第三方版本 |", "|---|---|---|"])
        for pkg, versions in data["important_runtime_versions"].items():
            md.append(f"| {pkg} | {versions['ours']} | {versions['third_party']} |")
        md.extend(["", "### 核心文件 SHA256", "",
                   "| 文件 | 我方 | 第三方 | 相同 |", "|---|---|---|---|"])
        for path, vals in data["core_file_sha256"].items():
            md.append(
                f"| {path} | \u0060{vals['ours']}\u0060 | "
                f"\u0060{vals['third_party']}\u0060 | {'是' if vals['identical'] else '否'} |"
            )
        if data["runtime_dependency_version_differences"]:
            md.extend(["", "### 全部生产依赖版本差异", "",
                       "| 包 | 我方版本 | 第三方版本 |", "|---|---|---|"])
            for pkg in data["runtime_dependency_version_differences"]:
                md.append(f"| {pkg['name']} | {', '.join(pkg['ours']) or '(absent)'} | "
                          f"{', '.join(pkg['third_party']) or '(absent)'} |")
        for label, paths in [
            ("内容不同文件", data["different_files"]),
            ("我方独有文件", data["ours_only_paths"]),
            ("第三方独有文件", data["third_party_only_paths"]),
        ]:
            md.extend(["", f"### {label}（{len(paths)}）", ""])
            if paths:
                md.extend(f"- \u0060{p}\u0060" for p in paths[:80])
                if len(paths) > 80:
                    md.append(f"- ……余 {len(paths)-80} 项见 FILE-DIFF.csv")
            else:
                md.append("无")
        md.append("")

    (args.output_dir / "COMPARISON.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "COMPARISON.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8"
    )
    for name, rows, headers in [
        ("FILE-DIFF.csv", file_rows,
         ["archive","status","category","path","ours_sha256","third_party_sha256",
          "ours_size","third_party_size"]),
        ("DEPENDENCY-VERSIONS.csv", version_rows,
         ["archive","package","ours_versions","third_party_versions","different",
          "ours_top_level","third_party_top_level"])
    ]:
        with (args.output_dir / name).open("w", encoding="utf-8-sig", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
    print("\n".join(md[:16]))
    print(f"\nFull report saved to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
