#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Static checks for 5.18-style PAS queue allocation and defaults."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    blkdev = read("include/linux/blkdev.h")
    blk_mq = read("block/blk-mq.c")

    for token in (
        "#define BLK_MQ_POLL_STATS_BKTS 16",
        "#define BLK_MQ_POLL_CLASSIC -1",
    ):
        require(token in blkdev, f"missing {token}")

    for token in (
        "static void init_pas_stat(struct blk_rq_pas_stat *stat,",
        "stat->dur = dur;",
        "stat->adj = adj;",
        "stat->sr_pnlt = 0;",
        "stat->sr_last = 1;",
        "stat->dur_cnt = 1;",
        "stat->dur_cnt_checked = 0;",
        "stat->update_req = 0;",
    ):
        require(token in blk_mq, f"missing PAS stat initializer token: {token}")

    for token in (
        "q->poll_nsec = BLK_MQ_POLL_CLASSIC;",
        "q->max_no_lock = 100;",
        "q->poll_threshold = 0;",
        "q->div = 1000000;",
        "q->d_init = 100;",
        "q->up_init = 10000;",
        "q->dn_init = 100000;",
        "q->heat_up = 50000;",
        "q->cool_dn = 100000;",
        "q->min_dn = 10000;",
        "q->max_dn = 100000;",
        "q->updn_ratio = 10;",
        "q->switch_param1 = 0;",
        "q->switch_param7 = 10000;",
    ):
        require(token in blk_mq, f"missing PAS queue default: {token}")

    require(
        "q->pas_stat = __alloc_percpu(BLK_MQ_POLL_STATS_BKTS *" in blk_mq,
        "q->pas_stat must be allocated as 16 PAS buckets per CPU",
    )
    require(
        "init_pas_stat(&stat[bucket_idx], q->d_init, q->div, q->up_init, q->dn_init);" in blk_mq,
        "each PAS bucket must be initialized from request_queue defaults",
    )
    require(
        "free_percpu(q->pas_stat);" in blk_mq,
        "q->pas_stat must be freed when the mq queue is released",
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
