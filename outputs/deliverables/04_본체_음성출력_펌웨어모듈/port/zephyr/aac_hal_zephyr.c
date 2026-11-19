/*
 * aac_hal_zephyr.c — nRF Connect SDK(Zephyr) 용 HAL 포팅 템플릿.
 * ※ 실기(nRF52832 시작품) 미검증. 핀/디바이스트리 이름은 발주기관 보드 정의에 맞춰 수정.
 *   - 외장 플래시: SPI NOR (devicetree: aac_flash 파티션)
 *   - 오디오: I2S → 외장 DAC/앰프(예: MAX98357A), 16kHz/16bit 모노
 *   - 메타데이터: NVS(settings) 사용
 */
#include <zephyr/kernel.h>
#include <zephyr/drivers/flash.h>
#include <zephyr/drivers/i2s.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/storage/flash_map.h>
#include <zephyr/fs/nvs.h>
#include "aac_hal.h"
#include "aac_player.h"

#define AAC_PART       FIXED_PARTITION_ID(aac_vocab_partition)
#define I2S_NODE       DT_NODELABEL(i2s0)
#define BLOCK_SAMPLES  256
#define BLOCK_BYTES    (BLOCK_SAMPLES * sizeof(int16_t))
#define BLOCK_COUNT    4

K_MEM_SLAB_DEFINE_STATIC(tx_slab, BLOCK_BYTES, BLOCK_COUNT, 4);
static const struct flash_area *fa;
static const struct device *i2s = DEVICE_DT_GET(I2S_NODE);
static const struct gpio_dt_spec amp_en = GPIO_DT_SPEC_GET(DT_NODELABEL(amp_enable), gpios);
static struct nvs_fs nvs;
static K_THREAD_STACK_DEFINE(audio_stack, 1024);
static struct k_thread audio_thread;
static K_SEM_DEFINE(audio_go, 0, 1);
static volatile bool audio_on;

int aac_hal_flash_read(uint32_t a, void *b, size_t n) { return flash_area_read(fa, a, b, n); }
int aac_hal_flash_write(uint32_t a, const void *b, size_t n) { return flash_area_write(fa, a, b, n); }
int aac_hal_flash_erase(uint32_t a, size_t n) { return flash_area_erase(fa, a, n); }
int aac_hal_meta_read(void *b, size_t n) { return nvs_read(&nvs, 1, b, n) == (ssize_t)n ? 0 : -1; }
int aac_hal_meta_write(const void *b, size_t n) { return nvs_write(&nvs, 1, b, n) >= 0 ? 0 : -1; }
void aac_hal_amp_enable(int on) { gpio_pin_set_dt(&amp_en, on); }
uint32_t aac_hal_time_us(void) { return (uint32_t)k_cyc_to_us_floor64(k_cycle_get_64()); }

/* 오디오 스레드: 버퍼를 채워 I2S 로 계속 공급, 재생이 끝나면 drain */
static void audio_fn(void *a, void *b, void *c)
{
    for (;;) {
        k_sem_take(&audio_go, K_FOREVER);
        bool started = false;
        while (audio_on) {
            void *blk;
            if (k_mem_slab_alloc(&tx_slab, &blk, K_MSEC(50)) != 0) continue;
            size_t n = aac_player_fill((int16_t *)blk, BLOCK_SAMPLES);
            if (n == 0) { k_mem_slab_free(&tx_slab, blk); break; }
            if (n < BLOCK_SAMPLES) memset((int16_t *)blk + n, 0, (BLOCK_SAMPLES - n) * 2);
            i2s_write(i2s, blk, BLOCK_BYTES);
            if (!started) { i2s_trigger(i2s, I2S_DIR_TX, I2S_TRIGGER_START); started = true; }
        }
        if (started) i2s_trigger(i2s, I2S_DIR_TX, I2S_TRIGGER_DRAIN);
    }
}

int aac_hal_audio_start(uint32_t sr)
{
    if (audio_on) return 0;            /* 클립 교체 시 스트림 유지 */
    struct i2s_config cfg = {.word_size = 16, .channels = 1, .format = I2S_FMT_DATA_FORMAT_I2S,
                             .options = I2S_OPT_BIT_CLK_MASTER | I2S_OPT_FRAME_CLK_MASTER, .frame_clk_freq = sr,
                             .mem_slab = &tx_slab, .block_size = BLOCK_BYTES, .timeout = 100};
    if (i2s_configure(i2s, I2S_DIR_TX, &cfg) != 0) return -1;
    audio_on = true;
    k_sem_give(&audio_go);
    return 0;
}
void aac_hal_audio_stop(void) { audio_on = false; }

/* 아래 3개는 발주기관 펌웨어의 LED·이벤트·통신 모듈에 연결 */
__weak void aac_hal_led_set(uint8_t z, uint8_t r, uint8_t g, uint8_t b) { ARG_UNUSED(z); ARG_UNUSED(r); ARG_UNUSED(g); ARG_UNUSED(b); }
__weak void aac_hal_event(aac_evt_t e, uint16_t v) { ARG_UNUSED(e); ARG_UNUSED(v); }
__weak void aac_hal_tx(const uint8_t *d, size_t n) { ARG_UNUSED(d); ARG_UNUSED(n); }

int aac_hal_zephyr_init(void)
{
    if (flash_area_open(AAC_PART, &fa) != 0) return -1;
    gpio_pin_configure_dt(&amp_en, GPIO_OUTPUT_INACTIVE);
    nvs.flash_device = FIXED_PARTITION_DEVICE(storage_partition);
    nvs.offset = FIXED_PARTITION_OFFSET(storage_partition);
    nvs.sector_size = 4096; nvs.sector_count = 2;
    if (nvs_mount(&nvs) != 0) return -1;
    k_thread_create(&audio_thread, audio_stack, K_THREAD_STACK_SIZEOF(audio_stack), audio_fn, NULL, NULL, NULL,
                    K_PRIO_COOP(5), 0, K_NO_WAIT);
    return 0;
}
