# Local control API

Talk DAT! can expose a small HTTP API on your own machine so tools like Stream Deck,
AutoHotkey, Raycast-style launchers, or a shell script can trigger dictation. It is
**off by default** and only ever listens on the loopback interface.

## Turning it on

In `config.json` under `%APPDATA%\TalkDat`:

```json
{
  "remote": {
    "enabled": true,
    "port": 4670,
    "token": "<your-token>"
  }
}
```

Restart Talk DAT! after changing `remote`.

Set a token. It is optional for the action routes so existing setups keep working,
but without one any program on the machine can trigger your dictation, and the route
that returns dictated text refuses to answer at all.

## Endpoints

Every route accepts `GET` or `POST`. Responses are JSON.

| Route | Does | Token |
| --- | --- | --- |
| `/status` | Returns the app's current state | Required only if configured |
| `/toggle` | Starts or stops hands-free dictation | Required only if configured |
| `/cancel` | Panic stop | Required only if configured |
| `/paste-last` | Pastes the last transcript into the active app | Required only if configured |
| `/copy-last` | Copies the last transcript to the clipboard | Required only if configured |
| `/last-text` | **Returns the last transcript as text** | Always required |

Send the token as a header or a query value:

```
curl -H "Authorization: Bearer <your-token>" http://127.0.0.1:4670/status
curl "http://127.0.0.1:4670/toggle?token=<your-token>"
```

## What protects it

- **Loopback bind.** The listener is bound to `127.0.0.1`, so nothing on your network
  can reach it.
- **Host header check.** A website you visit can point a hostname it owns at
  `127.0.0.1` and script requests at this port. Those requests still carry the
  attacker's hostname, so any request that does not address the server as `localhost`,
  `127.0.0.1`, or `[::1]` is rejected with `403`.
- **Dictated text always needs a token.** `/last-text` is the only route that hands
  back what you said. On a tokenless listener it answers `403` with a message telling
  you to set `remote.token`, rather than disclosing the transcript.
- **Constant-time token comparison,** so a wrong token cannot be discovered by timing
  the response.

If a request fails, the response says why: `401` for a bad or missing token, `403`
for a non-localhost `Host` or a tokenless `/last-text`, `404` for an unknown route.

## What it is not

This API cannot read your history, your configuration, your provider keys, or your
audio. It exposes the actions above and nothing else. Turning `remote.enabled` back
to `false` and restarting stops the listener entirely.

Covered by `tests/test_http_api.py`.
