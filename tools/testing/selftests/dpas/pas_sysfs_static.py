#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Static checks for simple 5.18-style PAS queue sysfs knobs."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]

SYSFS_KNOBS = (
    ("queue_pas_enabled", "pas_enabled", "pas_enabled"),
    ("queue_pas_adaptive_enabled", "pas_adaptive_enabled", "pas_adaptive_enabled"),
    ("queue_ehp_enabled", "ehp_enabled", "ehp_enabled"),
    ("queue_max_no_lock", "pas_max_no_lock", "max_no_lock"),
    ("queue_poll_threshold", "pas_poll_threshold", "poll_threshold"),
    ("queue_logging_enabled", "logging_enabled", "logging_enabled"),
    ("queue_d_init", "pas_d_init", "d_init"),
    ("queue_up_init", "pas_up_init", "up_init"),
    ("queue_dn_init", "pas_dn_init", "dn_init"),
    ("queue_heat_up", "pas_heat_up", "heat_up"),
    ("queue_cool_dn", "pas_cool_dn", "cool_dn"),
    ("queue_min_dn", "pas_min_dn", "min_dn"),
    ("queue_max_dn", "pas_max_dn", "max_dn"),
    ("queue_switch_param1", "switch_param1", "switch_param1"),
    ("queue_switch_param2", "switch_param2", "switch_param2"),
    ("queue_switch_param3", "switch_param3", "switch_param3"),
    ("queue_switch_param4", "switch_param4", "switch_param4"),
    ("queue_switch_param5", "switch_param5", "switch_param5"),
    ("queue_switch_param6", "switch_param6", "switch_param6"),
    ("queue_switch_param7", "switch_param7", "switch_param7"),
)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def initializer_body(source: str, name: str) -> str:
    match = re.search(
        rf"static const struct attribute \*const {name}\[\] = \{{", source
    )
    require(match is not None, f"{name} initializer not found")

    start = match.end()
    end = source.find("};", start)
    require(end != -1, f"{name} initializer terminator not found")
    return source[start:end]


def main() -> int:
    blk_sysfs = read("block/blk-sysfs.c")
    mq_attrs = initializer_body(blk_sysfs, "blk_mq_queue_attrs")

    require(
        "static bool queue_dpas_poll_capable(struct request_queue *q)" in blk_sysfs,
        "DPAS sysfs stores must reject queues without mq poll support",
    )

    for prefix, attr_name, field_name in SYSFS_KNOBS:
        require(
            f'QUEUE_RW_ENTRY({prefix}, "{attr_name}");' in blk_sysfs,
            f"missing sysfs entry for {attr_name}",
        )
        require(
            f"&{prefix}_entry.attr," in mq_attrs,
            f"{attr_name} must be registered as an mq queue attribute",
        )
        field_macro = re.search(
            rf"QUEUE_DPAS_(?:INT|U32|LL)_RW\({prefix}, {field_name},",
            blk_sysfs,
        )
        require(
            f"q->{field_name}" in blk_sysfs or field_macro is not None,
            f"{attr_name} must read or write q->{field_name}",
        )

    for token in (
        "static void queue_dpas_reinit_pas_stats(struct request_queue *q,",
        "for_each_possible_cpu(cpu)",
        "stat = per_cpu_ptr(q->pas_stat, cpu);",
        "queue_dpas_init_pas_stat(&stat[bucket_idx],",
        "queue_dpas_reinit_pas_stats(q, q->div);",
        "queue_dpas_reinit_pas_stats(q, q->div + q->up_init);",
    ):
        require(token in blk_sysfs, f"missing PAS stat reinit token: {token}")

    for attr_name in ("switch_enabled", "pas_exception", "switch_stat"):
        require(
            f'"{attr_name}"' not in blk_sysfs,
            f"{attr_name} sysfs must wait for its backing logic",
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
