// SPDX-License-Identifier: GPL-2.0

#include <linux/blkdev.h>
#include <linux/compiler.h>
#include <linux/cpumask.h>
#include <linux/gfp.h>
#include <linux/percpu.h>
#include <linux/preempt.h>
#include <linux/slab.h>

#include "blk-dpas.h"

#define DPAS_DEFAULT_MIN_DURATION_NS	100
#define DPAS_DEFAULT_MAX_DURATION_NS	200000
#define DPAS_DEFAULT_ADJUST_PPM		1000000
#define DPAS_DEFAULT_UP_PPM		10000
#define DPAS_DEFAULT_DN_PPM		100000

static void blk_dpas_init_cpu_state(struct dpas_cpu_state *state)
{
	int i;

	/* 처음 단계에서는 hook 진입 여부만 보기 위해 counter를 0으로 시작한다. */
	state->poll_entry_count = 0;
	state->skip_count = 0;

	for (i = 0; i < DPAS_NR_BUCKETS; i++) {
		struct pas_bucket *bucket = &state->buckets[i];

		/* sleep-before-poll은 아직 켜지 않는다. skeleton 단계에서는 0이다. */
		bucket->duration_ns = 0;
		bucket->adjust_ppm = DPAS_DEFAULT_ADJUST_PPM;
		bucket->up_ppm = DPAS_DEFAULT_UP_PPM;
		bucket->dn_ppm = DPAS_DEFAULT_DN_PPM;
		bucket->sleep_count = 0;
		bucket->under_count = 0;
		bucket->over_count = 0;
		bucket->generation = 0;
	}
}

int blk_dpas_queue_init(struct request_queue *q)
{
	struct dpas_queue *dpas;
	int cpu;

	/* queue마다 독립된 PAS 상태를 하나씩 둔다. */
	dpas = kzalloc_obj(*dpas);
	if (!dpas)
		return -ENOMEM;

	/* polling path에서 공유 counter 경합을 피하기 위해 CPU별 상태를 둔다. */
	dpas->cpu_state = alloc_percpu(struct dpas_cpu_state);
	if (!dpas->cpu_state) {
		kfree(dpas);
		return -ENOMEM;
	}

	/* 기본값은 항상 안전하게 disabled 상태다. */
	dpas->pas_enabled = false;
	dpas->min_duration_ns = DPAS_DEFAULT_MIN_DURATION_NS;
	dpas->max_duration_ns = DPAS_DEFAULT_MAX_DURATION_NS;

	for_each_possible_cpu(cpu) {
		blk_dpas_init_cpu_state(per_cpu_ptr(dpas->cpu_state, cpu));
	}

	q->dpas = dpas;
	return 0;
}

void blk_dpas_queue_exit(struct request_queue *q)
{
	struct dpas_queue *dpas = q->dpas;

	if (!dpas)
		return;

	/* queue 해제 중에는 q->dpas를 먼저 끊고 내부 메모리를 정리한다. */
	q->dpas = NULL;
	free_percpu(dpas->cpu_state);
	kfree(dpas);
}

void blk_dpas_poll_count(struct request_queue *q)
{
	struct dpas_queue *dpas = READ_ONCE(q->dpas);
	struct dpas_cpu_state *state;

	if (!dpas || !READ_ONCE(dpas->pas_enabled))
		return;

	/*
	 * 현재 단계에서는 sleep하지 않는다.
	 * pas_enabled=1일 때 bio_poll 경로에 들어왔는지만 센다.
	 */
	preempt_disable();
	state = this_cpu_ptr(dpas->cpu_state);
	state->poll_entry_count++;
	preempt_enable();
}
