# Local live captions

While you hold the trigger on a local model, the Pill's caption line shows the
words so far. On release the finished text is produced exactly as before; the
live line is a preview, not the paste.

**Where:** Settings > Voice > Local models > "Show words while I speak (local
models)". Off by default.

**How:** closed speech segments are transcribed during the hold (X-405) and
shown as they finish; the open segment's last 8 seconds are decoded every
0.8 s by the already-loaded engine, and the cadence stretches to twice the
decode time on a slower machine so the preview never takes the CPU the
dictation needs. Nothing leaves the machine (`tests/test_local_live.py`
proves the module opens no socket). The release path is the same bytes with
the toggle on or off; the test proves the final text is byte-equal.

**Measured on the founder's i7-8700 + RTX 3090 (2026-09-03,
`scripts/measure_local_live_latency.py`, an 11.7 s synthetic speech clip,
the last 8 s window, median of ten warm decodes):**

| Path | 8 s window decode | Tail latency (0.8 s cadence + decode) |
|---|---|---|
| GPU (DirectML, RTX 3090) | 0.42 s (0.38 to 0.48) | about 1.2 s |
| CPU (int8, six cores) | 0.38 s (0.34 to 0.43) | about 1.2 s |

The CPU number surprised us: the earlier 18.5 s for a 66 s take was one long
call under the utterance cap, not a per-window cost. So the first beta is not
GPU-only. A two-core laptop will be slower; the adaptive cadence is its
protection, and the number for such a machine has not been measured.

Ships with 0.4.129-beta (X-416). Plan: `docs/superpowers/plans/2026-09-03-local-live-captions.md`.
