/**
 * @file aac_player.h
 * @brief AAC 핵심문구 재생 엔진: 터치 → 음원 재생 + LED, 우선순위, 응급 이벤트.
 *
 * 우선순위 규칙
 *  - 응급(도움·통증)·시스템 안내는 일반 문구 재생 중에도 즉시 끊고 재생
 *  - 일반 문구는 응급/시스템 재생 중에는 무시(AAC_ERR_BUSY)
 *  - 같은 우선순위 이하가 아니면(>=) 최신 입력이 이김
 * 계단식 성능저하: 이 모듈은 통신·DX-M2 와 무관하게 nRF52832 단독 동작.
 */
#ifndef AAC_PLAYER_H
#define AAC_PLAYER_H
#include "aac_pkg.h"

typedef enum { AAC_TOUCH_TAP = 0, AAC_TOUCH_LONG = 1 } aac_touch_t;

typedef struct {
    uint32_t touch_us;      /* 마지막 터치 수신 시각 */
    uint32_t first_audio_us;/* 첫 오디오 버퍼 공급 시각 */
    uint32_t last_latency_us;
    uint32_t max_latency_us;
    uint32_t plays;
    uint32_t preempted;
    uint32_t ignored;
} aac_player_stats_t;

aac_err_t aac_player_init(uint32_t slot_base);             /* 패키지 적재(부팅 시) */
aac_err_t aac_player_reload(uint32_t slot_base);           /* 업로드 후 교체 */
aac_err_t aac_player_on_touch(uint8_t zone, aac_touch_t t);/* 발주기관 터치·손떨림 필터 출력 */
aac_err_t aac_player_play(uint16_t vocab_id);              /* 시스템 안내 등 직접 재생 */
void      aac_player_stop(void);
int       aac_player_is_playing(void);
uint16_t  aac_player_current(void);
/** HAL 오디오 콜백에서 호출: out 에 최대 n 샘플 채움. 반환 0 이면 재생 끝. */
size_t    aac_player_fill(int16_t *out, size_t n);
const aac_pkg_t *aac_player_pkg(void);
const aac_player_stats_t *aac_player_stats(void);
#endif
