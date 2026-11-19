#ifndef MOCK_HAL_H
#define MOCK_HAL_H
#include <stdint.h>
#include <stddef.h>
#include "aac_player.h"
#define MOCK_FLASH_SIZE (2u * 1024u * 1024u)
extern uint8_t g_flash[]; extern int g_audio_running, g_amp_on, g_audio_starts, g_prime_on_start;
extern uint8_t g_led[4][3]; extern int g_evt_count[8]; extern uint16_t g_evt_last[8];
extern uint8_t g_tx[]; extern size_t g_tx_len;
void mock_reset(void);
#endif
