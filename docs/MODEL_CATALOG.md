# Current Speech Model Catalog

Verified: **2026-08-02**

This is Talk DAT!'s maintained research index, not a claim that every listed
model is bundled. **Works now** means a tested Talk DAT! adapter or packaged
Windows runtime exists. **Adapter pending** means the model is current and worth
tracking, but the app will not advertise it as runnable until its authentication,
request protocol, packaging, recovery behavior, and clean-PC tests pass.

The order is a best-first shortlist informed by current Artificial Analysis
streaming and non-streaming results, official model lifecycle documentation,
latency, language coverage, cost, and Talk DAT!'s short-form dictation workload.
It is not a universal rank: streaming and batch results are not interchangeable.

Benchmark references: [streaming](https://artificialanalysis.ai/speech-to-text/streaming)
and [non-streaming](https://artificialanalysis.ai/speech-to-text/non-streaming).

The links below point to provider-owned or model-owner documentation. Talk DAT!
does not copy entire third-party manuals into the repository because copied
documentation becomes stale and may be copyrighted.

## Cloud And Hosted Models (30)

| # | Model | Provider | Mode | Availability | Official docs |
| ---: | --- | --- | --- | --- | --- |
| 1 | Scribe v2 | ElevenLabs | batch | Works now | [Docs](https://elevenlabs.io/docs/overview/models) |
| 2 | Gemini 3.1 Pro Preview High | Google | batch | Adapter pending | [Docs](https://ai.google.dev/gemini-api/docs/audio) |
| 3 | Pulse Pro | Smallest.ai | batch | Works now | [Docs](https://docs.smallest.ai/waves/documentation/speech-to-text-pulse/overview) |
| 4 | Universal-3.5 Pro | AssemblyAI | realtime | Adapter pending | [Docs](https://www.assemblyai.com/docs/speech-to-text/streaming) |
| 5 | GPT-4o Transcribe | OpenAI | batch | Works now | [Docs](https://developers.openai.com/api/docs/models/gpt-4o-transcribe) |
| 6 | Voxtral Small | Mistral | batch | Adapter pending | [Docs](https://docs.mistral.ai/capabilities/audio_transcription/) |
| 7 | Solaria 3 | Gladia | batch | Adapter pending | [Docs](https://docs.gladia.io/chapters/pre-recorded-stt/getting-started) |
| 8 | MAI Transcribe 1.5 | Microsoft | batch | Adapter pending | [Docs](https://learn.microsoft.com/azure/ai-services/speech-service/) |
| 9 | Ink-2 Semantic Endpoints | Cartesia | realtime | Adapter pending | [Docs](https://docs.cartesia.ai/build-with-cartesia/stt/latest) |
| 10 | Scribe v2 Realtime | ElevenLabs | realtime | Adapter pending | [Docs](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/client-side-streaming) |
| 11 | Ink-2 External Endpoints | Cartesia | realtime | Adapter pending | [Docs](https://docs.cartesia.ai/api-reference/stt/turns/websocket) |
| 12 | Inworld STT 1 Realtime | Inworld | realtime | Adapter pending | [Docs](https://docs.inworld.ai/docs/tts-stt/stt) |
| 13 | STT Realtime v5 | Soniox | realtime | Adapter pending | [Docs](https://soniox.com/docs/stt/models) |
| 14 | Chirp 3 Streaming | Google Cloud | realtime | Adapter pending | [Docs](https://cloud.google.com/speech-to-text/v2/docs/chirp_3-model) |
| 15 | Azure Speech Realtime | Microsoft | realtime | Adapter pending | [Docs](https://learn.microsoft.com/azure/ai-services/speech-service/speech-to-text) |
| 16 | Flux General English | Deepgram | realtime | Adapter pending | [Docs](https://developers.deepgram.com/docs/flux/quickstart) |
| 17 | Nemotron 3 ASR 80 ms | NVIDIA | realtime | Adapter pending | [Docs](https://build.nvidia.com/nvidia/nemotron-speech-streaming-en-us) |
| 18 | Voxtral Mini Transcribe Realtime | Mistral | realtime | Adapter pending | [Docs](https://docs.mistral.ai/studio-api/audio/speech_to_text/realtime_transcription) |
| 19 | Realtime Enhanced | Speechmatics | realtime | Adapter pending | [Docs](https://docs.speechmatics.com/introduction) |
| 20 | Nova-3 Realtime | Deepgram | realtime | Works now | [Docs](https://developers.deepgram.com/docs/live-streaming-audio) |
| 21 | Pulse Realtime | Smallest.ai | realtime | Adapter pending | [Docs](https://docs.smallest.ai/waves/documentation/speech-to-text-pulse/quickstart) |
| 22 | Qwen3-ASR Flash Realtime | Alibaba | realtime | Adapter pending | [Docs](https://www.alibabacloud.com/help/en/model-studio/qwen-asr-api-reference) |
| 23 | Amazon Transcribe Streaming | AWS | realtime | Adapter pending | [Docs](https://docs.aws.amazon.com/transcribe/latest/dg/streaming.html) |
| 24 | GPT Realtime Whisper | OpenAI | realtime | Adapter pending | [Docs](https://developers.openai.com/api/docs/models/gpt-realtime-whisper) |
| 25 | Grok Speech to Text | xAI | batch | Works now | [Docs](https://docs.x.ai/developers/model-capabilities/audio/speech-to-text) |
| 26 | Universal-3 Pro | AssemblyAI | batch | Works now | [Docs](https://www.assemblyai.com/docs/speech-to-text/pre-recorded-audio) |
| 27 | Whisper Large v3 Turbo | Groq | batch | Works now | [Docs](https://console.groq.com/docs/speech-to-text) |
| 28 | Rev AI Streaming | Rev AI | realtime | Adapter pending | [Docs](https://docs.rev.ai/api/streaming/) |
| 29 | Cohere Transcribe 03-2026 | Cohere | batch | Adapter pending | [Docs](https://docs.cohere.com/docs/transcribe) |
| 30 | Gemini 3.6 Flash | Google | batch | Works now | [Docs](https://ai.google.dev/gemini-api/docs/audio) |

## Local And Open-Weight Models (30)

| # | Model | Provider | Mode | Availability | Official docs |
| ---: | --- | --- | --- | --- | --- |
| 1 | Qwen3-ASR 1.7B | Qwen | local | Adapter pending | [Docs](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) |
| 2 | Qwen3-ASR 0.6B | Qwen | local | Adapter pending | [Docs](https://huggingface.co/Qwen/Qwen3-ASR-0.6B) |
| 3 | Cohere Transcribe 03-2026 | Cohere | local | Adapter pending | [Docs](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026) |
| 4 | Granite 4.0 1B Speech | IBM | local | Adapter pending | [Docs](https://huggingface.co/ibm-granite/granite-4.0-1b-speech) |
| 5 | MOSS Transcribe Diarize | OpenMOSS | local | Adapter pending | [Docs](https://huggingface.co/OpenMOSS-Team/MOSS-Transcribe-Diarize) |
| 6 | Voxtral Mini 4B Realtime | Mistral | local | Adapter pending | [Docs](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602) |
| 7 | Nemotron 3.5 ASR Streaming 0.6B | NVIDIA | local | Adapter pending | [Docs](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b) |
| 8 | Nemotron Speech Streaming EN 0.6B | NVIDIA | local | Adapter pending | [Docs](https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b) |
| 9 | Parakeet TDT 0.6B v3 | NVIDIA | local | Works now | [Docs](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) |
| 10 | Parakeet TDT 0.6B v2 | NVIDIA | local | Works now | [Docs](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2) |
| 11 | Canary 1B v2 | NVIDIA | local | Works now | [Docs](https://huggingface.co/nvidia/canary-1b-v2) |
| 12 | Canary 180M Flash | NVIDIA | local | Works now | [Docs](https://huggingface.co/nvidia/canary-180m-flash) |
| 13 | Canary Qwen 2.5B | NVIDIA | local | Adapter pending | [Docs](https://huggingface.co/nvidia/canary-qwen-2.5b) |
| 14 | Whisper Large v3 Turbo | OpenAI | local | Works now | [Docs](https://huggingface.co/openai/whisper-large-v3-turbo) |
| 15 | Whisper Large v3 | OpenAI | local | Works now | [Docs](https://huggingface.co/openai/whisper-large-v3) |
| 16 | Distil-Whisper Large v3.5 | Distil-Whisper | local | Works now | [Docs](https://huggingface.co/distil-whisper/distil-large-v3.5) |
| 17 | Whisper Medium | OpenAI | local | Works now | [Docs](https://huggingface.co/openai/whisper-medium) |
| 18 | Whisper Medium English | OpenAI | local | Works now | [Docs](https://huggingface.co/openai/whisper-medium.en) |
| 19 | Whisper Small | OpenAI | local | Works now | [Docs](https://huggingface.co/openai/whisper-small) |
| 20 | Whisper Small English | OpenAI | local | Works now | [Docs](https://huggingface.co/openai/whisper-small.en) |
| 21 | Distil-Whisper Medium English | Distil-Whisper | local | Works now | [Docs](https://huggingface.co/distil-whisper/distil-medium.en) |
| 22 | Distil-Whisper Small English | Distil-Whisper | local | Works now | [Docs](https://huggingface.co/distil-whisper/distil-small.en) |
| 23 | Whisper Base | OpenAI | local | Works now | [Docs](https://huggingface.co/openai/whisper-base) |
| 24 | Whisper Base English | OpenAI | local | Works now | [Docs](https://huggingface.co/openai/whisper-base.en) |
| 25 | Whisper Tiny | OpenAI | local | Works now | [Docs](https://huggingface.co/openai/whisper-tiny) |
| 26 | Whisper Tiny English | OpenAI | local | Works now | [Docs](https://huggingface.co/openai/whisper-tiny.en) |
| 27 | GigaAM v3 | Sber | local | Works now | [Docs](https://github.com/salute-developers/GigaAM) |
| 28 | Fun-ASR MLT Nano | FunAudioLLM | local | Adapter pending | [Docs](https://huggingface.co/FunAudioLLM/Fun-ASR-MLT-Nano-2512) |
| 29 | FireRedASR2 LLM | FireRedTeam | local | Adapter pending | [Docs](https://huggingface.co/FireRedTeam/FireRedASR2-LLM) |
| 30 | SenseVoice Small | FunAudioLLM | local | Adapter pending | [Docs](https://huggingface.co/FunAudioLLM/SenseVoiceSmall) |

## Product Defaults

- **Local speech:** Parakeet TDT 0.6B v3. It is packaged through the tested
  ONNX runtime, works well on ordinary CPUs, and downloads once for offline use.
- **Local formatting:** Qwen3 1.7B through Ollama. On Talk DAT!'s exact
  meaning-preservation suite it was faster and safer than the locally tested
  Qwen3.5 2B and 4B models, so a newer release number did not earn the default.
- **Bring your own cloud:** Deepgram Nova-3 remains the mature low-latency live
  route. ElevenLabs Scribe v2 remains the leading managed batch-quality route.

## Lifecycle Rules

1. Retired model IDs are removed from the picker, not silently rerouted.
2. Advanced users can still type a custom model ID for compatible endpoints.
3. A catalog entry becomes `wired` only after request-level tests and a real
   Windows runtime or provider smoke test pass.
4. New local runtimes must preserve protected-audio recovery and meaning-safe
   formatting before becoming a default.
5. The catalog date must change whenever any model, status, or lifecycle claim
   changes.
