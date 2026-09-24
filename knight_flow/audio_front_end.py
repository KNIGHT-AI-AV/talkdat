"""X-36: the always-on audio front-end. Whispering just works.

Mayowa's spec, verbatim intent: "there's no whisper mode it should just be
that good and have auto gain bring up the volume automatically on its own as
low latency as possible... same with compression... preset all of that
default." So this is not a mode and has no switch in the UI: every chunk of
microphone audio passes through here on its way to every engine, local or
cloud, and a 2am whisper arrives at the recognizer at conversational level.

Three stages, all per-chunk so latency is the chunk cadence and nothing more:

1. Pre-gain -- the user's existing manual gain_boost/quiet_mode settings,
   honoured as before. The adaptive stage sits AFTER it, so a hand-tuned
   setup keeps its character.
2. Adaptive gain -- tracks speech RMS toward a target. It rises quickly when
   real-but-quiet speech is present (that is the whisper case), falls twice
   as fast when the input turns loud (so a shout never pumps), and holds
   still through silence rather than amplifying room noise into the model.
3. Soft limiter -- anything the gain pushed near full scale is scaled back
   below clipping. Clipped audio transcribes worse than quiet audio; the
   limiter is what makes an aggressive gain ceiling safe.
"""

from __future__ import annotations

from .audio_input import pcm_rms_level

# The RMS a normal conversational voice lands at through a decent mic. The
# adaptive stage aims quiet speech here; it never pushes speech that already
# meets it.
# Raised from 0.055 (X-58, field report: 'it keeps mishearing me even
# though Wispr Flow is fine on the same mic') -- recognizers reward hot
# input, and Wispr runs its capture noticeably hotter. The limiter keeps
# the extra headroom safe.
TARGET_RMS = 0.085
# Below this the chunk is treated as silence: gain HOLDS instead of climbing,
# which is the difference between lifting a whisper and lifting the air
# conditioner. Matches likely_has_input_signal's floor.
SILENCE_RMS = 0.0018
MAX_ADAPTIVE_GAIN = 32.0
RISE = 0.30   # per-chunk approach toward a higher desired gain (whisper help)
FALL = 0.60   # per-chunk approach toward a lower one (never pump a shout)
LIMIT_PEAK = 30000  # soft ceiling, ~0.92 full scale


class AdaptiveFrontEnd:
    def __init__(self, *, pre_gain: float = 1.0, enabled: bool = True) -> None:
        self.pre_gain = max(0.1, min(16.0, float(pre_gain or 1.0)))
        self.enabled = bool(enabled)
        self.gain = 1.0

    def visual_level(self, raw_rms: float) -> float:
        """The Pill's meter, from the raw mic RMS of the chunk just processed.

        Two ways a meter can lie, and this splits them: metering POST-limiter
        audio pins a hot mic at full scale (the limiter flattens syllables);
        metering the RAW mic makes a quiet mic invisible (field regression:
        the voice wave vanished for exactly the people whose mics need the
        auto-gain). So: raw dynamics, scaled by the gain the engine actually
        received, with the limiter deliberately left out of the meter path.
        """
        boost = self.pre_gain * (self.gain if self.enabled else 1.0)
        return max(0.0, min(1.0, float(raw_rms) * boost))

    def process(self, pcm16: bytes) -> bytes:
        if not pcm16:
            return pcm16
        try:
            import numpy as np
        except Exception:
            from .audio_input import apply_gain

            return apply_gain(pcm16, self.pre_gain)

        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) * self.pre_gain
        if self.enabled:
            rms = pcm_rms_level(audio.clip(-32768, 32767).astype(np.int16).tobytes())
            if rms >= SILENCE_RMS:
                desired = max(1.0, min(MAX_ADAPTIVE_GAIN, TARGET_RMS / max(rms, 1e-5)))
                rate = RISE if desired > self.gain else FALL
                self.gain += (desired - self.gain) * rate
            audio = audio * self.gain
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > LIMIT_PEAK:
            audio = audio * (LIMIT_PEAK / peak)
        return audio.clip(-32768, 32767).astype(np.int16).tobytes()


def front_end_for(config: dict, base_gain: float) -> AdaptiveFrontEnd:
    """One constructor for every capture path, so the default staging lives
    in exactly one place. `audio.adaptive_gain: false` is the escape hatch
    for a rig where the mic's own hardware AGC fights ours -- an escape
    hatch, not a mode."""
    audio = config.get("audio", {}) if isinstance(config, dict) else {}
    return AdaptiveFrontEnd(
        pre_gain=base_gain,
        enabled=bool(audio.get("adaptive_gain", True)),
    )
