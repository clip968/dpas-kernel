/* SPDX-License-Identifier: GPL-2.0 */
#ifndef BLK_DPAS_H
#define BLK_DPAS_H

#include <linux/percpu.h>
#include <linux/types.h>

struct request_queue;

/*
 * Part 4에서는 PAS 범위를 일부러 작게 유지한다. 읽기 크기 bucket 8개와
 * 쓰기 크기 bucket 8개만 둔다. 정확한 bucket 매핑은 이 헤더가 아니라
 * poll helper 쪽에 둔다.
 */
#define DPAS_NR_BUCKETS		16

/*
 * bucket별 PAS 학습 상태.
 *
 * duration_ns는 이 bucket에서 현재 사용할 sleep-before-poll 시간이다.
 * adjust_ppm/up_ppm/dn_ppm은 kernel에서 쓰기 어려운 floating point 대신
 * ppm(parts per million) fixed-point 값으로 표현한다.
 */
struct pas_bucket {
	u64 duration_ns;
	u32 adjust_ppm;
	u32 up_ppm;
	u32 dn_ppm;

	/* PAS hook이 실제로 동작하는지 확인하기 위한 debug counter. */
	u64 sleep_count;
	u64 under_count;
	u64 over_count;

	/* 나중에 같은 bucket update에 여러 result가 중복 반영되는 것을 막는다. */
	u64 generation;
};

/*
 * CPU별 PAS 상태.
 *
 * polling path에서 하나의 공유 counter를 뜨겁게 만들지 않기 위해 per-CPU로
 * 둔다. 초기 FIO smoke test에서 hook 진입 여부를 보기에도 충분하다.
 */
struct dpas_cpu_state {
	struct pas_bucket buckets[DPAS_NR_BUCKETS];
	u64 poll_entry_count;
	u64 skip_count;
};

/*
 * request_queue별 DPAS/PAS 상태.
 *
 * request_queue에는 이 구조체를 가리키는 pointer 하나만 둔다. 이렇게 해야
 * PAS field가 block layer 전체에 흩어지지 않고, CONFIG_DPAS를 끄거나
 * 나중에 제거하기도 쉽다.
 */
struct dpas_queue {
	bool pas_enabled;
	u64 min_duration_ns;
	u64 max_duration_ns;
	struct dpas_cpu_state __percpu *cpu_state;
};

#ifdef CONFIG_DPAS
int blk_dpas_queue_init(struct request_queue *q);
void blk_dpas_queue_exit(struct request_queue *q);
void blk_dpas_poll_count(struct request_queue *q);
#else
static inline int blk_dpas_queue_init(struct request_queue *q)
{
	return 0;
}

static inline void blk_dpas_queue_exit(struct request_queue *q)
{
}

static inline void blk_dpas_poll_count(struct request_queue *q)
{
}
#endif

#endif /* BLK_DPAS_H */
