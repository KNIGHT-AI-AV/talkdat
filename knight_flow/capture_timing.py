from __future__ import annotations


PCM16_BYTES_PER_SAMPLE = 2


def pcm_duration_ms(byte_count: int, sample_rate: int, channels: int) -> float:
    bytes_per_second = max(1, int(sample_rate) * max(1, int(channels)) * PCM16_BYTES_PER_SAMPLE)
    return max(0, int(byte_count)) / bytes_per_second * 1000.0


def should_extend_min_capture(
    byte_count: int,
    sample_rate: int,
    channels: int,
    *,
    heard_voice: bool,
    min_capture_ms: int,
) -> bool:
    if not heard_voice or int(min_capture_ms) <= 0:
        return False
    return pcm_duration_ms(byte_count, sample_rate, channels) < int(min_capture_ms)
