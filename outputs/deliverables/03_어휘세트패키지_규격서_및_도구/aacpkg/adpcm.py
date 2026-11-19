"""IMA-ADPCM (4bit) 인코더/디코더 — 펌웨어 aac_adpcm.c 와 비트 단위로 동일한 알고리즘."""

INDEX_TABLE = [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8]
STEP_TABLE = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
    50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230,
    253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963,
    1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327,
    3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442,
    11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794,
    32767]


def _decode_nibble(nib, pred, idx):
    step = STEP_TABLE[idx]
    diff = step >> 3
    if nib & 4: diff += step
    if nib & 2: diff += step >> 1
    if nib & 1: diff += step >> 2
    pred = pred - diff if nib & 8 else pred + diff
    pred = max(-32768, min(32767, pred))
    idx = max(0, min(88, idx + INDEX_TABLE[nib]))
    return pred, idx


def encode(samples):
    """int16 시퀀스 → bytes. 클립 시작 시 predictor=0, index=0. 하위 니블이 먼저 오는 샘플."""
    pred, idx = 0, 0
    out = bytearray()
    cur = None
    for s in samples:
        step = STEP_TABLE[idx]
        diff = int(s) - pred
        nib = 0
        if diff < 0:
            nib = 8
            diff = -diff
        if diff >= step: nib |= 4; diff -= step
        if diff >= step >> 1: nib |= 2; diff -= step >> 1
        if diff >= step >> 2: nib |= 1
        pred, idx = _decode_nibble(nib, pred, idx)   # 디코더와 같은 상태를 유지
        if cur is None:
            cur = nib
        else:
            out.append(cur | (nib << 4))
            cur = None
    if cur is not None:
        out.append(cur)
    return bytes(out)


def decode(data, sample_count):
    pred, idx = 0, 0
    out = []
    for b in data:
        for nib in (b & 0x0F, b >> 4):
            if len(out) >= sample_count:
                return out
            pred, idx = _decode_nibble(nib, pred, idx)
            out.append(pred)
    return out
