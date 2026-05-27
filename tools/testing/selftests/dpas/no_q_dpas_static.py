#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Static guard that rejects the old q->dpas split-state skeleton."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]

FORBIDDEN_TOKENS = (
    "q->dpas",
    "struct dpas_queue",
    "blk_dpas_queue_init",
    "blk_dpas_queue_exit",
    "blk_dpas_poll_count",
    "blk_dpas_queue_enabled",
)

CHECKED_PATHS = (
    "include/linux/blkdev.h",
    "block/Makefile",
    "block/blk-core.c",
    "block/blk-mq.c",
    "block/blk-sysfs.c",
    "fs/iomap/direct-io.c",
)


def main() -> int:
    failures: list[str] = []

    for relpath in CHECKED_PATHS:
        path = ROOT / relpath
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if token in text:
                failures.append(f"{relpath}: still contains {token!r}")

    for relpath in ("block/blk-dpas.c", "block/blk-dpas.h"):
        if (ROOT / relpath).exists():
            failures.append(f"{relpath}: old q->dpas skeleton file still exists")

    if failures:
        print("FAIL: q->dpas split-state skeleton remains:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
