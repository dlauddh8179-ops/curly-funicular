/**
 * @file aac_hal.h
 * @brief AAC 음성출력 모듈이 요구하는 하드웨어 추상화(HAL). 발주기관 펌웨어(또는 port/zephyr)가 구현.
 */
#ifndef AAC_HAL_H
#define AAC_HAL_H
#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* 외장 플래시 (주소는 플래시 내부 절대 주소) */
int  aac_hal_flash_read(uint32_t addr, void *buf, size_t len);
int  aac_hal_flash_write(uint32_t addr, const void *buf, size_t len);
int  aac_hal_flash_erase(uint32_t addr, size_t len);          /* 섹터 단위 정렬 */

/* 활성 슬롯 등 메타데이터(전원이 꺼져도 유지: 내부 플래시/NVS) */
int  aac_hal_meta_read(void *buf, size_t len);
int  aac_hal_meta_write(const void *buf, size_t len);

/* 오디오 출력: start 후 HAL 이 버퍼가 필요할 때 aac_player_fill() 을 호출 */
int  aac_hal_audio_start(uint32_t sample_rate);
void aac_hal_audio_stop(void);
void aac_hal_amp_enable(int on);                              /* 앰프 전원(대기 시 OFF) */

/* LED: zone 0~3, rgb 0이면 소등 */
void aac_hal_led_set(uint8_t zone, uint8_t r, uint8_t g, uint8_t b);

/* 이벤트 통지(보호자 앱 전송 등은 발주기관 펌웨어가 처리) */
typedef enum { AAC_EVT_PLAY_START = 1, AAC_EVT_PLAY_END, AAC_EVT_EMERGENCY, AAC_EVT_SOS, AAC_EVT_PKG_UPDATED } aac_evt_t;
void aac_hal_event(aac_evt_t evt, uint16_t vocab_id);

/* 단조 증가 마이크로초 타이머(지연시간 로그용) */
uint32_t aac_hal_time_us(void);

/* 업로드 응답 송신(USB CDC 또는 BLE notify) */
void aac_hal_tx(const uint8_t *data, size_t len);

#ifdef __cplusplus
}
#endif
#endif
