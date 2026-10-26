# Talk DAT! Companion (browser extension)

Inserts your latest Talk DAT! transcript directly into the focused browser
field without synthetic Ctrl+V, and toggles hands-free dictation.

## Setup

1. In Talk DAT!: Settings > Privacy, turn on "Enable local control API for
   automations", and save.
2. Give Talk DAT! a token: in its config.json, set "token" under "remote" to a
   long random value, then restart Talk DAT!. Inserting your latest transcript
   needs a token; toggling dictation works without one.
3. In Chrome or Edge: open `chrome://extensions`, turn on Developer mode, choose
   "Load unpacked", and pick this `extension/` folder.
4. Open the Companion's options (right-click its toolbar button, then Options),
   paste the same token, and choose Save.
5. Shortcuts: `Alt+Shift+V` inserts the latest transcript, `Alt+Shift+D`
   toggles dictation. The toolbar button also inserts the latest transcript.

If something goes wrong, the toolbar button shows a "!" and says why when you
point at it. The extension only talks to `http://127.0.0.1:4670` (your own
machine), and it keeps the token in this browser only.
