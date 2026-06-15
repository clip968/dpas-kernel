#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Static checks for request_queue based full DPAS mode switching.

This test intentionally replaces the older partial PAS/static guards.  The
current DPAS design keeps mode state directly in struct request_queue and
splits responsibility this way:

* submit path: decide whether HIPRI bio stays polled or becomes interrupt I/O
* poll path: update PAS/QD/tf state and switch CP/PAS/OL modes
* sysfs: expose switch_enabled and reset the mode window safely
"""

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


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def find_braced_body(source: str, marker: str) -> str:
    start = source.find(marker)
    require(start != -1, f"{marker} not found")

    brace = source.find("{", start)
    require(brace != -1, f"{marker} body start not found")

    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1 : index]

    raise AssertionError(f"{marker} body end not found")


def require_tokens(source: str, tokens: tuple[str, ...], context: str) -> None:
    for token in tokens:
        require(token in source, f"{context}: missing {token}")


def require_patterns(source: str, patterns: tuple[str, ...], context: str) -> None:
    for pattern in patterns:
        require(re.search(pattern, source), f"{context}: missing pattern {pattern}")


def require_in_order(source: str, tokens: tuple[str, ...], context: str) -> None:
    offset = 0
    for token in tokens:
        index = source.find(token, offset)
        require(index != -1, f"{context}: missing ordered token {token}")
        offset = index + len(token)


def check_queue_state() -> None:
    blkdev = read("include/linux/blkdev.h")
    request_queue = find_braced_body(blkdev, "struct request_queue {")

    require_tokens(
        blkdev,
        (
            "enum dpas_mode",
            "DPAS_MODE_INT = 0",
            "DPAS_MODE_CP = 1",
            "DPAS_MODE_PAS = 2",
            "DPAS_MODE_OL = 3",
            "bool blk_dpas_prepare_bio(struct request_queue *q, struct bio *bio,",
        ),
        "blkdev.h",
    )
    require_patterns(
        request_queue,
        (
            r"\bspinlock_t\s+dpas_lock\b",
            r"\benum\s+dpas_mode\s+dpas_mode\s*;",
            r"\bu32\s+dpas_cp_cnt\s*;",
            r"\bu32\s+dpas_pas_cnt\s*;",
            r"\bu32\s+dpas_ol_cnt\s*;",
            r"\bu32\s+dpas_int_cnt\s*;",
            r"\bu32\s+dpas_qd\s*;",
            r"\bu64\s+dpas_qd_sum\s*;",
            r"\bu32\s+dpas_tf\s*;",
            r"\bint\s+switch_enabled\s*;",
            r"\bint\s+switch_param1\s*;",
            r"\bint\s+switch_param7\s*;",
        ),
        "struct request_queue DPAS state",
    )


def check_queue_initialization() -> None:
    blk_mq = read("block/blk-mq.c")
    init_body = find_braced_body(blk_mq, "int blk_mq_init_allocated_queue(")

    require_in_order(
        init_body,
        (
            "spin_lock_init(&q->dpas_lock);",
            "q->switch_enabled = 0;",
            "q->dpas_mode = DPAS_MODE_PAS;",
            "q->dpas_cp_cnt = 0;",
            "q->dpas_pas_cnt = 0;",
            "q->dpas_ol_cnt = 0;",
            "q->dpas_int_cnt = 0;",
            "q->dpas_qd = 0;",
            "q->dpas_qd_sum = 0;",
            "q->dpas_tf = 0;",
        ),
        "queue init DPAS defaults",
    )
    require_tokens(
        init_body,
        (
            "q->switch_param1 = 0;",
            "q->switch_param2 = 10;",
            "q->switch_param3 = 10;",
            "q->switch_param4 = 1;",
            "q->switch_param5 = 100;",
            "q->switch_param6 = 1000;",
            "q->switch_param7 = 10000;",
        ),
        "queue init switch_param defaults",
    )


def check_switch_enabled_sysfs() -> None:
    blk_sysfs = read("block/blk-sysfs.c")
    reset_body = find_braced_body(blk_sysfs, "static void queue_dpas_reset_switch_state(")
    store_body = find_braced_body(blk_sysfs, "static ssize_t queue_switch_enabled_store(")
    mq_attrs = find_braced_body(
        blk_sysfs, "static const struct attribute *const blk_mq_queue_attrs[]"
    )

    require_in_order(
        reset_body,
        (
            "q->dpas_mode = DPAS_MODE_PAS;",
            "q->dpas_cp_cnt = 0;",
            "q->dpas_int_cnt = 0;",
            "q->dpas_pas_cnt = 0;",
            "q->dpas_ol_cnt = 0;",
            "q->dpas_qd = 0;",
            "q->dpas_qd_sum = 0;",
            "q->dpas_tf = 0;",
        ),
        "switch_enabled reset state",
    )
    require_tokens(
        store_body,
        (
            "queue_dpas_poll_capable(q)",
            "kstrtoint(page, 10, &val)",
            "if (val < 0 || val > 1)",
            "spin_lock_irqsave(&q->dpas_lock, flags_lock);",
            "q->switch_enabled = val;",
            "queue_dpas_reset_switch_state(q);",
            "spin_unlock_irqrestore(&q->dpas_lock, flags_lock);",
        ),
        "switch_enabled store",
    )
    require_tokens(
        blk_sysfs,
        ('QUEUE_RW_ENTRY(queue_switch_enabled, "switch_enabled");',),
        "switch_enabled sysfs entry",
    )
    require_tokens(
        mq_attrs,
        ("&queue_switch_enabled_entry.attr,",),
        "switch_enabled mq attr registration",
    )


def check_submit_helper() -> None:
    blk_core = read("block/blk-core.c")
    fops = read("block/fops.c")
    iomap = read("fs/iomap/direct-io.c")
    helper = find_braced_body(blk_core, "bool blk_dpas_prepare_bio(")
    helper_c = compact(helper)

    require_tokens(
        blk_core,
        ("EXPORT_SYMBOL_GPL(blk_dpas_prepare_bio);",),
        "blk_dpas_prepare_bio export",
    )
    require_tokens(
        fops,
        (
            "iocb->ki_flags & IOCB_HIPRI &&",
            "blk_dpas_prepare_bio(bdev_get_queue(bio->bi_bdev), bio, iocb)",
            "WRITE_ONCE(iocb->private, bio);",
        ),
        "raw block DIO submit hook",
    )
    require_tokens(
        iomap,
        (
            "if (iocb->ki_flags & IOCB_HIPRI)",
            "blk_dpas_prepare_bio(bdev_get_queue(bio->bi_bdev), bio, iocb)",
            "dio->submit.poll_bio = bio;",
        ),
        "iomap DIO submit hook",
    )
    require_tokens(
        helper,
        (
            "if (!q->switch_enabled)",
            "bio_set_polled(bio, iocb);",
            "spin_lock_irqsave(&q->dpas_lock, flags);",
            "spin_unlock_irqrestore(&q->dpas_lock, flags);",
        ),
        "submit helper common path",
    )
    require_in_order(
        helper_c,
        (
            "case DPAS_MODE_INT:",
            "iocb->ki_flags &= ~IOCB_HIPRI;",
            "bio_clear_polled(bio);",
            "q->dpas_int_cnt++;",
            "if (q->dpas_int_cnt >= q->switch_param7)",
            "q->dpas_mode = DPAS_MODE_OL;",
            "q->dpas_ol_cnt = 0;",
            "q->dpas_qd_sum = 0;",
            "q->dpas_tf = 0;",
            "polled = false;",
        ),
        "INT submit gate and INT->OL transition",
    )
    for mode, counter in (
        ("DPAS_MODE_CP", "q->dpas_cp_cnt++;"),
        ("DPAS_MODE_PAS", "q->dpas_pas_cnt++;"),
        ("DPAS_MODE_OL", "q->dpas_ol_cnt++;"),
    ):
        require_in_order(
            helper_c,
            (f"case {mode}:", "bio_set_polled(bio, iocb);", counter),
            f"{mode} submit gate",
        )


def check_poll_mode_switching() -> None:
    blk_mq = read("block/blk-mq.c")
    switcher = find_braced_body(blk_mq, "static void blk_dpas_maybe_switch_mode(")
    switcher_c = compact(switcher)

    require_tokens(
        switcher,
        (
            "s64 avg_qd;",
            "lockdep_assert_held(&q->dpas_lock);",
            "if (!q->switch_enabled)",
        ),
        "mode switch guard",
    )
    require_in_order(
        switcher_c,
        (
            "case DPAS_MODE_CP:",
            "if ((s64)q->dpas_cp_cnt >= q->switch_param6)",
            "q->dpas_mode = DPAS_MODE_PAS;",
            "q->dpas_pas_cnt = 0;",
            "q->dpas_qd_sum = 0;",
            "q->dpas_tf = 0;",
        ),
        "CP->PAS transition",
    )
    require_in_order(
        switcher_c,
        (
            "case DPAS_MODE_PAS:",
            "if ((s64)q->dpas_pas_cnt < q->switch_param5)",
            "avg_qd = (s64)q->dpas_qd_sum * 10 / q->dpas_pas_cnt;",
            "if ((s64)q->dpas_tf > q->switch_param1)",
            "q->dpas_mode = DPAS_MODE_OL;",
            "q->dpas_ol_cnt = 0;",
            "else if (q->switch_param4 > 0 && avg_qd == 10)",
            "q->dpas_mode = DPAS_MODE_CP;",
            "q->dpas_cp_cnt = 0;",
            "else",
            "q->dpas_pas_cnt = 0;",
            "q->dpas_qd_sum = 0;",
            "q->dpas_tf = 0;",
        ),
        "PAS transitions",
    )
    require_in_order(
        switcher_c,
        (
            "case DPAS_MODE_OL:",
            "if ((s64)q->dpas_ol_cnt < q->switch_param5)",
            "avg_qd = (s64)q->dpas_qd_sum * 10 / q->dpas_ol_cnt;",
            "if (avg_qd <= q->switch_param2)",
            "q->dpas_mode = DPAS_MODE_PAS;",
            "q->dpas_pas_cnt = 0;",
            "else if (avg_qd > q->switch_param3)",
            "q->dpas_mode = DPAS_MODE_INT;",
            "q->dpas_int_cnt = 0;",
            "else",
            "q->dpas_ol_cnt = 0;",
            "q->dpas_qd_sum = 0;",
            "q->dpas_tf = 0;",
        ),
        "OL transitions",
    )
    require_in_order(
        switcher_c,
        ("case DPAS_MODE_INT:", "break;"),
        "INT stays out of poll-time switching",
    )


def check_poll_path_integration() -> None:
    blk_mq = read("block/blk-mq.c")
    update_duration = find_braced_body(
        blk_mq, "static void blk_mq_poll_pas_update_duration("
    )
    sleep_body = find_braced_body(blk_mq, "static void blk_mq_poll_pas_sleep(")
    complete_body = find_braced_body(blk_mq, "static void blk_mq_poll_pas_complete(")

    require_in_order(
        compact(update_duration),
        (
            "if (stat->dur < q->d_init)",
            "stat->dur = q->d_init;",
            "if (q->switch_enabled)",
            "spin_lock_irqsave(&q->dpas_lock, lock_flags);",
            "q->dpas_tf++;",
            "spin_unlock_irqrestore(&q->dpas_lock, lock_flags);",
        ),
        "tf update when PAS duration clamps to d_init",
    )
    require_in_order(
        compact(sleep_body),
        (
            "if (q->switch_enabled && q->dpas_mode == DPAS_MODE_CP)",
            "spin_lock_irqsave(&q->dpas_lock, lock_flags);",
            "blk_dpas_maybe_switch_mode(q);",
            "spin_unlock_irqrestore(&q->dpas_lock, lock_flags);",
            "return;",
        ),
        "CP skips PAS sleep",
    )
    require_in_order(
        compact(sleep_body),
        (
            "if (q->switch_enabled)",
            "spin_lock_irqsave(&q->dpas_lock, lock_flags);",
            "q->dpas_qd++;",
            "q->dpas_qd_sum += q->dpas_qd;",
            "spin_unlock_irqrestore(&q->dpas_lock, lock_flags);",
            "blk_mq_poll_pas_update_duration(q, &stat[bucket]);",
            "out_qd:",
            "if (q->switch_enabled)",
            "if (q->dpas_qd)",
            "q->dpas_qd--;",
        ),
        "QD sample around PAS sleep",
    )
    require_in_order(
        compact(complete_body),
        (
            "stat[ctx->bucket].update_req = 1;",
            "if (q->switch_enabled)",
            "spin_lock_irqsave(&q->dpas_lock, lock_flags);",
            "blk_dpas_maybe_switch_mode(q);",
            "spin_unlock_irqrestore(&q->dpas_lock, lock_flags);",
        ),
        "completion triggers poll-time mode evaluation",
    )


def main() -> int:
    check_queue_state()
    check_queue_initialization()
    check_switch_enabled_sysfs()
    check_submit_helper()
    check_poll_mode_switching()
    check_poll_path_integration()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
