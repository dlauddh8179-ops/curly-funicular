#include "aac_pkg.h"

uint32_t aac_crc32(uint32_t crc, const void *data, size_t len)
{
    const uint8_t *p = (const uint8_t *)data;
    crc = ~crc;
    while (len--) {
        crc ^= *p++;
        for (int k = 0; k < 8; k++)
            crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
    }
    return ~crc;
}

uint16_t aac_crc16_ccitt(uint16_t crc, const void *data, size_t len)
{
    const uint8_t *p = (const uint8_t *)data;
    while (len--) {
        crc ^= (uint16_t)(*p++) << 8;
        for (int k = 0; k < 8; k++)
            crc = (crc & 0x8000u) ? (uint16_t)((crc << 1) ^ 0x1021u) : (uint16_t)(crc << 1);
    }
    return crc;
}
