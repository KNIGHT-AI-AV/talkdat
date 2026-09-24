from __future__ import annotations

from . import mac_support

from dataclasses import dataclass, field
from typing import Any

from . import platform_copy
from .licensing import DEFAULT_COMMERCE_API_URL
from .local_stt import LOCAL_MODELS
from .model_quality import quality_line


@dataclass(frozen=True)
class STTModel:
    id: str
    label: str
    mode: str
    variants: tuple[str, ...] = ("default",)
    notes: str = ""
    open_weights: bool = False


@dataclass(frozen=True)
class STTProvider:
    id: str
    label: str
    api_kind: str
    env_key: str
    docs_url: str
    login_url: str = ""
    api_keys_url: str = ""
    key_label: str = "API key"
    key_optional: bool = False
    # What the vendor sells. NOT what Talk DAT! does with it -- eleven providers
    # set this and exactly one of them streams through this app. Use
    # `streams_in_app` for anything a user will see or feel.
    supports_streaming: bool = False
    supports_batch: bool = True
    models: tuple[STTModel, ...] = field(default_factory=tuple)
    api_base: str = ""
    notes: str = ""

    @property
    def streams_in_app(self) -> bool:
        """Whether text arrives while you speak rather than after you stop.

        This is the single largest difference in felt speed in the product and
        nothing surfaced it. Measured on one machine, 5s of speech:

            Deepgram (streaming)   119-413ms after release
            OpenRouter (batch)     1371ms after release
            bundled local (batch)  938-1647ms, plus 7.9s on the first call

        A streaming provider has already transcribed most of the audio by the
        time the key comes up, so the wait is a settle rather than a round
        trip. A batch provider cannot start until the recording ends, so its
        entire cost is paid where the person is watching.

        Derived from api_kind rather than declared, because the declared field
        drifted from the truth for ten of the eleven providers that set it, and
        a hand-maintained duplicate of something already knowable is only ever
        one edit from being wrong again.
        """
        return "stream" in self.api_kind

    @property
    def delivery_note(self) -> str:
        """One line for the settings picker, where the choice is actually made."""
        if self.api_kind == "external":
            return "Not available in this build"
        if self.streams_in_app:
            return "Text appears as you speak"
        if self.api_kind == "local_batch":
            return f"Runs on {platform_copy.THIS_COMPUTER}; waits for the recording to finish"
        return "Waits for a round trip after you stop"


PROVIDERS: tuple[STTProvider, ...] = (
    STTProvider(
        id="openrouter",
        label="OpenRouter",
        # OpenRouter accepts OpenAI-style multipart on /v1/audio/transcriptions
        # and answers with {"text": ...}, so the existing OpenAI adapter carries
        # it unchanged. api_base deliberately stops at /api: the adapter appends
        # /v1/audio/transcriptions, and storing the documented base verbatim
        # would compose a doubled /v1/v1/ path.
        api_kind="openai_batch",
        env_key="OPENROUTER_API_KEY",
        docs_url="https://openrouter.ai/docs/guides/overview/multimodal/stt",
        login_url="https://openrouter.ai/",
        api_keys_url="https://openrouter.ai/settings/keys",
        # 2026-09-22: the key is the person's own and it is REQUIRED. It was
        # optional while paid subscribers were served by our backend key;
        # there is no backend key and no paid tier, and "optional" also
        # disabled the key box in Settings, so nobody could type one.
        key_label="OpenRouter API key",
        # OpenRouter's transcription endpoint documents no streaming. Talk DAT!
        # is press-and-hold-then-release, so the audio is already complete when
        # transcription starts and batch is the correct shape anyway.
        supports_streaming=False,
        supports_batch=True,
        api_base="https://openrouter.ai/api",
        models=(
            # Ranking and speed figures below are Artificial Analysis AA-WER and
            # speed-factor measurements, read 2026-08-04. The free local default
            # (Parakeet TDT 0.6B v3) measures 4.5% AA-WER, which is the bar any
            # paid cloud model has to clear to be worth selling.
            STTModel(
                "microsoft/mai-transcribe-1.5",
                "MAI-Transcribe 1.5 (most accurate)",
                "batch",
                notes=(
                    "2.4% AA-WER at 190x real time - roughly half the errors of the free "
                    "local default. This is the model the paid tier is actually sold on."
                ),
            ),
            STTModel(
                "x-ai/grok-stt-1.0",
                "Grok STT 1.0 (best value)",
                "batch",
                notes=(
                    "4.0% AA-WER at 225x real time, and the cheapest strong model here. "
                    "The metered default."
                ),
            ),
            STTModel(
                "deepgram/nova-3",
                "Nova-3 (fastest)",
                "batch",
                notes=(
                    "505x real time, the fastest in the catalogue, but 5.2% AA-WER - "
                    "measurably worse than the free local default. Offer it for speed, "
                    "never for accuracy."
                ),
            ),
            STTModel(
                "qwen/qwen3-asr-flash-2026-02-10",
                "Qwen3 ASR Flash (cheapest)",
                "batch",
                notes="Lowest per-second price in the catalogue.",
            ),
            STTModel(
                "nvidia/parakeet-tdt-0.6b-v3",
                "Parakeet TDT 0.6B v3 (same as local)",
                "batch",
                notes=(
                    "Identical weights to the default local model, hosted. Offered only for "
                    "machines too weak to run it, or when the local runtime is missing. "
                    "Never sell this as a cloud upgrade -- the free local route is the same model."
                ),
                open_weights=True,
            ),
            STTModel("mistralai/voxtral-mini-transcribe", "Voxtral Mini Transcribe", "batch", open_weights=True),
            STTModel("openai/gpt-4o-transcribe", "GPT-4o Transcribe", "batch"),
            STTModel("openai/gpt-4o-mini-transcribe", "GPT-4o Mini Transcribe", "batch"),
            STTModel("openai/whisper-large-v3", "Whisper large-v3", "batch", open_weights=True),
            STTModel("openai/whisper-large-v3-turbo", "Whisper large-v3 Turbo", "batch", open_weights=True),
            STTModel("openai/whisper-1", "Whisper v1", "batch"),
            STTModel("google/chirp-3", "Chirp 3", "batch"),
            STTModel("fish-audio/transcribe-1", "Fish Audio Transcribe 1", "batch"),
        ),
        notes=(
            "One key, every cloud model. Model ids are OpenRouter slugs verified against "
            "/api/v1/models?output_modalities=transcription on 2026-08-04; they are not "
            "guessable, so tests pin them. Uses your own OpenRouter key."
        ),
    ),
    STTProvider(
        id="deepgram",
        label="Deepgram",
        api_kind="deepgram_stream",
        env_key="DEEPGRAM_API_KEY",
        docs_url="https://developers.deepgram.com/docs/live-streaming-audio",
        login_url="https://console.deepgram.com/",
        api_keys_url="https://console.deepgram.com/",
        supports_streaming=True,
        supports_batch=True,
        api_base="https://api.deepgram.com",
        models=(
            STTModel("nova-3", "Nova-3", "streaming", ("streaming",)),
            STTModel("nova-3-general", "Nova-3 General", "streaming", ("streaming",)),
            STTModel("nova-3-medical", "Nova-3 Medical", "streaming", ("streaming",)),
        ),
        notes="Current Nova-3 choices only. Flux needs the /v2/listen protocol and stays cataloged as adapter pending.",
    ),
    STTProvider(
        id="openai",
        label="OpenAI",
        api_kind="openai_batch",
        env_key="OPENAI_API_KEY",
        docs_url="https://platform.openai.com/docs/api-reference/audio/createTranscription",
        login_url="https://platform.openai.com/login",
        api_keys_url="https://platform.openai.com/api-keys",
        api_base="https://api.openai.com",
        models=(
            STTModel("gpt-4o-transcribe", "GPT-4o Transcribe", "batch", ("json", "text")),
            STTModel("gpt-4o-mini-transcribe", "GPT-4o Mini Transcribe", "batch", ("json", "text")),
            STTModel("gpt-4o-transcribe-diarize", "GPT-4o Transcribe Diarize", "batch", ("diarized_json", "json")),
        ),
    ),
    STTProvider(
        id="elevenlabs",
        label="ElevenLabs",
        api_kind="elevenlabs_batch",
        env_key="ELEVENLABS_API_KEY",
        docs_url="https://elevenlabs.io/docs/api-reference/speech-to-text/convert",
        login_url="https://elevenlabs.io/app/sign-in",
        api_keys_url="https://elevenlabs.io/app/developers/api-keys",
        key_label="ElevenLabs API key",
        api_base="https://api.elevenlabs.io",
        models=(
            STTModel("scribe_v2", "Scribe v2", "batch", ("default", "diarize", "tag-audio-events")),
        ),
    ),
    STTProvider(
        id="xai",
        label="xAI",
        api_kind="xai_batch",
        env_key="XAI_API_KEY",
        docs_url="https://docs.x.ai/developers/model-capabilities/audio/speech-to-text",
        login_url="https://console.x.ai/",
        api_keys_url="https://console.x.ai/",
        api_base="https://api.x.ai",
        models=(
            STTModel("grok-transcribe", "Grok STT", "batch", ("default", "diarize")),
        ),
        notes="Uses xAI's dedicated POST /v1/stt multipart endpoint with formatting enabled.",
    ),
    STTProvider(
        id="groq",
        label="Groq",
        api_kind="openai_batch",
        env_key="GROQ_API_KEY",
        docs_url="https://console.groq.com/docs/speech-to-text",
        login_url="https://console.groq.com/login",
        api_keys_url="https://console.groq.com/keys",
        api_base="https://api.groq.com/openai",
        models=(
            STTModel("whisper-large-v3", "Whisper Large v3", "batch", ("json", "verbose_json")),
            STTModel("whisper-large-v3-turbo", "Whisper Large v3 Turbo", "batch", ("json", "verbose_json")),
        ),
    ),
    STTProvider(
        id="mistral",
        label="Mistral",
        api_kind="openai_batch",
        env_key="MISTRAL_API_KEY",
        docs_url="https://docs.mistral.ai/capabilities/audio/",
        login_url="https://console.mistral.ai/",
        api_keys_url="https://console.mistral.ai/api-keys/",
        api_base="https://api.mistral.ai",
        models=(
            STTModel("voxtral-mini-2602", "Voxtral Mini Transcribe 2", "batch", ("json", "text")),
        ),
    ),
    STTProvider(
        id="assemblyai",
        label="AssemblyAI",
        api_kind="assemblyai_batch",
        env_key="ASSEMBLYAI_API_KEY",
        docs_url="https://www.assemblyai.com/docs/speech-to-text",
        login_url="https://www.assemblyai.com/dashboard/login",
        api_keys_url="https://www.assemblyai.com/dashboard/api-keys",
        supports_streaming=True,
        supports_batch=True,
        api_base="https://api.assemblyai.com",
        models=(
            STTModel("universal-3-pro", "Universal-3 Pro", "batch", ("default", "speaker-labels")),
        ),
    ),
    STTProvider(
        id="google_gemini",
        label="Google Gemini",
        api_kind="gemini_batch",
        env_key="GEMINI_API_KEY",
        docs_url="https://ai.google.dev/gemini-api/docs/audio",
        login_url="https://aistudio.google.com/",
        api_keys_url="https://aistudio.google.com/apikey",
        api_base="https://generativelanguage.googleapis.com",
        models=(
            STTModel("gemini-3.6-flash", "Gemini 3.6 Flash", "batch", ("default", "low-latency")),
            STTModel("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "batch", ("default", "low-latency")),
        ),
        notes="Current audio-capable Gemini choices only. Deprecated 2.x IDs are hidden from the picker.",
    ),
    STTProvider(
        id="smallest",
        label="Smallest.ai",
        api_kind="smallest_batch",
        env_key="SMALLEST_API_KEY",
        docs_url="https://docs.smallest.ai/waves/documentation/speech-to-text-pulse/quickstart",
        login_url="https://console.smallest.ai/",
        api_keys_url="https://console.smallest.ai/",
        key_label="Smallest.ai API key",
        supports_streaming=True,
        supports_batch=True,
        api_base="https://api.smallest.ai",
        models=(
            STTModel("pulse-pro", "Pulse Pro (English)", "batch", ("default",)),
            STTModel("pulse", "Pulse (Multilingual)", "batch", ("default", "diarize")),
        ),
        notes="Pulse Pro is English-only batch STT. Pulse supports multilingual batch and streaming.",
    ),
    STTProvider(
        id="soniox",
        label="Soniox",
        api_kind="soniox_batch",
        env_key="SONIOX_API_KEY",
        docs_url="https://soniox.com/docs/stt/async/async-transcription",
        login_url="https://console.soniox.com/",
        api_keys_url="https://console.soniox.com/",
        key_label="Soniox API key",
        supports_streaming=True,
        supports_batch=True,
        api_base="https://api.soniox.com",
        models=(
            STTModel("stt-async-v5", "STT Async v5", "batch", ("default", "diarize")),
        ),
        notes="Uploads a temporary local recording, waits for transcription, then deletes the Soniox job and file.",
    ),
    STTProvider(
        id="google_cloud",
        label="Google Cloud Speech",
        api_kind="external",
        env_key="GOOGLE_APPLICATION_CREDENTIALS",
        docs_url="https://cloud.google.com/speech-to-text/docs",
        login_url="https://console.cloud.google.com/",
        api_keys_url="https://console.cloud.google.com/apis/credentials",
        key_label="Service account path",
        supports_streaming=True,
        supports_batch=True,
        models=(
            STTModel("chirp_3", "Chirp 3", "streaming", ("default", "enhanced")),
        ),
        notes="Needs Google service-account auth, not a simple bearer key.",
    ),
    STTProvider(
        id="azure",
        label="Microsoft Azure Speech",
        api_kind="external",
        env_key="AZURE_SPEECH_KEY",
        docs_url="https://learn.microsoft.com/azure/ai-services/speech-service/speech-to-text",
        login_url="https://portal.azure.com/",
        api_keys_url="https://portal.azure.com/#view/Microsoft_Azure_ProjectOxford/CognitiveServicesHub/~/SpeechServices",
        key_label="Azure Speech key",
        supports_streaming=True,
        supports_batch=True,
        models=(
            STTModel("latest", "Speech to Text", "streaming", ("region-required", "custom-endpoint")),
            STTModel("mai-transcribe-1.5", "MAI Transcribe 1.5", "batch", ("preview",)),
        ),
        notes="Requires Azure region and usually SDK/service setup. MAI Transcribe runs via the LLM Speech API preview.",
    ),
    STTProvider(
        id="aws",
        label="Amazon Transcribe",
        api_kind="external",
        env_key="AWS_ACCESS_KEY_ID",
        docs_url="https://docs.aws.amazon.com/transcribe/latest/dg/what-is-transcribe.html",
        login_url="https://console.aws.amazon.com/",
        api_keys_url="https://console.aws.amazon.com/iam/home#/security_credentials",
        key_label="AWS access key",
        supports_streaming=True,
        supports_batch=True,
        models=(
            STTModel("transcribe", "Amazon Transcribe", "streaming", ("standard", "medical", "call-analytics")),
        ),
        notes="Job-based service without public model IDs. Requires AWS signed requests and region/secret configuration.",
    ),
    STTProvider(
        id="speechmatics",
        label="Speechmatics",
        api_kind="external",
        env_key="SPEECHMATICS_API_KEY",
        docs_url="https://docs.speechmatics.com/",
        login_url="https://portal.speechmatics.com/",
        api_keys_url="https://portal.speechmatics.com/manage-access/api-keys",
        supports_streaming=True,
        supports_batch=True,
        models=(
            STTModel("enhanced", "Enhanced", "batch", ("default", "diarization")),
            STTModel("standard", "Standard", "streaming", ("default",)),
        ),
    ),
    STTProvider(
        id="cohere",
        label="Cohere",
        api_kind="external",
        env_key="COHERE_API_KEY",
        docs_url="https://docs.cohere.com/v2/docs/transcribe",
        login_url="https://dashboard.cohere.com/welcome/login",
        api_keys_url="https://dashboard.cohere.com/api-keys",
        api_base="https://api.cohere.com",
        models=(
            STTModel(
                "cohere-transcribe-03-2026",
                "Cohere Transcribe",
                "batch",
                ("default",),
                open_weights=True,
            ),
        ),
        notes="Uses POST /v2/audio/transcriptions (not OpenAI-compatible). Adapter pending.",
    ),
    STTProvider(
        id="gladia",
        label="Gladia",
        api_kind="external",
        env_key="GLADIA_API_KEY",
        docs_url="https://docs.gladia.io/",
        login_url="https://app.gladia.io/signin",
        api_keys_url="https://app.gladia.io/",
        supports_streaming=True,
        supports_batch=True,
        models=(
            STTModel("solaria-3", "Solaria 3", "batch", ("default",), notes="Async only. EN/FR/DE/ES/IT."),
        ),
    ),
    STTProvider(
        id="rev_ai",
        label="Rev AI",
        api_kind="external",
        env_key="REVAI_API_KEY",
        docs_url="https://docs.rev.ai/",
        login_url="https://www.rev.ai/auth/login",
        api_keys_url="https://www.rev.ai/access_token",
        supports_streaming=True,
        supports_batch=True,
        models=(STTModel("rev-ai", "Rev AI", "batch", ("default",)),),
    ),
    STTProvider(
        id="nvidia",
        label="NVIDIA",
        api_kind="external",
        env_key="NVIDIA_API_KEY",
        docs_url="https://docs.nvidia.com/deeplearning/riva/user-guide/docs/asr/asr-overview.html",
        login_url="https://build.nvidia.com/",
        api_keys_url="https://build.nvidia.com/",
        supports_streaming=True,
        supports_batch=True,
        models=(
            STTModel("parakeet-tdt-0.6b-v3", "Parakeet TDT 0.6B v3", "batch", ("default",), open_weights=True),
            STTModel("canary-1b-v2", "Canary 1B v2", "batch", ("default",), open_weights=True),
            STTModel("canary-qwen-2.5b", "Canary Qwen 2.5B", "batch", ("default",), open_weights=True),
        ),
        notes="Usually runs via Riva/NIM or another NVIDIA-hosted endpoint.",
    ),
    STTProvider(
        id="alibaba",
        label="Alibaba",
        api_kind="external",
        env_key="DASHSCOPE_API_KEY",
        docs_url="https://www.alibabacloud.com/help/en/model-studio/qwen-asr-api-reference",
        login_url="https://account.alibabacloud.com/login/login.htm",
        api_keys_url="https://bailian.console.aliyun.com/?apiKey=1",
        models=(
            STTModel("qwen3-asr-flash", "Qwen3-ASR Flash", "batch", ("default",)),
            STTModel("qwen3-omni-flash", "Qwen3-Omni Flash", "batch", ("default",)),
        ),
    ),
    STTProvider(
        id="custom_openai",
        label="Custom OpenAI-Compatible",
        api_kind="openai_batch",
        env_key="CUSTOM_STT_API_KEY",
        docs_url="",
        key_label="Custom API key",
        key_optional=True,
        api_base="",
        supports_batch=True,
        models=(STTModel("custom-model", "custom-model", "batch", ("json", "text")),),
        notes="Set API base to a server that accepts POST /v1/audio/transcriptions.",
    ),
    STTProvider(
        id="local",
        label="Local / On-Device",
        api_kind="local_batch",
        env_key="",
        docs_url="https://github.com/istupakov/onnx-asr",
        key_label="No key needed",
        key_optional=True,
        supports_streaming=False,
        supports_batch=True,
        models=tuple(
            STTModel(
                local_model.id,
                local_model.label,
                "batch",
                ("auto",),
                notes=f"{local_model.languages}. ~{local_model.size_mb} MB download. {local_model.notes}".strip(),
                open_weights=True,
            )
            for local_model in LOCAL_MODELS
        ),
        notes=f"Runs fully on {platform_copy.THIS_COMPUTER}. Models download once into the TalkDat models folder; audio never leaves the machine.",
    ),
)


PROVIDER_BY_ID = {provider.id: provider for provider in PROVIDERS}

# X-224: ordered by MEASURED accuracy, best first, and nothing else.
#
# This list is the order of the bring-your-own-key dropdown, so whatever sits
# at the top reads as the recommendation whether or not anyone intended it.
# Deepgram used to sit there. Two things were wrong with that.
#
# Commercially it is not what this product is: the free local engine is the
# offering, and a BYOK list exists so somebody can bring ANY provider, not so
# one vendor can be showcased.
#
# Factually it was worse. Artificial Analysis measures Deepgram Nova-3 at 5.2%
# AA-WER, which is not only mid-table, it is worse than Talk DAT!'s own FREE
# local Parakeet default at 4.5%. Blog round-ups call it the accuracy leader
# and they are wrong; its real distinction is speed, at 505x real time. So the
# first thing a person saw in a list sorted by nothing was a paid provider that
# would transcribe less accurately than the model already on their disk.
#
# Order below is AA-WER, lowest first, re-read from
# https://artificialanalysis.ai/speech-to-text on 2026-08-20:
#
#   elevenlabs      Scribe v2              2.2%
#   smallest        Pulse Pro              2.4%
#   google_gemini   Gemini 3.1 Pro         2.8%
#   mistral         Voxtral Small          2.8%
#   openai          GPT Transcribe         3.3%
#   xai             Grok STT               4.0%
#   deepgram        Nova-3                 5.2%   (fast, not accurate)
#
# assemblyai, groq and soniox are not in AA's measured top set, so they sit
# after the measured ones rather than being given an invented rank.
#
# Azure, Gladia and Alibaba score well and are DELIBERATELY ABSENT: their
# registry entries are api_kind "external", meaning this app cannot actually
# talk to them. Listing a provider it cannot reach is the connector-that-does-
# not-connect failure, and a test refuses it. Adding them means implementing
# them first.
#
# RE-READ THE SOURCE before changing this. The numbers move, and the whole
# point of sorting by them is that the order is a measurement, not an opinion.
FLAGSHIP_CLOUD_PROVIDER_IDS: tuple[str, ...] = (
    "elevenlabs",
    "smallest",
    "google_gemini",
    "mistral",
    "openai",
    "xai",
    "assemblyai",
    "groq",
    "soniox",
    "deepgram",
)

# X-516: empty, and kept only so a stored config naming the managed
# service still resolves. selected_provider_id falls back to "local" for
# any id not in PROVIDER_BY_ID, so those installs heal on next launch.
MANAGED_CLOUD_PROVIDER_IDS: tuple[str, ...] = ()


def provider_is_ready(provider_id: str) -> bool:
    provider = PROVIDER_BY_ID.get(str(provider_id).strip())
    return provider is not None and provider.api_kind != "external"


def activation_provider_id(candidate_id: str, current_id: str) -> str:
    if provider_is_ready(candidate_id):
        return candidate_id
    if provider_is_ready(current_id):
        return current_id
    return "local"


def provider_labels() -> list[str]:
    return [provider.label for provider in PROVIDERS]


def flagship_cloud_provider_labels() -> list[str]:
    return [PROVIDER_BY_ID[provider_id].label for provider_id in FLAGSHIP_CLOUD_PROVIDER_IDS]


def provider_id_for_label(label: str) -> str:
    for provider in PROVIDERS:
        if provider.label == label or provider.id == label:
            return provider.id
    return "local"


def provider_label(provider_id: str) -> str:
    return PROVIDER_BY_ID.get(provider_id, PROVIDER_BY_ID["local"]).label


def models_for_provider(provider_id: str) -> tuple[STTModel, ...]:
    return PROVIDER_BY_ID.get(provider_id, PROVIDER_BY_ID["local"]).models


def model_labels(provider_id: str) -> list[str]:
    return [model.label for model in models_for_provider(provider_id)]


def model_for_id(provider_id: str, model_id: str | None) -> STTModel:
    models = models_for_provider(provider_id)
    for model in models:
        if model.id == model_id or model.label == model_id:
            return model
    if model_id and str(model_id).strip():
        return STTModel(str(model_id).strip(), str(model_id).strip(), models[0].mode, models[0].variants)
    return models[0]


def model_id_for_label(provider_id: str, label: str) -> str:
    for model in models_for_provider(provider_id):
        if model.label == label or model.id == label:
            return model.id
    clean = str(label).strip()
    return clean or models_for_provider(provider_id)[0].id


def model_label(provider_id: str, model_id: str | None) -> str:
    return model_for_id(provider_id, model_id).label


# X-480: two routes, because those are the two the product offers.
#
#   local  the machine. The default, and what Talk DAT! is for.
#   byok   the person's own key, their own account, their own provider.
#
# "cloud" was the managed middleman and it is gone. "auto" existed only to
# arbitrate between that middleman and a person's own key, so with one side
# removed it has nothing left to decide. A three-position switch on a
# two-choice product is how somebody lands on a route nobody meant them to
# have.
ROUTE_MODES = ("local", "byok")


def local_only(config: dict[str, Any]) -> bool:
    """X-465: is this install local-only? On by default.

    Read by the speech route, the formatter resolver and the door that lets
    text leave, so a single switch cannot be true in one of them and false
    in another -- which is exactly how his text ended up in the cloud while
    his speech stayed on the machine.
    """
    privacy = config.get("privacy", {})
    if not isinstance(privacy, dict):
        return True
    return bool(privacy.get("local_only", True))


def provider_key_is_set(config: dict[str, Any], provider_id: str) -> bool:
    """Has this person actually given us a key for that provider?

    The difference between a route that works and a route that cannot
    transcribe. A byok mode with no key is not a preference, it is a dead end.
    """
    providers = config.get("stt", {}).get("providers", {})
    if not isinstance(providers, dict):
        return False
    settings = providers.get(provider_id, {})
    if not isinstance(settings, dict):
        return False
    return bool(str(settings.get("api_key", "") or "").strip())


def byok_provider(config: dict[str, Any]) -> str:
    """The person's OWN provider, or "" if they have not set one up.

    Never the managed service, and never "local": this answers "whose key",
    and the answer has to be somebody's.
    """
    stt = config.get("stt", {})
    for field in ("cloud_provider", "provider"):
        candidate = str(stt.get(field, "") or "").strip()
        if (candidate in PROVIDER_BY_ID
                and candidate not in ("local", "talk_dat_cloud")
                and provider_key_is_set(config, candidate)):
            return candidate
    return ""


def route_mode(config: dict[str, Any]) -> str:
    """The switch: local or byok. Local is the default and the fallback.

    X-480 also migrates the three old positions, and does it conservatively,
    because a switch that silently relocates somebody is the failure this is
    supposed to prevent:

      * "auto" becomes LOCAL. It was the old default, so most installs are on
        it, and moving those people onto a keyed route without asking would be
        a surprise rather than a migration.
      * "cloud" becomes BYOK only if a usable key is actually configured.
        Otherwise local, because a keyless "cloud" now points at a managed
        service that no longer exists, and home beats nowhere.
    """
    raw = str(config.get("stt", {}).get("route_mode", "local") or "").strip().lower()
    if raw in ROUTE_MODES:
        return raw
    if raw == "cloud" and byok_provider(config):
        return "byok"
    return "local"


def cloud_leg_provider(config: dict[str, Any]) -> str:
    """Kept for callers that have not been moved to byok_provider yet.

    X-480: it used to fall back to the managed service for anyone who had
    never configured a route. There is no managed service to fall back to, so
    it answers "local" instead of naming something that cannot run.
    """
    return byok_provider(config) or "local"




def resolve_route(config: dict[str, Any], cloud_entitled: bool = False) -> str:
    """Which provider a session should actually use.

    Two answers now, and `cloud_entitled` no longer changes either of them: it
    gated the managed leg, and with no managed leg an account's entitlement
    has no say over which engine transcribes a person's voice. The parameter
    stays so existing callers keep working.
    """
    # X-465: local-only outranks the switch. The switch is a preference; this
    # is the promise the product makes on its own front page, and it wins even
    # over an explicit byok choice.
    if local_only(config):
        return "local"
    if route_mode(config) == "byok":
        # A byok route with no usable key cannot transcribe. Falling home is
        # the difference between a slower dictation and no dictation.
        return byok_provider(config) or "local"
    return "local"


def selected_provider_id(config: dict[str, Any]) -> str:
    stt = config.get("stt", {})
    provider_id = str(stt.get("provider", "local")).strip() or "local"
    if provider_id not in PROVIDER_BY_ID:
        return "local"
    return provider_id


def provider_settings(config: dict[str, Any], provider_id: str | None = None) -> dict[str, Any]:
    provider_id = provider_id or selected_provider_id(config)
    if provider_id not in PROVIDER_BY_ID:
        provider_id = "local"
    stt = config.setdefault("stt", {})
    providers = stt.setdefault("providers", {})
    settings = providers.setdefault(provider_id, {})
    if provider_id == "deepgram":
        deepgram = config.setdefault("deepgram", {})
        settings.setdefault("api_key", deepgram.get("api_key", ""))
        settings.setdefault("model", deepgram.get("model", "nova-3"))
        settings.setdefault("variant", "streaming")
    provider = PROVIDER_BY_ID.get(provider_id)
    if provider:
        settings.setdefault("model", provider.models[0].id)
        settings.setdefault("variant", provider.models[0].variants[0])
        settings.setdefault("api_base", provider.api_base)
        settings.setdefault("extra", {})
    return settings


def selected_model_id(config: dict[str, Any], provider_id: str | None = None) -> str:
    provider_id = provider_id or selected_provider_id(config)
    settings = provider_settings(config, provider_id)
    if provider_id == "deepgram":
        return str(settings.get("model") or config.get("deepgram", {}).get("model", "nova-3"))
    return str(settings.get("model") or models_for_provider(provider_id)[0].id)


def selected_variant(config: dict[str, Any], provider_id: str | None = None) -> str:
    provider_id = provider_id or selected_provider_id(config)
    model = model_for_id(provider_id, selected_model_id(config, provider_id))
    settings = provider_settings(config, provider_id)
    value = str(settings.get("variant") or model.variants[0])
    return value if value in model.variants else model.variants[0]


def provider_capability_summary(provider_id: str, model_id: str | None = None) -> str:
    provider = PROVIDER_BY_ID.get(provider_id, PROVIDER_BY_ID["local"])
    model = model_for_id(provider.id, model_id)
    caps = []
    # `streams_in_app`, not `supports_streaming`. The declared flag is a vendor
    # fact and eleven providers set it, while exactly one of them streams
    # through this app -- so the picker was telling someone choosing AssemblyAI
    # or Soniox that text would appear as they spoke, and then making them wait
    # for a full round trip. The felt difference is 119ms against 1371ms.
    if provider.streams_in_app:
        caps.append("streaming")
    elif provider.supports_batch or model.mode == "batch":
        caps.append("batch")
    if model.open_weights:
        caps.append("open weights")
    if provider.api_kind == "external":
        caps.append("adapter pending")
    summary = " / ".join(caps) or model.mode
    # Lead with the measured rating when there is one. Choosing between two
    # dozen models on name alone is guesswork, and the capability list says
    # nothing about whether a model is any good.
    rating = quality_line(model.id)
    # The delivery note goes last because it is the sentence people act on: it
    # is the difference between text landing as you finish and a second and a
    # half of nothing, and it was the one thing the picker never said.
    tail = f"   -   {provider.delivery_note}"
    return (f"{rating}   {summary}{tail}" if rating else f"{summary}{tail}")


def sync_legacy_deepgram(config: dict[str, Any]) -> None:
    settings = provider_settings(config, "deepgram")
    deepgram = config.setdefault("deepgram", {})
    if str(settings.get("api_key", "")).strip():
        deepgram["api_key"] = settings.get("api_key", "")
    if str(settings.get("model", "")).strip():
        deepgram["model"] = settings.get("model", "nova-3")
