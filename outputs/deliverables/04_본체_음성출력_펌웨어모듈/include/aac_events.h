/**
 * @file aac_events.h
 * @brief 버튼 누름 기록 링버퍼. 보호자 웹 "모든 버튼 기록"을 위해 통신이 끊겨도 보관했다가 회수(EVENTS_GET/ACK).
 */
#ifndef AAC_EVENTS_H
#define AAC_EVENTS_H
#include <stdint.h>
#ifndef AAC_EVENT_CAP
#define AAC_EVENT_CAP 128              /* 128 × 12B = 1.5KB RAM */
#endif
typedef struct { uint32_t unix_time; uint16_t vocab_id; uint8_t set_id; uint8_t button; uint32_t config_version; } aac_event_t;

void     aac_events_reset(void);
void     aac_events_push(const aac_event_t *e);   /* 가득 차면 가장 오래된 기록 삭제 후 dropped 증가 */
uint16_t aac_events_count(void);
uint16_t aac_events_dropped(void);
uint16_t aac_events_peek(aac_event_t *out, uint16_t max);   /* 오래된 순 */
uint16_t aac_events_drop(uint16_t n);                       /* 회수 확인된 n 개 삭제 */
#endif
