# Document exports

Open **Writing > Ramble** to record a longer thought or work on a draft. Choose
the document format first. **Record more** adds another recording to your current
words. **Finish writing** uses your configured writing model and keeps the
pre-finishing version under **Original text**. You can edit or save the draft
without applying another writing finish.

**Save document** writes the current draft. Saved documents have separate **Open**
and **Show folder** buttons. A failed finish or save leaves the draft and original
text available to copy, restore or retry. These drafts stay in the current Talk
DAT session, even when text history is off; save a document before exiting the
app to keep it afterward. Finish or cancel an active recording before leaving
Ramble. Recording retains the existing writing-model requirement and session
limits; the interface does not promise an untested recording duration.

Ramble saves PDF, Word, Markdown and text documents. Export report saves a PDF.
Each save uses a new filename, so saving again cannot replace an earlier export.
Word, Markdown and text retain blank paragraphs and indentation.

PDF styles use fonts already installed on your computer to lay out multilingual
text and complete joined emoji. Each PDF also includes `dictated-text.txt`, a
UTF-8 attachment containing the complete text supplied for that export, including
its spacing. It does not add a separate raw recording or hidden transcript.
Reader applications can differ in how they copy complex scripts; the attachment
preserves the exact exported text.

If a required font is missing, a character is unsupported, or a system font
cannot be embedded, Talk DAT explains the problem. Save as Word or text to retain
the content. Fonts and document text are processed locally for PDF layout.

## Maintainer acceptance

Both desktop package specs must call `scripts.pdf_bundle.collect_pdf_runtime`
and use `scripts/pyi_pdf_runtime.py`. The helper includes native shaping libraries,
dependency metadata, notices and a separately replaceable complete fpdf2 source
tree in `pdf_runtime/fpdf`. That tree must load ahead of the frozen archive.
The source guard rejects an incomplete frozen PDF runtime without affecting
Word or text exports. System font files must not be copied into the installer.

The Windows spec includes this integration. The mac-port `TalkDat-mac.spec`
must receive the same helper and runtime hook during the final parity merge.
The private Mac application-bundle proof already exercises both, but is not a
signed Talk DAT release receipt.

Install `requirements-test.txt` for the independent PDF reader checks. Exercise
`tests.test_unicode_documents`, the existing Ramble/report checks and the full
offscreen suite. Native Apple PDFKit and Windows PDFium checks, rendered page
inspection, and a behavior-changing replacement of the external fpdf2 source
are separate package acceptance gates. Restore the original library afterward.

The actual packaged executable accepts `--document-export-smoke`. Set
`TALK_DAT_EXPORT_SMOKE_DIR` to a new private directory and isolate app data as
for the other release probes. It creates only synthetic multilingual exports,
an expected source and a receipt with file hashes. It refuses an existing output
directory. Independently verify the document contents and render the PDFs;
a successful process exit alone is not release acceptance.
