#ifndef AAC_ADPCM_H
#define AAC_ADPCM_H
#include <stdint.h>
#include <stddef.h>
typedef struct { int32_t pred; int32_t index; } aac_adpcm_state_t;
static inline void aac_adpcm_reset(aac_adpcm_state_t *s) { s->pred = 0; s->index = 0; }
/** IMA-ADPCM 4bit 디코드. 바이트당 2샘플(하위 니블 먼저). 반환: 출력 샘플 수. */
size_t aac_adpcm_decode(aac_adpcm_state_t *s, const uint8_t *in, size_t in_bytes, int16_t *out, size_t max_out);
#endif
