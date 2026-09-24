# Third-Party Notices

Talk DAT!'s own source code is licensed under the [Apache License 2.0](LICENSE)
and this repository vendors no third-party code (the verbatim FSF license
texts in `knight_flow/assets/licenses/` are the only exception). Binary
distributions (the Windows installer and portable zip, the Mac disk image)
bundle the Python runtime and the third-party packages listed in
`requirements.txt` and `requirements.lock`, each under its own license.

**The complete list, with every license text, is `THIRD_PARTY_LICENSES.txt`.**
The build generates it from the bundled packages' own metadata
(`scripts/collect_licenses.py`, run by `build-exe.ps1`) and ships it next to
the program and in the installer's `docs` folder. Nothing in Talk DAT!'s
license or end-user terms restricts the rights those licenses grant. This page
is the human summary.

## Components with obligations worth knowing

| Component | License | Notes |
|---|---|---|
| pynput, pystray | LGPL-3.0 | Bundled as Python modules. The full source of Talk DAT! and its build scripts is public, so you can rebuild the app against a modified copy. |
| fpdf2 2.8.8 | LGPL-3.0-only | Shipped as replaceable source; see below. |
| FFmpeg 8.1.2, inside PyAV 18.1.0 (`av`) | LGPL-3.0-or-later; its x264 and x265 libraries are GPL-2.0-or-later | Used only to resample audio. License texts are in `THIRD_PARTY_LICENSES.txt`; the written offer for the source is [below](#written-offer-for-source-code) and at the end of that file. |
| LAME (`libmp3lame`) and GNU libiconv, inside PyAV | LGPL-2.0-or-later and LGPL-2.1-or-later | Built into PyAV's FFmpeg; covered by the same written offer. PyAV's other bundled libraries (dav1d, SVT-AV1, Opus, libvpx, libwebp, opencore-amr, Intel VPL, zlib under permissive licenses, and the GCC runtime under the GCC Runtime Library Exception) are listed with their licenses in `THIRD_PARTY_LICENSES.txt`. |
| certifi, tqdm | MPL-2.0 | Unmodified. |
| NVIDIA cuDNN 9.10.2 (`cudnn64_9.dll`, inside CTranslate2 4.8.1) | NVIDIA Software License Agreement for NVIDIA Software Development Kits, with the cuDNN Supplement: https://docs.nvidia.com/deeplearning/cudnn/backend/v9.10.2/reference/eula.html | Proprietary, redistributable as part of this application only. Not Apache-2.0; see "NVIDIA components" in [EULA.md](EULA.md). |
| Intel OpenMP (`libiomp5md.dll`, inside CTranslate2) | Intel redistribution terms | Proprietary, redistributable. |
| Microsoft DirectML (`DirectML.dll`, inside ONNX Runtime) | Microsoft DirectML license | Redistributable. |
| Microsoft WebView2 SDK (inside pywebview) | WebView2 SDK license (BSD-style) | Redistributable. |
| Microsoft Visual C++ runtime | Visual C++ Redistributable license | Redistributable. |
| Python, Tcl/Tk, OpenSSL, SQLite, zlib, libffi | PSF-2.0, TCL, Apache-2.0, public domain, Zlib, MIT | Bundled with the Python runtime. |
| Everything else (numpy, scipy, scikit-learn, onnxruntime, ctranslate2, faster-whisper, onnx-asr, pillow, cryptography, requests, huggingface_hub, tokenizers, pywebview, pythonnet, sounddevice, pyautogui, and others) | MIT, BSD, Apache-2.0, PSF and similar permissive licenses | Apache-2.0 components' NOTICE files are reproduced in `THIRD_PARTY_LICENSES.txt`. |

pyautogui's optional helpers `mouseinfo` (GPL-3.0-or-later) and `pymsgbox`
are deliberately excluded from every build; the app uses pyautogui only to
press keys.

## Written offer for source code

Some bundled components are licensed under the GNU GPL or LGPL: FFmpeg inside
PyAV and the libraries PyAV builds it with (the GPL x264 and x265, the LGPL
LAME and GNU libiconv), and pynput, pystray and fpdf2. For at least three
years after Knight AI+AV LLC last distributes a version of Talk DAT!, Knight
AI+AV LLC will give anyone who asks a complete machine-readable copy of the
corresponding source code of those components, as used in that version, for
no more than the cost of physically performing the transfer. Write to
security@knightaiav.com or Build@KnightAIAV.com with the subject "Source
request" and the version. The same offer, naming the version, closes
`THIRD_PARTY_LICENSES.txt` in every binary.

The same sources are published upstream. This release bundles PyAV 18.1.0
with FFmpeg 8.1.2, built by pyav-ffmpeg 8.1.2-1:

| Component | Corresponding source |
|---|---|
| PyAV 18.1.0 | https://github.com/PyAV-Org/PyAV/tree/v18.1.0 |
| pyav-ffmpeg 8.1.2-1 (the FFmpeg build PyAV 18.1.0 uses; `scripts/pkg.py` at this tag names the source archive of every library in it) | https://github.com/PyAV-Org/pyav-ffmpeg/tree/8.1.2-1 |
| FFmpeg 8.1.2 | https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz |
| x264 (commit b35605ace3ddf7c1a5d67a2eb553f034aef41d55) | https://code.videolan.org/videolan/x264/-/archive/b35605ace3ddf7c1a5d67a2eb553f034aef41d55/x264-b35605ace3ddf7c1a5d67a2eb553f034aef41d55.tar.bz2 |
| x265 4.2 | https://bitbucket.org/multicoreware/x265_git/downloads/x265_4.2.tar.gz |
| LAME 3.100 (libmp3lame) | https://deb.debian.org/debian/pool/main/l/lame/lame_3.100.orig.tar.gz |
| GNU libiconv 1.19 | https://ftp.gnu.org/pub/gnu/libiconv/libiconv-1.19.tar.gz |
| pynput, pystray | https://github.com/moses-palmer/pynput, https://github.com/moses-palmer/pystray |
| fpdf2 2.8.8 | https://github.com/py-pdf/fpdf2 (also shipped as source in `pdf_runtime`) |

`scripts/collect_licenses.py` holds the same list (`PYAV_SOURCES`) and fails
a strict build whose PyAV version has no entry, so the offer moves with the
bundle.

## PDF Documents

- fpdf2 2.8.8: https://github.com/py-pdf/fpdf2, GNU LGPL version 3.
- fontTools: https://github.com/fonttools/fonttools, MIT license.
- uharfbuzz: https://github.com/harfbuzz/uharfbuzz, Apache license version 2.
- regex: https://github.com/mrabarnett/mrab-regex, Apache license version 2
  and the component notices in its distribution.
- defusedxml: https://github.com/tiran/defusedxml, Python Software Foundation license.

The fpdf2 library is provided as complete Python source in `pdf_runtime/fpdf`
inside the application's runtime directory, with its copyright notices. The
GPL and LGPL texts are in `pdf_runtime/licenses`; the original distribution
license is also retained in `fpdf2-2.8.8.dist-info`. You may modify or replace
this library and debug those modifications under its license.

The application loads this source copy before its frozen fallback. A compatible
replacement uses the same `fpdf` package interface; the official build tests
2.8.8. No version-string lock prevents a compatible modified library from
loading. On Windows, this runtime directory is `_internal` beside the program.
In the Mac application bundle it is reached from `Contents/Frameworks`, with
data links to `Contents/Resources`. Preserve the package layout when replacing
the library. Modifying a signed Mac bundle requires signing the modified copy
for your own use; the official publisher's signature covers only its original
files.

PDFs embed subsets of compatible fonts already installed with the operating
system. Those font files are not redistributed in the installer. A font that
disallows this embedding path is rejected rather than silently substituted.
The complete exported text is also embedded as a UTF-8 attachment.

## Local Speech Models

Model weights are not stored in this repository or embedded in any installer.
When a user chooses Local / On-Device, Talk DAT! downloads the selected model
into that user's private models directory (`%APPDATA%\TalkDat\models` on
Windows).

The default model is NVIDIA Parakeet TDT 0.6B v3:

- Parakeet TDT 0.6B v3 by NVIDIA Corporation, licensed under the Creative
  Commons Attribution 4.0 International License
  (https://creativecommons.org/licenses/by/4.0/).
- Source: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- ONNX conversion used by the `onnx-asr` runtime, by istupakov:
  https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx
- Provided as is, without warranties.

Other downloadable models show their family and license in the Local Models
screen, and their model cards are the authoritative source for their terms:
other NVIDIA Parakeet, Canary and Nemotron models (CC BY 4.0), Whisper and the
SYSTRAN faster-whisper conversions (MIT), Distil-Whisper (MIT) and GigaAM (MIT).

Optional GPU acceleration on NVIDIA cards downloads NVIDIA's CUDA runtime
wheels from PyPI at the user's request (`knight_flow/cuda_runtime.py`). They
are never bundled, and each carries NVIDIA's license as `License.txt`:

- `nvidia-cublas-cu12` 12.9.2.10: the NVIDIA CUDA Toolkit End User License
  Agreement, https://docs.nvidia.com/cuda/eula/index.html
- `nvidia-cudnn-cu12` 9.25.1.1: the NVIDIA Software License Agreement for
  NVIDIA Software Development Kits with the cuDNN Supplement,
  https://docs.nvidia.com/deeplearning/cudnn/backend/v9.25.1/reference/eula.html

## Local Formatting and Translation Models

These run in Ollama (https://ollama.com/, MIT License), which the user installs
separately. Talk DAT! does not redistribute any of these weights.

- Qwen3 1.7B, the optional local formatter, by the Qwen team, Alibaba Cloud:
  Apache License 2.0.
- TranslateGemma, the optional local translator, by Google
  (`google/translategemma-4b-it` and related sizes): Gemma Terms of Use,
  https://ai.google.dev/gemma/terms. Model card:
  https://huggingface.co/google/translategemma-4b-it. Ollama packages:
  https://ollama.com/library/translategemma.

## Wake word

openWakeWord's pre-trained models are licensed CC BY-NC-SA 4.0 upstream
(non-commercial). Talk DAT! does not ship or download them; a wake-word model
is prepared by the user (see `docs/WAKE_WORD.md`).

## Speech Runtimes

- `onnx-asr`: https://github.com/istupakov/onnx-asr
- `faster-whisper`: https://github.com/SYSTRAN/faster-whisper
- CTranslate2: https://github.com/OpenNMT/CTranslate2
- ONNX Runtime: https://github.com/microsoft/onnxruntime

## Fonts

- `knight_flow/assets/fonts/KnightDisplay.ttf` (and its copy under
  `knight_flow/web_shell/shell_assets/fonts/`): the Knight Display typeface,
  Copyright Knight AI+AV. A proprietary brand asset, **not** licensed under
  Apache-2.0; see [TRADEMARKS.md](TRADEMARKS.md).

Talk DAT! does not claim ownership of these libraries, model weights, provider
names, or trademarks.
