# Talk DAT! End User License Agreement

Effective date: September 23, 2026

This End User License Agreement ("Agreement") covers the official Talk DAT!
binaries that Knight AI+AV LLC ("Knight") builds, signs and distributes: the
Windows installer and portable app and the Mac disk image. Installing or using
one of them means you accept this Agreement. It says the same things as the
Talk DAT! Product Terms at https://www.talkdat.app/terms.html.

## Talk DAT! is free, and its source is open

Talk DAT! is free to download and use. There is no paid plan, nothing renews,
and nothing in the software bills you. Knight does not ask for payment
details. If Knight ever offers something paid, it will be a separate, clearly
priced offer that you would have to choose.

The Talk DAT! source code is licensed under the Apache License, Version 2.0.
A copy is in LICENSE.txt, with the notices in NOTICE.txt. Nothing in this
Agreement limits what the Apache License lets you do with that source code,
including copying, modifying and redistributing it.

## Third-party software

The binaries include third-party components, each under its own license:
among them LGPL-licensed libraries (pynput, pystray, fpdf2, and FFmpeg inside
PyAV), GPL-licensed libraries (x264 and x265 inside PyAV), and redistributable
components from Microsoft, NVIDIA and Intel. Their notices and full license
texts are in THIRD_PARTY_NOTICES.md and THIRD_PARTY_LICENSES.txt, which ship
with every binary, together with a written offer for the source code of the
GPL and LGPL components. Those licenses govern those components. Nothing in
this Agreement restricts the rights they grant, including your right to
modify or replace an LGPL library and to reverse-engineer the program to debug
such a modification. NVIDIA's components are covered in the next section.

## NVIDIA components

The Windows binaries include one NVIDIA file: `cudnn64_9.dll`, NVIDIA cuDNN
9.10.2, shipped inside the CTranslate2 speech runtime. It is licensed to you
under NVIDIA's license terms, not the Apache License: the NVIDIA Software
License Agreement for NVIDIA Software Development Kits, with the cuDNN
Supplement (https://docs.nvidia.com/deeplearning/cudnn/backend/v9.10.2/reference/eula.html).
To the extent NVIDIA's terms require, you may use it only as part of Talk DAT!,
and you may not redistribute it separately from Talk DAT!, modify it or reverse
engineer it.

If you turn on GPU acceleration on an NVIDIA card, Talk DAT! downloads NVIDIA's
CUDA runtime from NVIDIA's own packages on PyPI; nothing of it ships in the
installer. Those files come to you under NVIDIA's license terms, which each
package carries as License.txt: cuBLAS (`nvidia-cublas-cu12` 12.9.2.10) under
the NVIDIA CUDA Toolkit End User License Agreement
(https://docs.nvidia.com/cuda/eula/index.html), and cuDNN (`nvidia-cudnn-cu12`
9.25.1.1) under the cuDNN agreement above as published for that version
(https://docs.nvidia.com/deeplearning/cudnn/backend/v9.25.1/reference/eula.html).
Knight grants no rights in them.

This section covers only those NVIDIA files. It does not restrict the Talk DAT!
source code, which stays under the Apache License 2.0, or any LGPL- or
GPL-licensed component, whose own licenses continue to govern as described
above.

## Using the official binaries

You may install and use the official binaries on devices you own or control,
for personal use or inside your organization, on as many of those devices as
you like, and pass copies on unmodified.
No account is needed. Signing in, with an emailed code or with Sign in with
Apple, is optional.

## Trademarks

"Talk DAT!", "Talk Stone", "The Pill", "Knight AI+AV", the Talk DAT! logo and
icon, The Pill artwork and the Knight Display typeface are Knight's trademarks
and brand assets. Neither this Agreement nor the Apache License grants you the
right to use them. If you distribute a modified build, give it another name
and remove Knight's branding; see TRADEMARKS.md.

## Your content and providers

What you dictate is yours, and you are responsible for it. Talk DAT!
transcribes and formats on your own device; Knight does not receive your
audio, transcripts, history, dictionaries, scratchpads, or protected voice
sessions. If you add a key for a third-party speech or writing provider,
requests on that route go from your device to that provider, and you are
responsible for that provider's account, charges, and terms.

If you use the optional account, Knight processes the minimum account and
device metadata described in the Talk DAT! Privacy Notice at
https://www.talkdat.app/privacy.html. You can delete the account at any time.

## Recording other people

If you use Talk DAT! where other people can be heard, recording and
transcribing them may require their consent where you are. You are
responsible for obtaining that consent.

## Updates

The official binaries may check Knight's official distribution channel for
updates. Features may be added, changed, or withdrawn; Talk DAT! is a public
beta.

## Warranty disclaimer and liability

Talk DAT! is provided "as is" and "as available" without warranties of any
kind. To the maximum extent permitted by law, Knight is not liable for
indirect, incidental, special, consequential, or exemplary damages, loss of
data, lost profits, provider charges, or interruption arising from use of the
software, and Knight's aggregate liability is limited to the amount you paid
Knight for Talk DAT!, which is nothing. Nothing here limits liability that the
law does not allow to be limited.

## Governing law

This Agreement is governed by the laws of the State of California, United
States, without regard to its conflict of law rules. The United Nations
Convention on Contracts for the International Sale of Goods does not apply.
Any dispute will be brought exclusively in the state or federal courts located
in Sacramento County, California. Nothing here removes a consumer protection
right, or the right to bring a claim in a small claims court, that cannot be
waived under the law of your country or state of residence.

## Contact

Questions may be sent to Build@KnightAIAV.com.
