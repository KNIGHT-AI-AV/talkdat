# Talk DAT! STT Provider Framework

Talk DAT! now separates speech-to-text selection into a provider registry and runtime session adapters.

## Runtime Lanes

- `streaming`: microphone audio is sent while the user is actively holding or using hands-free mode. Deepgram uses this path today.
- `batch`: microphone audio is recorded locally first, then sent after the user releases or stops the session. This keeps hover/idle credit-safe and supports leaderboard models that do not expose a realtime API.
- `local`: microphone audio is recorded locally and transcribed on-device by onnx-asr or faster-whisper. No key, no network after the one-time model download.
- `external`: the model is visible in Settings for planning and public customization, but needs a dedicated adapter, signed cloud auth flow, SDK, or local runner before it can execute.

## Routing

Session routing is driven entirely by the registry's `api_kind` field, so adding a provider that reuses an existing protocol needs only a registry entry:

- `deepgram_stream` routes to the Deepgram live WebSocket session.
- `openai_batch` routes to the OpenAI-compatible `POST /v1/audio/transcriptions` adapter (OpenAI, Groq, xAI, Mistral, custom endpoints).
- `elevenlabs_batch`, `assemblyai_batch`, and `gemini_batch` route to their dedicated batch adapters.
- `local_batch` routes to the on-device engines in `knight_flow/local_stt.py` (onnx-asr for Parakeet/Canary/GigaAM, faster-whisper for the Whisper families). The selected model auto-downloads on first use and the pill reports download/load progress states.
- `external` raises a clear "adapter pending" error instead of failing mid-session.

Providers with `key_optional` set (custom OpenAI-compatible endpoints and local runners) skip the API key requirement. Batch HTTP requests retry transient failures (HTTP 408/429/5xx and network errors) with short exponential backoff before surfacing an error.

## Wired Adapters

- Deepgram live streaming: `deepgram_stream`
- OpenAI-compatible batch transcription: OpenAI, Groq, xAI, Mistral, and custom OpenAI-compatible endpoints
- ElevenLabs batch transcription
- AssemblyAI upload/transcript/poll batch transcription
- Google Gemini audio batch transcription

## Registered Provider Families

Verified against official provider docs on 2026-06-12.

- Deepgram: Nova-3 / Nova-2, Enhanced, Base, Whisper (Flux exists but needs the `/v2/listen` protocol)
- OpenAI: GPT-4o Transcribe, GPT-4o Mini Transcribe, GPT-4o Transcribe Diarize, Whisper-1
- ElevenLabs: Scribe v2 (Scribe v1 is removed 2026-07-09)
- xAI: Grok STT (`/v1/stt`, adapter pending)
- Groq: Whisper Large v3 and v3 Turbo
- Mistral: Voxtral Mini Transcribe 2 (`voxtral-mini-2602`) and Voxtral Small
- AssemblyAI: Universal-3 Pro, Universal-2, Universal
- Google Gemini (3.5 Flash, 3.1 Flash-Lite, deprecated 2.5 family) and Google Cloud Speech
- Microsoft Azure Speech, including MAI Transcribe 1 / 1.5 preview
- Amazon Transcribe (job-based, no public model IDs)
- Speechmatics
- Cohere Transcribe (`cohere-transcribe-03-2026`, open weights)
- Gladia: Solaria 1 and Solaria 3
- Rev AI
- NVIDIA open-weight ASR: Parakeet TDT 0.6B v3, Canary 1B v2, Canary Qwen 2.5B
- Alibaba Qwen3-ASR Flash and Qwen3-Omni Flash
- Custom OpenAI-compatible and local/open-weight runners

## Source Anchors

- Artificial Analysis STT benchmark: https://artificialanalysis.ai/speech-to-text/non-streaming
- Deepgram live streaming docs: https://developers.deepgram.com/docs/live-streaming-audio
- OpenAI transcription API: https://platform.openai.com/docs/api-reference/audio/createTranscription
- ElevenLabs speech-to-text API: https://elevenlabs.io/docs/api-reference/speech-to-text/convert
- AssemblyAI speech-to-text docs: https://www.assemblyai.com/docs/speech-to-text
- Google Gemini audio docs: https://ai.google.dev/gemini-api/docs/audio
- Groq speech-to-text docs: https://console.groq.com/docs/speech-to-text
- AWS Transcribe docs: https://docs.aws.amazon.com/transcribe/latest/dg/what-is-transcribe.html
- Azure Speech-to-text docs: https://learn.microsoft.com/azure/ai-services/speech-service/speech-to-text

## Distribution Safety

Provider keys are stored only in the user's Windows credential vault or hydrated
process memory. The private source registry contains non-secret provider names,
model IDs, capability flags, and documentation URLs; customer releases contain
no Knight or user credentials.
