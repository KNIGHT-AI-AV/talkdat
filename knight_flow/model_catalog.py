"""Dated speech-model research catalog.

The product picker is intentionally smaller than this catalog. ``wired`` means
Talk DAT! has a tested request/runtime path today; ``adapter_pending`` means the
model is current and documented but must not be presented as runnable yet.
"""

from __future__ import annotations

from dataclasses import dataclass


MODEL_CATALOG_VERIFIED_ON = "2026-08-02"
MODEL_CATALOG_STATUSES = frozenset({"wired", "adapter_pending"})
MODEL_CATALOG_STATUS_LABELS = {
    "wired": "Ready in Talk DAT!",
    "adapter_pending": "Research candidate",
}

MODEL_GUIDE_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    ("Private on-device", "Parakeet TDT 0.6B v3", "Best verified CPU speed/accuracy balance in Talk DAT!"),
    ("Live BYOK", "Deepgram Nova-3", "Mature low-latency streaming route with trigger-gated capture."),
    
    ("Local cleanup", "Qwen3 1.7B", "Fastest meaning-safe formatter in the app's local benchmark."),
)


@dataclass(frozen=True)
class ModelCatalogEntry:
    id: str
    label: str
    provider: str
    mode: str
    docs_url: str
    status: str
    notes: str = ""


# Accuracy, latency, language coverage, and price vary by workload. This is a
# current best-first shortlist informed by Artificial Analysis streaming and
# non-streaming snapshots, then completed with relevant current provider models.
CLOUD_MODEL_CATALOG: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry("scribe_v2", "Scribe v2", "ElevenLabs", "batch", "https://elevenlabs.io/docs/overview/models", "wired", "Leading current dictation accuracy. Bring your own ElevenLabs key."),
    ModelCatalogEntry("gemini-3.1-pro-preview", "Gemini 3.1 Pro Preview High", "Google", "batch", "https://ai.google.dev/gemini-api/docs/audio", "adapter_pending", "High-ranked non-streaming audio model; preview lifecycle."),
    ModelCatalogEntry("pulse-pro", "Pulse Pro", "Smallest.ai", "batch", "https://docs.smallest.ai/waves/documentation/speech-to-text-pulse/overview", "wired", "High-accuracy English batch transcription."),
    ModelCatalogEntry("universal-3-5-pro", "Universal-3.5 Pro", "AssemblyAI", "realtime", "https://www.assemblyai.com/docs/speech-to-text/streaming", "adapter_pending", "Current realtime model; the app's tested AssemblyAI adapter is batch."),
    ModelCatalogEntry("gpt-4o-transcribe", "GPT-4o Transcribe", "OpenAI", "batch", "https://developers.openai.com/api/docs/models/gpt-4o-transcribe", "wired"),
    ModelCatalogEntry("voxtral-small-latest", "Voxtral Small", "Mistral", "batch", "https://docs.mistral.ai/capabilities/audio_transcription/", "adapter_pending", "Current larger Voxtral accuracy option."),
    ModelCatalogEntry("solaria-3", "Solaria 3", "Gladia", "batch", "https://docs.gladia.io/chapters/pre-recorded-stt/getting-started", "adapter_pending"),
    ModelCatalogEntry("mai-transcribe-1.5", "MAI Transcribe 1.5", "Microsoft", "batch", "https://learn.microsoft.com/azure/ai-services/speech-service/", "adapter_pending"),
    ModelCatalogEntry("ink-2-semantic", "Ink-2 Semantic Endpoints", "Cartesia", "realtime", "https://docs.cartesia.ai/build-with-cartesia/stt/latest", "adapter_pending", "Top current streaming accuracy in the referenced snapshot."),
    ModelCatalogEntry("scribe_v2_realtime", "Scribe v2 Realtime", "ElevenLabs", "realtime", "https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/client-side-streaming", "adapter_pending"),
    ModelCatalogEntry("ink-2-external", "Ink-2 External Endpoints", "Cartesia", "realtime", "https://docs.cartesia.ai/api-reference/stt/turns/websocket", "adapter_pending"),
    ModelCatalogEntry("inworld-stt-1", "Inworld STT 1 Realtime", "Inworld", "realtime", "https://docs.inworld.ai/docs/tts-stt/stt", "adapter_pending"),
    ModelCatalogEntry("stt-rt-v5", "STT Realtime v5", "Soniox", "realtime", "https://soniox.com/docs/stt/models", "adapter_pending", "Current Soniox realtime generation; v4 is retired."),
    ModelCatalogEntry("chirp_3", "Chirp 3 Streaming", "Google Cloud", "realtime", "https://cloud.google.com/speech-to-text/v2/docs/chirp_3-model", "adapter_pending"),
    ModelCatalogEntry("azure-speech-realtime", "Azure Speech Realtime", "Microsoft", "realtime", "https://learn.microsoft.com/azure/ai-services/speech-service/speech-to-text", "adapter_pending"),
    ModelCatalogEntry("flux-general-en", "Flux General English", "Deepgram", "realtime", "https://developers.deepgram.com/docs/flux/quickstart", "adapter_pending", "Very low finalization latency; requires Deepgram /v2/listen."),
    ModelCatalogEntry("nemotron-3-asr-80ms", "Nemotron 3 ASR 80 ms", "NVIDIA", "realtime", "https://build.nvidia.com/nvidia/nemotron-speech-streaming-en-us", "adapter_pending"),
    ModelCatalogEntry("voxtral-mini-transcribe-realtime-2602", "Voxtral Mini Transcribe Realtime", "Mistral", "realtime", "https://docs.mistral.ai/studio-api/audio/speech_to_text/realtime_transcription", "adapter_pending"),
    ModelCatalogEntry("enhanced", "Realtime Enhanced", "Speechmatics", "realtime", "https://docs.speechmatics.com/introduction", "adapter_pending"),
    ModelCatalogEntry("nova-3", "Nova-3 Realtime", "Deepgram", "realtime", "https://developers.deepgram.com/docs/live-streaming-audio", "wired", "Mature low-latency push-to-talk route."),
    ModelCatalogEntry("pulse", "Pulse Realtime", "Smallest.ai", "realtime", "https://docs.smallest.ai/waves/documentation/speech-to-text-pulse/quickstart", "adapter_pending"),
    ModelCatalogEntry("qwen3-asr-flash-realtime", "Qwen3-ASR Flash Realtime", "Alibaba", "realtime", "https://www.alibabacloud.com/help/en/model-studio/qwen-asr-api-reference", "adapter_pending"),
    ModelCatalogEntry("amazon-transcribe", "Amazon Transcribe Streaming", "AWS", "realtime", "https://docs.aws.amazon.com/transcribe/latest/dg/streaming.html", "adapter_pending"),
    ModelCatalogEntry("gpt-realtime-whisper", "GPT Realtime Whisper", "OpenAI", "realtime", "https://developers.openai.com/api/docs/models/gpt-realtime-whisper", "adapter_pending"),
    ModelCatalogEntry("grok-transcribe", "Grok Speech to Text", "xAI", "batch", "https://docs.x.ai/developers/model-capabilities/audio/speech-to-text", "wired"),
    ModelCatalogEntry("universal-3-pro", "Universal-3 Pro", "AssemblyAI", "batch", "https://www.assemblyai.com/docs/speech-to-text/pre-recorded-audio", "wired"),
    ModelCatalogEntry("whisper-large-v3-turbo", "Whisper Large v3 Turbo", "Groq", "batch", "https://console.groq.com/docs/speech-to-text", "wired"),
    ModelCatalogEntry("rev-ai", "Rev AI Streaming", "Rev AI", "realtime", "https://docs.rev.ai/api/streaming/", "adapter_pending"),
    ModelCatalogEntry("cohere-transcribe-03-2026", "Cohere Transcribe 03-2026", "Cohere", "batch", "https://docs.cohere.com/docs/transcribe", "adapter_pending"),
    ModelCatalogEntry("gemini-3.6-flash", "Gemini 3.6 Flash", "Google", "batch", "https://ai.google.dev/gemini-api/docs/audio", "wired", "Current general audio-capable Gemini fast model."),
)


# Only entries whose exact runtime IDs exist in local_stt.LOCAL_MODELS are
# marked wired. The newer candidates remain visible to maintainers without
# being offered as one-click downloads before packaging and clean-PC tests.
LOCAL_MODEL_CATALOG: tuple[ModelCatalogEntry, ...] = (
    # X-474: the Canary entries are "adapter_pending", not "wired". This
    # module defines wired as "a tested request/runtime path today" and shows
    # it to people as "Ready in Talk DAT!". Measured 2026-09-05, both raise on
    # every call, so neither word was true.
    ModelCatalogEntry("qwen3-asr-1.7b", "Qwen3-ASR 1.7B", "Qwen", "local", "https://huggingface.co/Qwen/Qwen3-ASR-1.7B", "adapter_pending"),
    ModelCatalogEntry("qwen3-asr-0.6b", "Qwen3-ASR 0.6B", "Qwen", "local", "https://huggingface.co/Qwen/Qwen3-ASR-0.6B", "adapter_pending"),
    ModelCatalogEntry("cohere-transcribe-03-2026", "Cohere Transcribe 03-2026", "Cohere", "local", "https://huggingface.co/CohereLabs/cohere-transcribe-03-2026", "adapter_pending"),
    ModelCatalogEntry("granite-4.0-1b-speech", "Granite 4.0 1B Speech", "IBM", "local", "https://huggingface.co/ibm-granite/granite-4.0-1b-speech", "adapter_pending"),
    ModelCatalogEntry("moss-transcribe-diarize", "MOSS Transcribe Diarize", "OpenMOSS", "local", "https://huggingface.co/OpenMOSS-Team/MOSS-Transcribe-Diarize", "adapter_pending"),
    ModelCatalogEntry("voxtral-mini-4b-realtime-2602", "Voxtral Mini 4B Realtime", "Mistral", "local", "https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602", "adapter_pending"),
    ModelCatalogEntry("nemotron-3.5-asr-streaming-0.6b", "Nemotron 3.5 ASR Streaming 0.6B", "NVIDIA", "local", "https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b", "adapter_pending"),
    ModelCatalogEntry("nemotron-speech-streaming-en-0.6b", "Nemotron Speech Streaming EN 0.6B", "NVIDIA", "local", "https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b", "adapter_pending"),
    ModelCatalogEntry("parakeet-tdt-0.6b-v3", "Parakeet TDT 0.6B v3", "NVIDIA", "local", "https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3", "wired", "Default packaged CPU route."),
    ModelCatalogEntry("parakeet-tdt-0.6b-v2", "Parakeet TDT 0.6B v2", "NVIDIA", "local", "https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2", "wired"),
    ModelCatalogEntry("canary-1b-v2", "Canary 1B v2", "NVIDIA", "local", "https://huggingface.co/nvidia/canary-1b-v2", "adapter_pending"),
    ModelCatalogEntry("canary-180m-flash", "Canary 180M Flash", "NVIDIA", "local", "https://huggingface.co/nvidia/canary-180m-flash", "adapter_pending"),
    ModelCatalogEntry("canary-qwen-2.5b", "Canary Qwen 2.5B", "NVIDIA", "local", "https://huggingface.co/nvidia/canary-qwen-2.5b", "adapter_pending"),
    ModelCatalogEntry("whisper-large-v3-turbo", "Whisper Large v3 Turbo", "OpenAI", "local", "https://huggingface.co/openai/whisper-large-v3-turbo", "wired"),
    ModelCatalogEntry("whisper-large-v3", "Whisper Large v3", "OpenAI", "local", "https://huggingface.co/openai/whisper-large-v3", "wired"),
    ModelCatalogEntry("distil-large-v3.5", "Distil-Whisper Large v3.5", "Distil-Whisper", "local", "https://huggingface.co/distil-whisper/distil-large-v3.5", "wired"),
    ModelCatalogEntry("whisper-medium", "Whisper Medium", "OpenAI", "local", "https://huggingface.co/openai/whisper-medium", "wired"),
    ModelCatalogEntry("whisper-medium.en", "Whisper Medium English", "OpenAI", "local", "https://huggingface.co/openai/whisper-medium.en", "wired"),
    ModelCatalogEntry("whisper-small", "Whisper Small", "OpenAI", "local", "https://huggingface.co/openai/whisper-small", "wired"),
    ModelCatalogEntry("whisper-small.en", "Whisper Small English", "OpenAI", "local", "https://huggingface.co/openai/whisper-small.en", "wired"),
    ModelCatalogEntry("distil-medium.en", "Distil-Whisper Medium English", "Distil-Whisper", "local", "https://huggingface.co/distil-whisper/distil-medium.en", "wired"),
    ModelCatalogEntry("distil-small.en", "Distil-Whisper Small English", "Distil-Whisper", "local", "https://huggingface.co/distil-whisper/distil-small.en", "wired"),
    ModelCatalogEntry("whisper-base", "Whisper Base", "OpenAI", "local", "https://huggingface.co/openai/whisper-base", "wired"),
    ModelCatalogEntry("whisper-base.en", "Whisper Base English", "OpenAI", "local", "https://huggingface.co/openai/whisper-base.en", "wired"),
    ModelCatalogEntry("whisper-tiny", "Whisper Tiny", "OpenAI", "local", "https://huggingface.co/openai/whisper-tiny", "wired"),
    ModelCatalogEntry("whisper-tiny.en", "Whisper Tiny English", "OpenAI", "local", "https://huggingface.co/openai/whisper-tiny.en", "wired"),
    ModelCatalogEntry("gigaam-v3-e2e-ctc", "GigaAM v3", "Sber", "local", "https://github.com/salute-developers/GigaAM", "wired"),
    ModelCatalogEntry("fun-asr-mlt-nano-2512", "Fun-ASR MLT Nano", "FunAudioLLM", "local", "https://huggingface.co/FunAudioLLM/Fun-ASR-MLT-Nano-2512", "adapter_pending"),
    ModelCatalogEntry("fireredasr2-llm", "FireRedASR2 LLM", "FireRedTeam", "local", "https://huggingface.co/FireRedTeam/FireRedASR2-LLM", "adapter_pending"),
    ModelCatalogEntry("sensevoice-small", "SenseVoice Small", "FunAudioLLM", "local", "https://huggingface.co/FunAudioLLM/SenseVoiceSmall", "adapter_pending"),
)


def catalog_entries(status: str | None = None) -> tuple[ModelCatalogEntry, ...]:
    entries = CLOUD_MODEL_CATALOG + LOCAL_MODEL_CATALOG
    if status is None:
        return entries
    return tuple(entry for entry in entries if entry.status == status)


def filtered_catalog_entries(
    *,
    location: str = "all",
    status: str = "all",
    query: str = "",
) -> tuple[ModelCatalogEntry, ...]:
    """Return stable, display-ready catalog rows without overstating support."""

    normalized_location = str(location or "all").strip().lower()
    if normalized_location == "cloud":
        entries = CLOUD_MODEL_CATALOG
    elif normalized_location == "local":
        entries = LOCAL_MODEL_CATALOG
    else:
        entries = CLOUD_MODEL_CATALOG + LOCAL_MODEL_CATALOG

    normalized_status = str(status or "all").strip().lower()
    if normalized_status in MODEL_CATALOG_STATUSES:
        entries = tuple(entry for entry in entries if entry.status == normalized_status)

    needle = str(query or "").strip().casefold()
    if not needle:
        return tuple(entries)
    return tuple(
        entry
        for entry in entries
        if needle
        in " ".join((entry.label, entry.provider, entry.mode, entry.notes, entry.id)).casefold()
    )
