# Trademarks and brand assets

Talk DAT!'s source code is open source under the [Apache License 2.0](LICENSE).
Its name and its brand are not. Section 6 of the Apache License already says the
license grants no rights in trademarks; this page says exactly what that covers
and what you may do.

## Not licensed under Apache-2.0

The following belong to Knight AI+AV LLC and are **not** covered by the Apache
License, even though some of the files are in this repository because the app
needs them to build:

**Names**

- "Talk DAT!" and "Talk Dat!", in any capitalization or spacing
- "Talk Stone" and "The Pill"
- "Knight AI+AV"

**Artwork and type (exact files, also listed in [REUSE.toml](REUSE.toml))**

| Asset | Files |
|---|---|
| Talk Stone logo and application icon | `knight_flow/assets/app_icon.ico`, `knight_flow/assets/app_icon.png`, `knight_flow/assets/logo.ico`, `knight_flow/assets/logo.png`, `knight_flow/assets/favicon.ico`, `knight_flow/assets/favicon.png` |
| The Pill artwork and animation frames | `knight_flow/assets/flow_pill_240.png`, `knight_flow/assets/flow_pill_240.json`, `knight_flow/assets/loading_pill_240.png`, `knight_flow/assets/loading_pill_240.json`, `knight_flow/assets/ui/processing-spectrum-loop-4k.png` |
| Knight Display typeface | `knight_flow/assets/fonts/KnightDisplay.ttf`, `knight_flow/web_shell/shell_assets/fonts/KnightDisplay.ttf` |
| Onboarding art | `knight_flow/assets/onboarding/*.png` |
| Installer art | `knight_flow/assets/ui/installer-clay.jpg`, `installer/splash.png`, `packaging/dmg-background.png` |
| Shared material art | `knight_flow/assets/materials/shared/**` |

Everything else in the repository, including the other generated textures and
icons, is Apache-2.0.

## What you may do without asking

- Build and run the unmodified source, for yourself or inside your
  organization, with the brand assets in place.
- Say truthfully that your work is "based on Talk DAT!", "a fork of Talk DAT!"
  or "compatible with Talk DAT!".
- Link to https://www.talkdat.app/.

## What needs our written permission

- Distributing a modified build, or any build you made yourself, under the
  Talk DAT! name, icon, Pill artwork or typeface.
- Publishing any build to an app store, package manager or download site under
  the Talk DAT! name.
- Using the marks in a product name, company name, domain name or social
  handle, or in a way that suggests Knight AI+AV made or endorses your product.

## Forks

If you distribute a fork, rename it and replace the brand files above with your
own. Also change the identity values the app uses so your build does not
collide with an installed official copy: the product name, the macOS bundle id
and URL scheme (`TalkDat-mac.spec`), the application data folder and credential
names (`knight_flow/config.py`, `knight_flow/credentials.py`), the Windows
version resource (`Talk Dat!.spec`, `build-exe.ps1`) and the endpoints in
`knight_flow/official_build.py`. A build from source contacts none of Knight
AI+AV's services unless you configure it to (see
[docs/NETWORK.md](docs/NETWORK.md)).

Questions: Build@KnightAIAV.com.
