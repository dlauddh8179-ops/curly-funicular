#include "aac_events.h"

static aac_event_t buf[AAC_EVENT_CAP];
static uint16_t head, count, dropped;

void aac_events_reset(void) { head = count = dropped = 0; }
uint16_t aac_events_count(void) { return count; }
uint16_t aac_events_dropped(void) { return dropped; }

void aac_events_push(const aac_event_t *e)
{
    if (count == AAC_EVENT_CAP) { head = (uint16_t)((head + 1) % AAC_EVENT_CAP); count--; dropped++; }
    buf[(head + count) % AAC_EVENT_CAP] = *e;
    count++;
}

uint16_t aac_events_peek(aac_event_t *out, uint16_t max)
{
    uint16_t n = max < count ? max : count;
    for (uint16_t i = 0; i < n; i++) out[i] = buf[(head + i) % AAC_EVENT_CAP];
    return n;
}

uint16_t aac_events_drop(uint16_t n)
{
    if (n > count) n = count;
    head = (uint16_t)((head + n) % AAC_EVENT_CAP);
    count = (uint16_t)(count - n);
    if (count == 0) dropped = 0;
    return n;
}
