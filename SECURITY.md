# Security policy

## Reporting a vulnerability

Email **security@knightaiav.com**. If that address bounces for any reason, use
Build@KnightAIAV.com and put "security" in the subject. You can also use
GitHub's private vulnerability reporting on this repository.

Please do not open a public issue for a security problem, and never post API
keys, transcripts, dictation history or private config files anywhere,
including in a report. If a finding involves a real person's data, describe
its shape rather than sending the data.

A useful report says what you did, what happened and why it matters, with the
Talk DAT! version, your operating system and the steps to reproduce it.

## What we commit to

- A reply from a person within three business days.
- An assessment, including whether the report is accepted, within ten
  business days.
- Credit in the advisory if you want it, and anonymity if you prefer that.
- Notice when a fix ships, with the release that carries it.

There is no paid bug bounty. We will not pursue or support legal action against
anyone who reports in good faith and stays within these limits: test only your
own installation, account and data; do not access, change or keep anyone
else's information; do not degrade the service for others; and give us a
reasonable chance to fix the issue before describing it publicly.

The full policy is at https://www.talkdat.app/security.html, and machine-readable
contact details at https://www.talkdat.app/.well-known/security.txt.

## Supported versions

Security fixes target the latest official release. Older versions may be asked
to update before a report is investigated.

## Scope

In scope: the Talk DAT! desktop apps for Windows and macOS built from this
repository, the installer and uninstaller, the updater and its release
verification (`knight_flow/updater.py`, [docs/RELEASE_INTEGRITY.md](docs/RELEASE_INTEGRITY.md)),
the local control API on `127.0.0.1:4670` (token and Host-header checks), the
local-only network fence (`knight_flow/net_fence.py`), and the account service
at api.talkdat.app that official builds use.

Out of scope: third-party speech and writing providers you connect with your own
key, findings that only affect a heavily modified build, reports produced
solely by an automated scanner with no demonstrated impact, and social
engineering.

## Secrets in this repository

The repository and the installers must never contain provider keys, signing
credentials or personal data. Provider keys and the sign-in token are stored in
Windows Credential Manager or the macOS Keychain for the current user;
non-secret preferences live in `%APPDATA%\TalkDat\config.json` on Windows and
`~/Library/Application Support/TalkDat` on macOS. Before opening a pull request,
run:

```powershell
python .\scripts\prepublish_check.py
```
