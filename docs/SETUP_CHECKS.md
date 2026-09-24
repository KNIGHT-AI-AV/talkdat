# Setup checks

Getting started is in Help. First launch and the Pill menu use the same shared
setup screen when the web renderer is available. Four sections keep it short:
Welcome, Voice, Controls and Try it. Move between them freely, or save for later.
The existing native setup remains the fallback if the renderer is unavailable.

Setup offers Local speech or a supported provider with your own key. Your
selection now updates the same route the dictation engine reads. If Local-only
privacy is enabled, setup explains that it takes priority. Choose Local, or
review the existing Privacy setting before choosing a provider. Setup does not
turn off that privacy setting for you.

The Voice section also offers Smart formatting: the local writing model that
formats your dictation on this computer. Set up smart formatting installs the
Ollama engine (Windows, through Windows Package Manager) if it is missing and
downloads the model once: the 2.5 GB model on a computer with a supported
graphics card, the 1.4 GB model otherwise. If the larger model turns out not to
fit on the card, Talk DAT measures that and falls back to the smaller one. It is recommended when the card is there and the disk has
room, offered either way, and never required: Finish setup works while it is
still downloading or after Not now. The model is warmed as soon as it lands, so
the next dictation uses it without a restart. Settings, Formatting shows the
same job (Ready, Not set up, Downloading, Failed with Retry). On a Mac, where
the engine cannot be installed for you, the step appears once the Ollama app is
installed; until then Settings offers Get Ollama and Check again.

A missing selected microphone stays selected and is marked unavailable.
Reconnect it or choose another input explicitly. The microphone check does not
silently switch to another device. Checks remain optional, and completion
records which checks were actually performed.

The practice result is the text Talk DAT produced. An empty result asks you to
check the microphone or try again. The two finishing previews describe their
visible difference; identical text does not prove that an AI model ran or failed.

If settings cannot be saved, setup stays open with a message and retains the
previous saved settings. A successful save remains saved even if a later
runtime refresh needs an app restart. The terms notice and account, licensing
and paid-feature rules are unchanged.

The trigger check lasts up to 30 seconds and does not record audio. It resumes
regular shortcuts after detecting and releasing the configured keys, when you
end the check, or when you leave. Practice recording starts only when requested;
leaving or closing setup cancels its recording before releasing the result.
The practice result remains available in memory while you navigate, with an
explicit Copy action. A new practice replaces it; copy anything you want to keep.

On Mac, permissions are shown as allowed, not allowed, needing review, or unable
to be checked. An unknown result never claims permission was granted. Each
Review button opens the corresponding System Settings page. Refresh permissions
after changing a grant. Fn/Globe labels follow your configured Mac controls.

The shared screen uses your selected theme and material. Fresh physical-device,
first-install and final packaged acceptance remain separate release checks.
