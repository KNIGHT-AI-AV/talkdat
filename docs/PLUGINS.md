# Installed plugins

Plugins are optional local Python extensions. They are off by default.
Open Settings > Privacy > Automation > Advanced options to enable them.
Only enable code you trust: an extension can access your files and the network
as your account. A separate host protects dictation from common crashes and
stalls; it does not make third-party code a security sandbox.

Open plugins folder shows the local folder. Each Python file may define
register(api), then add named transforms or text filters. Text filters run in
filename and registration order. A filter receives the current text and a copy
of the configuration, and returns a nonempty string. Intended text changes
remain the extension author's responsibility. Returning no string, an empty
string, throwing an exception or exceeding the time limit preserves the text
from before that filter. Successful output retains whitespace and passes the
house punctuation rule. Named transforms retain the existing built-in fallback.

Save your enable/disable choice before reloading. Reload plugins reads current
source without relying on stale Python bytecode and shows each failed file.
It runs in the background and is refused while capture is active. Opening the
status view does not run extension code. Turning plugins off retires their
hosts, including a load still in progress. Quit and Restart wait for this
cleanup. An error lists its type and file, without retaining the extension's
exception message or your dictated words.

The current limits are 32 files per load, 128 filters or named transforms per
file, 512 KiB of source per file, 200, 000 characters of text, and 1 MiB per
serialized message including configuration. Oversized or invalid results are
not truncated into a replacement. Startup allows 1 second per file and a
2-second batch budget; a hook gets 350 ms and a filter chain shares 500 ms.
These are processing budgets, with process cleanup and scheduling overhead
measured separately. Once a host times out or exits, reload is needed to retry.
Files that fail registration contribute no hooks. A bounded error list keeps
the most recent 128 distinct file/type entries.

Extension code uses the modules available in the app's Python runtime. Talk
DAT does not download dependencies for a plugin. Source checks cover healthy,
invalid, slow and crashing fixtures on Windows and Mac, plus both native
settings renderers. Final release-package acceptance remains a separate gate.
