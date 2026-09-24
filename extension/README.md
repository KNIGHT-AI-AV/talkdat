# Talk Dat! Companion (browser extension)

Inserts your latest Talk Dat! transcript directly into the focused browser
field without synthetic Ctrl+V, and toggles hands-free dictation.

## Setup

1. In Talk Dat!: Settings > Core > enable "Enable local control API", save.
2. In Chrome/Edge: open `chrome://extensions`, enable Developer mode,
   "Load unpacked", and pick this `extension/` folder.
3. Shortcuts: `Alt+Shift+V` inserts the latest transcript, `Alt+Shift+D`
   toggles dictation. The toolbar button also inserts the latest transcript.

The extension only talks to `http://127.0.0.1:4670` (your own machine). If you
set a `remote.token` in Talk Dat!'s config, edit `BASE` calls in
`background.js` to append `?token=YOURTOKEN`.
