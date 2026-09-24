# Check your microphone and local speech model

Open **Dictation > Mic Doctor** or choose **Mic Doctor** in Tools. The microphone
stays off while the page lists available inputs. Choose your input, then press
**Check my mic** and speak naturally for three seconds, with a brief pause.

The result estimates speaking level, quiet background level and clipped samples.
The pause gives the background estimate a useful reference. These are quick
level checks, not a hardware certification or a measurement of recognition
accuracy. A noisy sample can suggest moving the microphone closer or reducing
room noise. Clipping means the signal is too hot; reduce input level or move
slightly farther away.

Selecting an input saves it for dictation and these checks. **Refresh inputs**
updates the list. If the saved microphone is unplugged, it remains visible as
unavailable until you choose another. A failed save keeps your previous choice.
The check will not quietly switch to another microphone. It can use a different
sample rate supported by the selected device.

Use **Stop check** to cancel. Leaving the page, closing the window, Panic Stop
and quitting Talk DAT also cancel the check. Recording stays visibly owned until
the driver has closed. If a driver refuses to close, the error remains visible
and Panic Stop can retry. A recognition job already running may take time to
retire, but its cancelled result is discarded. Finish or stop the current check
before starting another recording or removing its model.

Open **Dictation > Speech check** to record eight seconds for the downloaded
local speech model. Review the words and use **Copy test words** to keep them.
The displayed recognition time starts after capture and can include model
loading. It does not measure release-to-paste latency, run cloud comparisons or
make a claim about the fastest model. Prepare a local model in Settings first.

These tests do not create History entries or saved recordings. Their temporary
audio stays in memory and is discarded after processing or cancellation. The
normal dictation and protected-recovery retention settings remain separate.
