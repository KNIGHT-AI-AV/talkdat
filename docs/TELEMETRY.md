# Telemetry and anonymous counts

Talk DAT! has two separate things that could be called telemetry. Only one of
them sends anything, and only from official builds. The full list of every
connection the app can make is in [NETWORK.md](NETWORK.md).

## 1. Anonymous usage counts: official builds, on by default, their own switch

`knight_flow/activation_metrics.py` sends four kinds of count to
`POST https://api.talkdat.app/v1/activation`. The setting names them in the
same words: first open, first dictation, still in use, day 7.

| Report | Setting's word | When | Fields |
|---|---|---|---|
| install | first open | once per install, retried until the server confirms it | install id, `stage`, first-run time, version, platform, internal flag |
| first dictation | first dictation | once, after the first delivered dictation | install id, seconds to first dictation, first-run time, version, platform |
| heartbeat | still in use | at most once a day, at startup | install id, `stage`, version, platform, internal flag |
| day 7 | day 7 | once, after a delivered dictation seven or more days after first open (retried at most daily until the server confirms it) | install id, `stage`, version, platform, internal flag |

The install id is a random `uuid4` created on the computer and tied to
nothing else: not the account, not an email address, not the machine. No
report carries audio, text, a file name, a user name or a host name.
`tests/test_our_own_machines_are_not_adoption.py` pins the install field set
and `tests/test_usage_counts_setting.py` the day-7 one. The "internal" flag
marks Knight's own machines and source checkouts so they are not counted as
adoption.

### The switch

**Settings > Privacy > "Share anonymous usage counts: first open, first
dictation, still in use, day 7. Never your audio or text."** The config key is
`privacy.share_usage_counts`. First-run setup mentions it once, as that line
and the toggle, above Finish setup; there is no other prompt.

They are sent only when **all** of these hold, decided in one place,
`knight_flow/official_build.activation_api_base()`:

- the app is an **official build**. A build from source never sends them,
  whatever the setting says and even when pointed at its own server; it shows
  no toggle for them. A fork that wants counts of its own builds as official
  with its own baked endpoint (see NETWORK.md);
- **Share anonymous usage counts is on.** It is on by default; turning it off
  stops all four reports from the next one onwards;
- `TALKDAT_NO_PHONE_HOME=1` is not set. The kill switch turns off every
  connection to Knight's services, these included, and hides the toggle.

**Local-only privacy does not decide the counts.** It governs what you
dictate: your audio and text stay on the computer, and your own provider keys
are not used while it is on. The counts carry neither, so they have their own
switch instead of riding on that one (owner decision, 2026-09-23).

This matches the "Anonymous usage counts" section of the privacy notice
(`docs/privacy.html`).

## 2. Product telemetry: built, not wired (dark)

`knight_flow/telemetry.py` is an event layer that exists and is wired to
nothing: default off, endpoint empty, no call sites. Arming it is a deliberate
future step that ships together with a consent surface, never before.

### The two-switch rule

The layer is armed only when **both** are true:

```json
{ "telemetry": { "enabled": true, "endpoint": "https://..." } }
```

`enabled` alone stays dark (a stray toggle cannot start uploads). An endpoint
alone stays dark (a preconfigured backend cannot collect without consent).
`tests/test_telemetry_stays_dark_and_private.py` pins this.

### What it could ever report

Only these events, with only these properties, from the closed table
`ALLOWED_EVENTS`, enforced at record time rather than by review:

| Event | Allowed properties |
|---|---|
| `app_started` | `app_version`, `days_since_install` |
| `onboarding_completed` | `app_version` |
| `first_dictation` | `app_version`, `route` |
| `dictation_completed` | `app_version`, `route` |
| `settings_opened` | `app_version` |

Values are scalars capped at 64 characters; an oversized value drops the whole
property (truncation would still carry the head of a sentence). The upload
payload has exactly two fields: a random install id and the events. There is
no field a transcript, file name, host name or user name fits in.

`telemetry_id` under the app directory is a random `uuid4`, generated rather
than derived from the machine. Deleting the file makes the install a stranger
to the backend.

### Rules for future work

- Growing `ALLOWED_EVENTS` is a reviewed change.
- `record()` and `flush()` must never raise into the dictation path.
- Arming ships with consent UI, an updated `docs/privacy.html`, an entry in
  NETWORK.md and an entry here: all of them move together or not at all.
