# Talk DAT! generated desktop icon family

This directory contains the first unified icon family for Talk DAT!'s native
desktop surfaces.

- `masters/` contains the 32 selected full-resolution outputs from the Codex
  image generation tool. These are archived source assets and are not shipped
  in the installer.
- `runtime/` contains the deterministic 384 px, grayscale, alpha-safe assets
  produced by `scripts/process_ui_icon_assets.py`. Only this directory ships.
- `contact-sheet.png` is a review proof at 20, 24, and 32 px on representative
  dark and light palettes. `menu-proof-dark.png` and `menu-proof-light.png`
  capture the real expanded Tk Pill menu in Flow Dark and Ivory Halo Light.
  These three proofs are not loaded by the application.

The runtime renderer in `knight_flow/ui/iconography.py` applies each active
theme's text and accent colours while preserving the generated material lift.
That keeps one asset family legible in every shipped light and dark theme and
at Windows display scaling from 100 to 200 percent.

The Talk DAT! logo, application mark, and Pill artwork are separate locked
brand assets. They are never inputs to this semantic icon pipeline and must
not be recoloured, regenerated, or replaced by it.

Do not replace a generated icon with a Unicode character, emoji, font glyph,
or hand-drawn Canvas approximation. Add a distinct transparent master, run the
processor, extend `ICON_NAMES`, and verify the contact sheet and real Tk render.
