# Meeting recordings and Scribe

Scribe records microphone audio, system audio, or both as separate tracks.
An unavailable source is reported; system audio never silently becomes a
microphone recording. Microphone capture uses the input selected in Settings.
Windows uses its output loopback device. Mac system audio uses Apple's
ScreenCaptureKit and requires macOS 13 or later and the relevant Screen and
System Audio Recording permission. The helper does not request video output.

Recording starts only after an explicit action. Originals are kept in Talk
DAT's application data folder under `scribe-recordings`. They remain after
transcription or saving fails. These files can contain everything heard by the
selected source. A recording warning means that part of the capture may be
missing; keeping the original does not reconstruct audio that never arrived.

Scribe transcribes locally using an already prepared local speech model.
Completed sections are saved as recovery progress. Retry processes failed or
changed sections while retaining verified earlier text. Gaps are marked in the
notes. Source labels identify the microphone and system audio, not individual
speakers; ordering uses approximate 30-second sections.

An AI summary is labelled separately from selected lines extracted from the
transcript. If the conversation exceeds the summary input limit, the full
transcript is kept and selected lines are shown. Incomplete recordings also use
selected lines. Any writing-model failure is disclosed.

Saved notes use an unused filename, including when two recordings finish in the
same minute. Failed saves retain the complete in-memory draft and recoverable
transcription progress. No notes folder opens automatically. Panic Stop cancels
capture and pending processing; Quit waits for the recording devices to close.

Live meeting notes follow the same Local-only privacy rule as normal dictation.
They read bounded sections from the original recording, so a slow recognizer
does not accumulate an unbounded audio buffer in memory. A failed transcript
save stops capture and retains the unsaved words.

Writing > Scribe and the Pill's Scribe entry open the same review screen.
Opening this screen or a saved recording never activates audio. Start recording
is explicit. Finish closes capture before transcription; Stop keeps originals
and pauses work. Recording source controls remain fixed during capture.

Edited notes are saved atomically for recovery in the original recording's
folder. A failed recovery save keeps the editor and prevents silent loss on
navigation; Copy and Save a copy remain ways to keep the draft. A successful
Markdown export creates a separate file and a current-revision receipt. Open
and folder actions require an explicit click. Original recordings and drafts
remain on the computer until their files are removed; there is no automatic
retention cleanup for this experimental library.

Saved recordings lists up to100 recent entries from a bounded5000-entry folder
scan on a worker. The folder action exposes older retained files when this
limit is reached. Unsupported, linked or damaged recovery files are refused
and preserved. An interrupted close receipt is shown as a recording warning.
Completed transcript sections can be recovered even without a review draft.
Retry uses the currently selected local model and language, retries empty and
failed sections, and saves an earlier notes copy before reprocessing. It never
opens the audio devices. Earlier copies remain inside the originals folder.

The shared screen has synthetic browser, Windows WebView2 and Mac WKWebView
acceptance. Real capture, packaged helpers, signing, endurance and physical
microphone/output acceptance still govern graduation from experimental status.
