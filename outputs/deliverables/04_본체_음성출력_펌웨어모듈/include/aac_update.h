/**
 * @file aac_update.h
 * @brief 어휘 세트 업로드 수신(USB CDC / BLE 공통 프레임) + A/B 슬롯 전환·롤백.
 */
#ifndef AAC_UPDATE_H
#define AAC_UPDATE_H
#include <stdint.h>
#include <stddef.h>

#ifndef AAC_SLOT_A_ADDR
#define AAC_SLOT_A_ADDR 0x000000u
#endif
#ifndef AAC_SLOT_B_ADDR
#define AAC_SLOT_B_ADDR 0x080000u
#endif
#ifndef AAC_SLOT_SIZE
#define AAC_SLOT_SIZE   0x080000u     /* 512KB × 2 (외장 플래시 1MB 이상): 녹음 6초 × 8개도 수용 */
#endif

int      aac_update_init(void);                 /* 메타데이터 읽고 활성 슬롯 적재 */
void     aac_update_rx(const uint8_t *data, size_t len); /* 수신 바이트 투입 */
uint32_t aac_update_active_slot_addr(void);
#endif
