#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Static checks for the 5.18-style PAS request_queue state types."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def struct_body(source: str, name: str) -> str:
    match = re.search(rf"struct\s+{name}\s*\{{", source)
    require(match is not None, f"struct {name} not found")

    start = match.end()
    end = source.find("};", start)
    require(end != -1, f"struct {name} terminator not found")
    return source[start:end]


def main() -> int:
    blk_types = read("include/linux/blk_types.h")
    blkdev = read("include/linux/blkdev.h")

    body = struct_body(blk_types, "blk_rq_pas_stat")
    for field in (
        "u64 dur;",
        "long long adj;",
        "long long up;",
        "long long dn;",
        "u8 sr_pnlt;",
        "u8 sr_last;",
        "u8 update_req;",
        "u8 dur_cnt;",
        "u8 dur_cnt_checked;",
    ):
        require(field in body, f"struct blk_rq_pas_stat missing {field}")

    require(
        "struct blk_rq_pas_stat __percpu *pas_stat;" in blkdev,
        "request_queue must point to per-CPU blk_rq_pas_stat buckets",
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
