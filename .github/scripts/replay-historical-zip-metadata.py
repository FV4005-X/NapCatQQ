#!/usr/bin/env python3
"""Repack locally reconstructed files with historical ZIP metadata and order.

The historical ZIP is read ONLY for names/timestamps/modes and verification.
It NEVER supplies output file contents or compressed streams.
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path

ARCHIVES = {
    "NapCat.Framework.zip": "replay_framework",
    "NapCat.Shell.zip": "replay_shell",
    "NapCat.Shell.Windows.Node.zip": "replay_windows",
}

def historical_ut(info):
    extra = info.extra
    offset = 0
    while offset + 4 <= len(extra):
        tag, n = struct.unpack_from("<HH", extra, offset)
        field = extra[offset + 4:offset + 4 + n]
        if tag == 0x5455 and len(field) >= 5 and field[0] & 1:
            return struct.unpack_from("<I", field, 1)[0]
        offset += 4 + n
    raise RuntimeError(f"Missing UT timestamp: {info.filename}")

def historical_atime(raw_archive, info):
    """Read atime only from original ZIP's local UT metadata, never file data."""
    raw_archive.seek(info.header_offset)
    header = raw_archive.read(30)
    if len(header) != 30 or header[:4] != b"PK\x03\x04":
        raise RuntimeError(f"Malformed local ZIP header: {info.filename}")
    fields = struct.unpack("<IHHHHHIIIHH", header)
    filename_length, extra_length = fields[-2:]
    raw_archive.seek(info.header_offset + 30 + filename_length)
    extra = raw_archive.read(extra_length)
    offset = 0
    while offset + 4 <= len(extra):
        tag, n = struct.unpack_from("<HH", extra, offset)
        data = extra[offset + 4:offset + 4 + n]
        if tag == 0x5455 and data:
            flags = data[0]
            pos = 1
            if flags & 1:
                pos += 4
            if flags & 2 and len(data) >= pos + 4:
                return struct.unpack_from("<I", data, pos)[0]
        offset += 4 + n
    return historical_ut(info)


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def metadata_delta(output, original):
    with zipfile.ZipFile(output) as mine, zipfile.ZipFile(original) as old:
        me = {i.filename: i for i in mine.infolist()}
        them = {i.filename: i for i in old.infolist()}
        shared = set(me) & set(them)
        fields = ("CRC", "file_size", "compress_size", "compress_type",
                  "extra", "external_attr", "internal_attr", "flag_bits")
        differences = [
            name for name in shared
            if any(getattr(me[name], field) != getattr(them[name], field)
                   for field in fields)
        ]
        return {
            "ours_entries": len(me), "original_entries": len(them),
            "metadata_different_entries": len(differences),
            "first_different_entries": sorted(differences)[:20],
            "ours_only": sorted(set(me) - set(them))[:20],
            "original_only": sorted(set(them) - set(me))[:20],
        }

def raw_zip_diagnostics(output, original):
    """Locate remaining byte differences; never use reference payloads for output."""
    def raw_segments(path):
        with zipfile.ZipFile(path) as archive, path.open("rb") as fp:
            segments = {}
            for info in archive.infolist():
                fp.seek(info.header_offset)
                header = fp.read(30)
                if len(header) != 30 or header[:4] != b"PK\x03\x04":
                    raise RuntimeError(f"Bad local header in {path}")
                fields = struct.unpack("<IHHHHHIIIHH", header)
                filename_length, extra_length = fields[-2:]
                local_header = header + fp.read(filename_length + extra_length)
                payload = fp.read(info.compress_size)
                segments[info.filename] = {
                    "local_header_sha256": hashlib.sha256(local_header).hexdigest(),
                    "compressed_stream_sha256": hashlib.sha256(payload).hexdigest(),
                    "local_header_hex": local_header[:96].hex(),
                    "header_offset": info.header_offset,
                    "create_version": info.create_version,
                    "extract_version": info.extract_version,
                    "comment_hex": info.comment.hex(),
                }
            return segments, archive.start_dir, archive.comment.hex()

    left, left_start, left_comment = raw_segments(output)
    right, right_start, right_comment = raw_segments(original)
    shared = set(left) & set(right)
    header_diff = sorted(
        x for x in shared
        if left[x]["local_header_sha256"] != right[x]["local_header_sha256"]
    )
    deflate_diff = sorted(
        x for x in shared
        if left[x]["compressed_stream_sha256"] != right[x]["compressed_stream_sha256"]
    )
    offset_diff = sorted(
        x for x in shared
        if left[x]["header_offset"] != right[x]["header_offset"]
    )

    # First disagreement offsets in the full archive, chunked to avoid large reads.
    positions = []
    first_samples = []
    with output.open("rb") as left_file, original.open("rb") as right_file:
        cursor = 0
        while True:
            a = left_file.read(131072)
            b = right_file.read(131072)
            if not a and not b:
                break
            if a != b:
                for k in range(min(len(a), len(b))):
                    if a[k] != b[k]:
                        if len(positions) < 80:
                            positions.append(cursor + k)
                        if len(first_samples) < 12:
                            first_samples.append({
                                "offset": cursor + k,
                                "ours_byte": f"{a[k]:02x}",
                                "official_byte": f"{b[k]:02x}",
                            })
            cursor += min(len(a), len(b))
            if len(positions) >= 80 and len(first_samples) >= 12:
                break
    return {
        "compressed_streams_identical": len(shared) - len(deflate_diff),
        "compressed_streams_different": len(deflate_diff),
        "first_compressed_stream_differences": deflate_diff[:15],
        "local_headers_identical": len(shared) - len(header_diff),
        "local_headers_different": len(header_diff),
        "first_local_header_differences": [
            {"path": x, "ours": left[x], "official": right[x]}
            for x in header_diff[:5]
        ],
        "local_header_offsets_different": len(offset_diff),
        "first_offset_differences": offset_diff[:10],
        "our_central_directory_offset": left_start,
        "official_central_directory_offset": right_start,
        "our_archive_comment_hex": left_comment,
        "official_archive_comment_hex": right_comment,
        "first_byte_differences": first_samples,
        "first_80_byte_difference_positions": positions,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-dir", type=Path, default=Path("official_zips"))
    parser.add_argument("--output-dir", type=Path, default=Path("historical_exact_replay"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    for archive_name, source_name in ARCHIVES.items():
        source = Path(source_name)
        reference_file = args.official_dir / archive_name
        result_file = args.output_dir / archive_name

        with zipfile.ZipFile(reference_file) as reference, reference_file.open("rb") as raw_reference:
            ordered = reference.infolist()
            required = {i.filename for i in ordered}
            actual = {
                p.relative_to(source).as_posix() + ("/" if p.is_dir() else "")
                for p in source.rglob("*")
            }
            missing = required - actual
            extra = actual - required
            hidden = {
                name for name in extra
                if any(part.startswith(".") for part in name.rstrip("/").split("/"))
            }
            unexpected = extra - hidden
            if missing or unexpected:
                raise SystemExit(
                    f"{archive_name}: missing={sorted(missing)[:15]}, "
                    f"unexpected non-hidden={sorted(unexpected)[:15]}"
                )

            # Original upload-artifact excluded hidden files; do the same.
            for name in sorted(hidden, key=lambda x: len(x.split("/")), reverse=True):
                item = source / name.rstrip("/")
                if item.is_dir():
                    shutil.rmtree(item)
                elif item.exists():
                    item.unlink()

            # All payload bytes come exclusively from the locally created tree.
            for entry in ordered:
                item = source / entry.filename
                if not item.exists() or item.is_symlink():
                    raise SystemExit(f"Missing/linked independently-built file: {item}")
                os.chmod(item, (entry.external_attr >> 16) & 0o7777)
                when = historical_ut(entry)
                accessed = historical_atime(raw_reference, entry)
                os.utime(item, (accessed, when), follow_symlinks=False)

            # Reset parent directory times last because modifying children changes mtime.
            for entry in sorted((x for x in ordered if x.is_dir()),
                                key=lambda x: len(x.filename), reverse=True):
                item = source / entry.filename
                when = historical_ut(entry)
                accessed = historical_atime(raw_reference, entry)
                os.utime(item, (accessed, when), follow_symlinks=False)

            # Info-ZIP, not Python zipfile. Pass the exact historical entry order.
            paths = "\n".join(info.filename for info in ordered) + "\n"
            subprocess.run(
                ["zip", "-q", "-@", str(result_file.resolve())],
                input=paths, text=True, cwd=source, check=True
            )

        our_hash, expected = sha(result_file), sha(reference_file)
        results[archive_name] = {
            "reconstructed_sha256": our_hash,
            "original_sha256": expected,
            "identical": our_hash == expected,
            "reconstructed_size": result_file.stat().st_size,
            "original_size": reference_file.stat().st_size,
            "removed_unpublished_hidden_entries": len(hidden),
            "metadata_comparison": metadata_delta(result_file, reference_file),
            "raw_byte_diagnostics": raw_zip_diagnostics(result_file, reference_file),
        }
        print(archive_name, json.dumps(results[archive_name]), flush=True)

    (args.output_dir / "RESULTS.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

if __name__ == "__main__":
    main()
