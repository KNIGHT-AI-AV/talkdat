# Talk DAT! onboarding artwork

These six 1200 x 675 PNG masters were generated specifically for Talk DAT! and
are bundled locally with the desktop application. They contain no text, people,
third-party logos, copied interface chrome, or dependency on a network fetch.
The live interface supplies every label, state, control, focus ring, meter, and
permission explanation.

## Shared art direction

- Premium industrial product photography in a dark obsidian studio.
- The existing square Talk DAT! mineral icon is the product reference.
- Warm ivory edge light, restrained teal and amber spectrum accents.
- Generous negative space, physically plausible materials, quiet contrast.
- No neon cyberpunk treatment, fake screen, floating UI card, or brand mimicry.
- 16:9 composition designed to crop safely in both dark and light themes.

## Asset map and final prompts

### `01-arrival-stone.png`

Pages: Talk DAT! arrival and private-instrument introduction.

Prompt: Create a high-end cinematic product still for the Talk DAT! desktop
onboarding experience. Use the supplied square Talk DAT! icon as the exact
product reference. Float the mineral-black square instrument above a low
blackened-metal plinth in an obsidian studio, with a warm ivory edge light and
restrained teal-to-amber spectrum light inside the five voice slots. Compose in
16:9 with generous negative space and physically plausible shadows. No text,
people, third-party logos, neon cyberpunk styling, or interface mockup.

### `02-access-continuity.png`

Page: optional account sign-in (no plans: Talk DAT! is free).

Prompt: Create a luxury technology product still in 16:9. Place the Talk DAT!
square stone inside a precision-machined circular cradle, with two quiet metal
paths converging into one illuminated continuity point. Keep the product on the
right half and leave useful negative space on the left. Use obsidian metal,
subtle warm ivory light, and restrained teal and amber accents. Suggest account
continuity without literal locks, cards, screens, text, people, logos, or copied
brand styling.

### `03-route-engine.png`

Page: private on-device and bring-your-own-key speech routes (the managed-cloud channel in this image is retired).

Prompt: Create an editorial 16:9 product photograph for a speech-routing
instrument. Three engineered physical channels converge into the Talk DAT!
square stone: a cool managed-cloud vapor channel, a private local-device core,
and a narrow amber provider-key path. Use a dark precision workshop, quiet
materials, clear visual hierarchy, and negative space for live interface copy.
No readable text, icons, dashboards, people, third-party marks, or science-fiction
glow.

### `04-voice-instrument.png`

Pages: microphone tuning and trigger rehearsal.

Prompt: Create a premium acoustic-instrument still in 16:9. A real dark studio
microphone capsule sends a subtle physical sound ribbon through a machined
measurement gate toward the Talk DAT! square stone. Include two unlabeled,
depressed metal keycaps as a secondary detail. Use obsidian surfaces, precise
warm rim light, restrained teal and amber signal color, and realistic depth.
No text, hands, people, fake UI, logos, or decorative neon.

### `05-command-deck.png`

Pages: Pill Panel and command-deck feature introduction.

Prompt: Create a refined 16:9 product-launch image. Place the Talk DAT! square
stone at the center of a circular blackened-metal command deck while six unique
machined functional modules unfold around it. Each module should feel physical
and purposeful through vents, channels, a dial, or a measured signal aperture,
not like floating software cards. Use restrained spectrum accents, deep
materials, and clean negative space. No text, people, third-party logos, game
console styling, or copied luxury-brand motifs.

### `06-finish-engine.png`

Pages: writing finish and first-dictation result.

Prompt: Create an elegant 16:9 finishing-machine still for a speech-to-writing
product. Feed an irregular acoustic ribbon through a precision black-metal
mechanism and let it emerge as aligned warm-ivory paper strips beside the Talk
DAT! square stone. Suggest faithful cleanup, structure, and delivery using
physical transformation rather than readable text. Use an obsidian studio,
restrained teal and amber light, and realistic materials. No words, people,
screens, third-party marks, or exaggerated glow.

## Packaging contract

The Windows candidate explicitly enumerates these six PNGs in `Talk Dat!.spec`
and verifies them again through `build-exe.ps1` after packaging. That proves
only the Windows payload. The macOS port must separately add the same manifest
to `TalkDat-mac.spec` and verify the files inside the built application bundle
through `build-mac.sh`. Keep each platform's checks synchronized with this
directory; do not treat the Windows packaging test as Mac evidence.

## Source integrity manifest

The values below identify the reviewed 1200 x 675 RGB masters. They are a
source-review receipt, not a substitute for checking the bytes inside a built
installer. Each SHA-256 fingerprint is written as 32 colon-delimited bytes;
removing the separators produces the conventional 64-digit hexadecimal form
without changing any digest data.

| File | SHA-256 |
|---|---|
| `01-arrival-stone.png` | `07:62:ad:53:5f:cf:a8:10:95:47:ae:4a:60:07:96:03:38:0b:27:78:57:6f:50:38:93:2f:31:27:ce:48:59:c6` |
| `02-access-continuity.png` | `2b:30:90:db:b9:36:e3:5d:b7:4f:34:55:94:40:9d:42:fa:6c:18:bd:20:b8:c0:ea:72:6c:25:1b:a1:d7:6f:41` |
| `03-route-engine.png` | `81:8d:6f:58:b8:5e:6e:81:af:cf:6d:eb:8c:54:28:70:d4:da:71:04:d2:94:2d:6a:00:d1:6c:c4:29:23:c2:57` |
| `04-voice-instrument.png` | `37:98:45:3f:c4:cb:a8:01:d5:d5:0f:e6:52:24:1c:28:92:c1:f1:a3:25:bb:ba:d5:11:f7:d2:2f:4d:87:49:c0` |
| `05-command-deck.png` | `04:26:dd:7d:9c:cd:e7:64:c8:48:03:d1:64:17:5e:6f:64:1c:49:63:7e:d0:13:90:cc:0c:10:06:44:b5:8f:41` |
| `06-finish-engine.png` | `1d:b4:b7:b5:22:5e:d5:69:15:f1:66:3d:ef:9e:37:f9:55:23:9f:36:15:64:33:cb:3f:cd:45:ea:5c:d3:2e:4b` |
