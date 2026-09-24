# Provider Support

Talk DAT! has a provider registry so users can choose a brand, model, mode/trim, API base, and key from Settings or first-run onboarding.

## Wired Adapters

These providers can currently run inside the app.

| Provider | Mode | Notes |
| --- | --- | --- |
| Talk DAT! Managed | Managed batch | Activated trial/Pro route using Scribe v2. Audio uploads only after release, duration is metered, and the protected local WAV remains available for recovery. No provider key is required. |
| Deepgram | Streaming | Best default for live push-to-talk. Uses Deepgram WebSocket streaming on `/v1/listen`. Flux models need the `/v2/listen` protocol and are not wired yet. |
| OpenAI | Batch | Records locally, then sends WAV audio after release. Includes current GPT-4o Transcribe, GPT-4o Mini Transcribe, and GPT-4o Transcribe Diarize choices. |
| Groq | Batch | Uses an OpenAI-compatible transcription endpoint with Whisper Large v3 and v3 Turbo. |
| Mistral | Batch | Uses an OpenAI-compatible transcription endpoint with Voxtral Mini Transcribe 2 (`voxtral-mini-2602`) choices. |
| Custom OpenAI-Compatible | Batch | Set API base to a server that accepts `POST /v1/audio/transcriptions`. |
| ElevenLabs | Batch | Uses the speech-to-text conversion endpoint. Only current Scribe v2 is offered. |
| AssemblyAI | Batch | Uploads audio, starts a transcript job with the current `speech_models` request field, then polls for completion. Universal-3 Pro is the tested batch model. |
| Google Gemini | Batch | Sends WAV audio as inline content to Gemini. Current Gemini 3.6 Flash and Gemini 3.5 Flash-Lite choices replace deprecated 2.x generations. |
| xAI | Batch | Uses the dedicated multipart `POST /v1/stt` endpoint with provider formatting and optional diarization. |
| Smallest.ai | Batch | Sends raw WAV bytes to Pulse Pro for English or Pulse for multilingual dictation. |
| Soniox | Batch | Uploads a temporary file, creates and polls a `stt-async-v5` job, fetches the transcript, and deletes the remote job and file. |
| Local / On-Device | Batch | No API key. Open-weight models run on this PC via onnx-asr (Parakeet, Canary, GigaAM) or faster-whisper (Whisper, Distil-Whisper). A local-first install prepares the active model in the background; Settings > Voice > Local Models manages and verifies downloads. |

## Current 30 + 30 Research Index

The complete dated shortlist of 30 cloud/hosted and 30 local/open-weight models,
with an official documentation link and honest integration status for every
entry, lives in [MODEL_CATALOG.md](MODEL_CATALOG.md). The active Settings picker
contains only choices with a working adapter. Newer research candidates are not
shown as runnable merely because a model card exists.

## Local / On-Device Models

Verified against current public STT ranking references, model cards, onnx-asr 0.11, and faster-whisper 1.2.1 on 2026-07-09. Models download once into `%APPDATA%\TalkDat\models` and audio never leaves the machine.

Current ranking checkpoint: Artificial Analysis lists newer Voxtral/Mistral and MAI Transcribe results near the top of the public STT accuracy-speed charts, and Mistral documents Voxtral Mini Transcribe V2 as a high-accuracy batch transcription API. Those are exposed in the provider/model registry where they are usable through cloud adapters or saved as planned provider choices. They are not the default local install because the Windows local lane must use a runtime that is already packaged, tested, and recoverable on ordinary PCs.

### Shipping Default

Talk DAT! ships new users on **Local / On-Device -> Parakeet TDT 0.6B v3**. The model weights are not embedded in the installer; the app downloads and verifies the selected model automatically in the background for local-first users. That keeps the installer practical while making later transcription fully offline. Parakeet is the practical default because it is open-weight, wired through the packaged Windows `onnx-asr` engine, multilingual across common European languages, and fast enough for desktop dictation. Some newer leaderboard entries may win on raw WER, but they stay out of the default until their runtime is stable in the packaged Windows app.

Recommended local picks:

- **Best default:** Parakeet TDT 0.6B v3.
- **English accuracy option:** Parakeet TDT 0.6B v2.
- **Higher-accuracy heavier option:** Canary 1B v2.
- **Broad multilingual fallback:** Whisper Large v3 Turbo.
- **Tiny/fast fallback:** Canary 180M Flash or Whisper Small.

Ranking/reference links:

- Artificial Analysis STT leaderboard: https://artificialanalysis.ai/speech-to-text/non-streaming#error-rate-tabs
- Mistral Voxtral Transcribe 2 docs: https://docs.mistral.ai/studio-api/audio/speech_to_text
- NVIDIA Parakeet TDT 0.6B v3 model card: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- Parakeet TDT 0.6B v3 ONNX runtime model: https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx
- NVIDIA Canary 1B v2 model card: https://huggingface.co/nvidia/canary-1b-v2
- OpenAI Whisper Large v3 Turbo model card: https://huggingface.co/openai/whisper-large-v3-turbo

| Model | Engine | Languages | Approx. download |
| --- | --- | --- | --- |
| Parakeet TDT 0.6B v3 (recommended default) | onnx-asr | 25 European languages, auto-detect | ~640 MB |
| Parakeet TDT 0.6B v2 | onnx-asr | English | ~640 MB |
| Canary 1B v2 | onnx-asr | 25 European languages | ~700 MB |
| Canary 180M Flash | onnx-asr | en, de, es, fr | ~150 MB |
| GigaAM v3 | onnx-asr | Russian | ~160 MB |
| Whisper Large v3 Turbo | faster-whisper | 99 languages | ~1.6 GB |
| Distil-Whisper Large v3.5 | faster-whisper | English | ~1.5 GB |
| Whisper Large v3 | faster-whisper | 99 languages | ~3.1 GB |
| Whisper Medium / Medium EN | faster-whisper | 99 languages / English | ~1.5 GB |
| Whisper Small / Small EN | faster-whisper | 99 languages / English | ~480 MB |
| Distil-Whisper Medium EN / Small EN | faster-whisper | English | ~750 / ~330 MB |
| Whisper Base / Base EN | faster-whisper | 99 languages / English | ~145 MB |
| Whisper Tiny / Tiny EN | faster-whisper | 99 languages / English | ~75 MB |

Parakeet TDT 0.6B v3 is the default because it has the best accuracy-per-speed on plain CPUs (real-time on ordinary desktops), the same reason Handy marks it recommended. Whisper Large v3 Turbo is the pick when you need broad multilingual coverage beyond European languages. Moonshine v2 streaming models are not included yet because no maintained Python runtime exists for them (Handy uses its own Rust engine).

Routing is registry-driven: each provider entry declares an `api_kind`, and the session layer dispatches to the matching adapter. Batch requests retry transient HTTP failures (408/429/5xx and network errors) with short exponential backoff.

Provider-specific advanced options are saved as JSON per provider and passed into wired adapters where supported:

- OpenAI-compatible providers: extra scalar fields are added to the multipart transcription request.
- ElevenLabs: extra scalar fields are added to the speech-to-text request.
- AssemblyAI: extra JSON fields are merged into the transcript job body.
- Gemini: `prompt` can override the default transcription prompt.
- xAI: scalar options are added before the file in its multipart request.
- Smallest.ai: scalar options become query parameters on the Pulse endpoint.
- Soniox: scalar options are merged into the async transcription job body.

## Roadmap catalog

These providers remain in the internal registry for planning, but the active
settings picker hides them until a dedicated authentication/request adapter is
tested. They cannot replace a working route.

- Google Cloud Speech
- Microsoft Azure Speech (including the MAI Transcribe preview models)
- Amazon Transcribe
- Speechmatics
- Cohere Transcribe (`POST /v2/audio/transcriptions`)
- Gladia (Solaria 1 and Solaria 3)
- Rev AI
- NVIDIA / Riva / NIM style ASR
- Alibaba / DashScope (Qwen3-ASR Flash, Qwen3-Omni Flash)

## Model Registry Freshness

Active model IDs and `knight_flow/model_catalog.py` were last verified against
official provider docs and current public ranking snapshots on 2026-08-02.
Notable lifecycle decisions:

- ElevenLabs `scribe_v1` is removed from the active picker; Scribe v2 is current.
- Google 2.x generations are removed from the active picker; Gemini 3.6 Flash and 3.5 Flash-Lite are current.
- Groq `distil-whisper-large-v3-en` is deprecated in favor of `whisper-large-v3-turbo`.
- AssemblyAI batch uses Universal-3 Pro and the current plural `speech_models` request field. Universal-3.5 Pro remains a realtime adapter target.
- Soniox v4 is retired; current catalog entries use v5.
- Deepgram legacy Base/Enhanced and routine Nova-2 variants are hidden; Nova-3 remains active and Flux is tracked until `/v2/listen` is wired.

The model picker accepts free-typed model IDs, so newly released models can be used before the registry is updated.

## API Key Storage

Keys are never stored in the repo. On Windows, user-entered keys are protected
for the current user in Windows Credential Manager. Non-secret provider
preferences are saved under:

```text
%APPDATA%\TalkDat\config.json
```

Users may also provide keys through environment variables such as
`DEEPGRAM_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `MISTRAL_API_KEY`,
`ELEVENLABS_API_KEY`, `ASSEMBLYAI_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`,
`SMALLEST_API_KEY`, and `SONIOX_API_KEY`.

Custom dictionary words, snippets, provider advanced options, transcript history, live drafts, and scratchpad tabs are also user-private local files under `%APPDATA%\TalkDat`. Public GitHub downloads start empty.

## Adding A Provider

1. Add or update the provider entry in `knight_flow/stt_registry.py`.
2. Add a session implementation in `knight_flow/stt_sessions.py`.
3. Map provider-specific request parameters into a small stable config shape.
4. Keep API keys out of logs and UI status snapshots.
5. Add a smoke test or manual checklist item for activation, no-speech timeout, and cancel.
