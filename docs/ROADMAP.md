# Talk DAT! Feature Roadmap

Thirty features that are industry standard across the leading dictation products (Wispr Flow, superwhisper, MacWhisper, Dragon, Aqua Voice, Talon, VoiceInk, Handy). Last revised 2026-06-13.

**Status: all 30 items below shipped a first implementation on 2026-06-13.** Items marked *(beta)* are functional but young: wake word needs the optional `openwakeword` package, meeting mode's system-audio loopback depends on the PortAudio build and falls back to the microphone, and the browser extension is a load-unpacked developer build. Diarization ships as provider-side speaker labels (AssemblyAI/ElevenLabs/OpenAI diarize models) rather than a dedicated meeting view, and accessibility shipped reduced-motion + keyboard-reachable controls with high-contrast themes still to come.

Effort key: **S** = under a day, **M** = 1-3 days, **L** = a week-plus.

## Tier 1 - Core dictation power

1. **Per-app formatting profiles** (Wispr Flow "context awareness") - M
   Detect the foreground app (`GetForegroundWindow` + process name, already half-built in `overlay._foreground_is_fullscreen`). New `profiles` config section maps process names to cleanup level, tone, auto-enter, and language. Hook into `app.handle_dictation` before `process_dictation`.
2. **Voice editing commands** ("scratch that", "new line", "delete last sentence") - M
   Dragon-standard. Add a command grammar pass in `text_pipeline.process_dictation` that interprets trailing/inline phrases into edit ops against the live draft; backspace/retype via `paste.py`.
3. **BYOK LLM cleanup providers** (OpenAI, Anthropic, Gemini, Groq alongside Ollama) - M
   Extend `transforms.ollama` into `transforms.llm` with a provider registry mirroring `stt_registry` patterns; reuse `stt_sessions.http_request` retry stack. The tone/polish transforms instantly get much better.
4. **AI tone presets** (formal, friendly, concise, bullet) - S
   Ship four built-in transforms on top of item 3; surface as right-click pill menu entries and hotkeys (hotkey scaffolding already exists for polish/prompt_engineer/turn_to_list).
5. **Auto-learned vocabulary** (Wispr auto-learns names) - M
   Mine `history.db` for words the user re-corrected (diff original vs final) and window titles; queue suggestions in Settings > Dictionary with one-click accept into `dictionary.words` (which already feeds Deepgram keyterms).
6. **Multi-language auto-switch + per-language dictionaries** - M
   Parakeet v3 and Whisper already auto-detect; store detected language in history entries, add `dictionary.by_language`, and pick replacements per detected language in `text_pipeline`.
7. **GPU acceleration for local models** (DirectML/CUDA) - M
   Settings toggle that passes `providers=["DmlExecutionProvider"]` to `onnx_asr.load_model` and `device="cuda"` to `WhisperModel` when available; detect via `onnxruntime.get_available_providers()`. Extend `local_stt.ensure_loaded`.
8. **Wake word activation** ("Hey Talk Dat") - L *(shipped, beta)*
   openWakeWord ONNX models run on the existing onnxruntime dependency; low-power loop in a new `wake.py` feeding the existing `toggle_hands_free` callback. Strictly opt-in (always-on mic is a privacy posture change).
9. **Input device picker + live mic meter + noise suppression** - M
   `sounddevice.query_devices()` dropdown in Settings > Audio; device index plumbed into both session classes; optional RNNoise-style ONNX denoiser pass before STT.
10. **Whisper-quiet mode** (superwhisper/Wispr both ship this) - S
    Gain-boost stage in the audio callbacks with automatic clipping guard, toggled per-session via a modifier hotkey.

## Tier 2 - History, knowledge, and output

11. **Full-text history search UI** - S
    SQLite backend and `HistoryStore.search()` already exist; add a search box + result list to the History window, with backend auto-set to sqlite (FTS5 virtual table when corpus grows).
12. **Pinned transcripts + tags** - S
    `pinned`/`tags` columns on the history table (schema is additive), pin button in History, "paste pinned" hotkey.
13. **Analytics dashboard** (Wispr-style words/day, WPM, time saved, streaks) - M
    Aggregate from `history.db` (counts, durations from session timestamps); render as a glass Stats window with simple canvas charts. Zero new data collection.
14. **Export: Markdown / TXT / DOCX / SRT** - S
    Export menu in History; MD/TXT/SRT are stdlib-only, DOCX via `python-docx` optional import.
15. **Encrypted settings backup/sync** - L
    Optional, off by default: encrypt `config.json` + dictionary + snippets with a user passphrase (libsodium/`cryptography`), sync to a user-chosen folder (Dropbox/OneDrive/GDrive handle transport). No Talk DAT! server.
16. **Snippet templates with variables** (`{date}`, `{clipboard}`, `{cursor}`) - S
    Variable expansion pass in the snippets engine in `text_pipeline`; TextExpander-standard.
17. **PII / profanity filter** - M
    Regex pass (emails, cards, SSNs) plus optional LLM redaction via item 3; toggle in Settings > Privacy.
18. **Meeting transcription mode** (system audio capture) - L *(shipped, beta)*
    WASAPI loopback capture (`soundcard` package or `sounddevice` WASAPI settings) into the existing batch lane with chunked VAD; new "Meeting" tray mode writing live notes to a scratchpad tab. This is the MacWhisper/Granola wedge.
19. **Speaker diarization view** - M
    Builds on 18: route meeting audio to diarizing providers already in the registry (AssemblyAI speaker-labels, ElevenLabs diarize, gpt-4o-transcribe-diarize); render speaker-colored transcript.
20. **Translation mode** (dictate in any language, paste in English) - S
    Whisper task=translate flag in `local_stt`, or LLM translate via item 3; per-profile target language.

## Tier 3 - Platform, trust, and reach

21. **Update channels (stable/beta) + delta-conscious updater** - S
    Builds on the new update window: `updates.channel` config; beta reads pre-releases from the GitHub API (`/releases` list instead of `/latest`).
22. **Opt-in crash reporting + diagnostics bundle** - M
    Local-first: rotate `%APPDATA%\TalkDat\logs`, "Export diagnostics ZIP" button (logs + redacted config); optional Sentry DSN for opt-in telemetry.
23. **Interactive onboarding tutorial** - M
    Shipped as a versioned seven-step first-run walkthrough: account/trial and
    private-mode choice, route cards, local mic waveform, trigger-key rehearsal,
    writing presets, and protected first dictation into a practice box. Remaining
    work is broader clean-machine and assistive-technology field validation.
24. **Accessibility pass** - M
    Keyboard navigation through settings tabs, screen-reader labels on controls, reduced-motion toggle (skips pill animations), high-contrast theme family (theme scaffolding exists, 20 themes already).
25. **Multi-monitor + pill position presets** - S
    Per-monitor placement and corner presets in `_apply_geometry` / `_logical_work_area`; remember last monitor by device name.
26. **Browser extension companion** - L *(shipped, beta)*
    Chrome/Edge MV3 extension + native messaging host: focused-field insert without synthetic Ctrl+V, per-site profiles. Pairs with item 1.
27. **CLI + local HTTP API** - M
    `talk-dat --toggle|--paste-last|--history` via the existing single-instance pipe; optional localhost HTTP for Raycast/Stream Deck/AutoHotkey integrations.
28. **Portable mode + package managers** - M
    `TALK_DAT_HOME` already enables portable config (ship `portable.flag` detection next to the EXE); publish winget and Chocolatey manifests from the release workflow.
29. **Shared dictionary/snippet packs** - M
    Import/export signed JSON packs (team names, jargon); load from URL or file; merge UI with conflict review. The "teams" wedge without running a server.
30. **Plugin system for transforms and providers** - L
    Entry-point discovery (`talkdat_plugins/*.py` in AppData) exposing `register_transforms()` / `register_providers()` against the existing registries; documented stable API surface. Community leverage multiplier.

## Action plan

**Phase 1 (weeks 1-2) - quick wins on shipped foundations:** 11, 12, 14, 16, 20, 21, 25, 10, 4. All small, all build directly on the SQLite history store, local engine lane, transforms pipeline, and new updater that are already in main.

**Phase 2 (weeks 3-6) - the differentiators:** 1, 2, 3, 5, 6, 7, 9, 13, 17, 23. Per-app profiles + BYOK LLM cleanup + voice editing is the Wispr Flow feature-parity package; GPU toggle and device picker complete the local story.

**Phase 3 (weeks 7-12) - the moat:** 18, 19, 8, 15, 22, 24, 27, 28, 29. Meeting mode and diarization open a second multimillion-dollar market (meeting notes); wake word, sync, packaging, and trust features harden the product.

**Phase 4 (quarter 2) - the platform:** 26, 30. Browser extension and plugins turn Talk DAT! from an app into an ecosystem.

Sequencing rules: 19 depends on 18; 4, 17, 20 lean on 3; 21-23 share the updater/logging plumbing; everything in Phase 1 is independently shippable. Each feature lands behind a settings toggle, defaults preserving current behavior, with a `docs/` note and a prepublish-check pass before tagging.
