/**
 * @file aac_player.h
 * @brief 에이블톡 버튼 재생 엔진 (에이블톡 1차 기능 정리 1장).
 *
 *  - 버튼 4개, 세트 2개(일반·작업장). 작업장 시간표에 걸리는 시간에는 작업장 세트, 그 밖에는 일반 세트를 자동 선택
 *  - 누르면: 해당 버튼 색 불빛 5초 + 진동 + 문장 재생 + 누름 기록 저장. 평소 불빛은 꺼짐
 *  - 기기는 문장만 말함: "보호자에게 알렸어요" 같은 안내 음성 없음(2차 검토)
 *  - 버튼 4(도움 요청)는 다른 버튼 재생을 끊고 재생, 버튼 4 재생 중 다른 버튼은 기록·불빛만(재생 안 함)
 *  - 통신·상위 계층과 무관하게 nRF52832 단독 동작
 */
#ifndef AAC_PLAYER_H
#define AAC_PLAYER_H
#include "aac_pkg.h"

#ifndef AAC_LED_MS
#define AAC_LED_MS      5000u
#endif
#ifndef AAC_VIBRATE_MS
#define AAC_VIBRATE_MS  150u
#endif

typedef struct {
    uint32_t touch_us, first_audio_us, last_latency_us, max_latency_us;
    uint32_t presses, plays, preempted, ignored;
} aac_player_stats_t;

aac_err_t aac_player_init(uint32_t slot_base);
aac_err_t aac_player_reload(uint32_t slot_base);
aac_err_t aac_player_on_button(uint8_t button);    /* 0~3, 버튼 입력 처리부(디바운스 후)에서 호출 */
aac_err_t aac_player_play_vocab(uint16_t vocab_id);/* 시험·점검용 직접 재생 */
void      aac_player_stop(void);
void      aac_player_tick(void);                   /* 50~100ms 주기 호출: 불빛 5초 소등, 세트 전환 감지 */
void      aac_player_set_tz(int16_t tz_offset_min);/* 기본 +540(한국) */
int16_t   aac_player_tz(void);
uint8_t   aac_player_current_set(void);
int       aac_player_is_playing(void);
uint16_t  aac_player_current(void);
size_t    aac_player_fill(int16_t *out, size_t n); /* 오디오 콜백: 0 이면 재생 끝 */
const aac_pkg_t *aac_player_pkg(void);
const aac_player_stats_t *aac_player_stats(void);
#endif
