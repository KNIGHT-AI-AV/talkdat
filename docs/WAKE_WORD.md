# Optional wake listening

Wake word is off by default. In Settings > Dictation > Wake word, choose an
installed compatible model and enable listening. The selected microphone is
used; an unavailable named input is reported instead of silently using another.

Compatible local ONNX wake models also need their runtime's preprocessing and
embedding files. Talk DAT does not download these files when a model is missing.
Choose files licensed for your intended use. An unavailable model is reported
on the Pill, and ordinary dictation remains available.

Pause stops wake listening. Resume can start it again when no recording or test
owns audio. Panic Stop suspends wake listening until you turn Wake word off and
back on. A wake phrase cannot toggle off an existing manual dictation. Ordinary
dictation closes the wake microphone first; releasing the hold control during
that brief handoff cancels the pending take.

Wake audio is processed in memory and is not saved by this listener. Recognition
runs on a worker; its audio callback has a bounded queue. An interruption or a
decoder that cannot keep up stops listening with a visible message. The app
retains microphone ownership until the driver confirms closure. Panic Stop can
retry a failed close. Quit and Restart wait for registered audio devices and
remain available with an error if closure does not finish.

The current acceptance checks use synthetic audio and models. They verify
ownership and lifecycle, not real wake accuracy, false activations or the
finished release package. Those remain separate release gates.
