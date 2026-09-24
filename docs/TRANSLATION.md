# Translation

Translate a passage, then copy the result into the place you need it. Desktop
translation runs through Ollama on your computer. Manual translation works
without turning on automatic translation for every dictation.

Right-click the Pill and choose **Translate**, or open **Settings > Writing >
Translation**. Install Ollama, choose a translation model and download it, then
choose the source and target languages. **Follow dictation language** uses your
configured speech language; it does not detect the language of a pasted passage.

The source and result appear beside each other, or one above the other in a
narrow window. **Swap** exchanges the languages and uses the current result as
the next source. **Copy result** copies the complete result. If you edit the
source or options, an older result is labelled **Previous result** until you
translate again. Ctrl+Enter on Windows or Command+Enter on Mac starts translation.

Drafts stay available when you visit another page or close and reopen Settings
during the same Talk DAT session. They are not saved across an app restart.
Completed results follow your History setting after the interface confirms
that they belong to the current passage. Cancelled or replaced requests cannot
save a late result. Cancelling may take a moment while the current local model
request finishes; your source and previous result stay available.

**Speak and translate** appends speech to the current source. Choose **Finish
speaking** to translate it. Leaving while recording cancels that page's capture.
It cannot redirect the words into another application.

**Model and passage options** contains tone, line-break preservation, model
readiness, engine setup and model downloads. A model download shows its size
before confirmation and can continue while you use another page.

**Automatic translation and saved defaults** contains settings for future
sessions and automatic dictation, including the glossary. Enter each source
term and preferred translation in its own fields, then choose **Save changes**.
Existing extra glossary details remain attached to their entries. A passage can
contain up to 64,000 characters; larger results are delivered to the interface
in smaller pieces so copying still includes the complete text.

On Mac, install Ollama in Applications and open it once. Talk DAT recognises the
application even when its command-line shortcut is not installed. The official
[Mac instructions](https://docs.ollama.com/macos) explain installation. On
Windows, the translation setup can use Windows Package Manager or open the
official download page.

The default TranslateGemma 4B download is about 3.3 GB. The optional 12B and 27B
models are about 8.1 GB and 17 GB. Larger models need more memory and storage;
their names do not guarantee a better translation of every passage. Downloads
start only when you choose them. The [official model listing](https://ollama.com/library/translategemma)
has the model details.

Automatic dictation translation is a separate opt-in setting. It translates
after dictation cleanup and uses the normal insertion path. If translation
fails, Talk DAT keeps and delivers the cleaned source text instead.

Links, email addresses, prices, signed numbers, percentages, versions and
literal placeholder text are protected during translation. A changed or missing
protected item stops the result. Long passages keep whole words and protected
links at chunk boundaries. Repeated sentences are translated once within a
request and restored in their original count and order. Surrounding spaces are
kept; formatting preservation also checks the number of line breaks.

An incomplete model response or an unexpected repetition stops the result
instead of presenting it as finished. These checks cannot judge every nuance,
obligation or deadline. Review the result alongside the original, particularly
when the exact meaning matters. Language-pair quality varies.

There is no desktop managed translation fallback. An older setting requesting
that removed route produces an explicit error. This does not change the account
or paid-feature policy elsewhere in Talk DAT. iPhone translation is a separate
implementation.

Language requests open a local email draft to `Build@KnightAIAV.com`. You review
and send that draft yourself; it does not automatically attach a transcript.
