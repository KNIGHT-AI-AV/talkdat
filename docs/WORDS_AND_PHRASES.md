# Words and phrases

Open **Writing > Words**, or choose **Words & Phrases** from Tools or the Pill
menu. Words, replacements and snippets now share one searchable workspace.

Choose an entry to edit it, or use Add. Save entry applies your changes to the
next dictation. Ctrl+Enter on Windows or Command+Enter on Mac also saves.
Leaving an unsaved entry offers Keep editing, Discard draft or Save entry.
A failed save keeps your text in the editor.

- **Words:** personal names, brands and spellings. Optional sounds-like
  spellings go on separate lines, up to eight per entry.
- **Replacements:** an exact phrase that is heard and the text to use instead.
  An empty replacement removes that phrase.
- **Snippets:** a distinctive spoken trigger and the text it inserts. Line
  breaks, Unicode and spaces in the saved text are preserved. Disable a snippet
  to keep it saved without expanding it.

Search includes pronunciation aliases and the full saved snippet text. Results
are shown in pages of 40. Delete asks before removing the selected entry.
Older entries that this editor cannot safely interpret remain in your saved
configuration and are disclosed in the list; export a pack before reviewing them.

If another window changes vocabulary while you edit, your draft stays here.
Refresh list can update the revision when the selected saved entry itself is
unchanged. If that entry changed too, copy any draft text you need before
opening its latest saved version.

## Learning and suggestions

Expand **Learning, suggestions and vocabulary packs**. The copied-word setting
has three choices:

- **Off:** do not learn from copied words.
- **Ask before adding:** offer qualifying copied words for approval.
- **Learn distinctive spellings; ask about other words:** unusual spellings
  can be learned immediately with the Pill's undo option. Repeated ordinary
  words are offered for approval.

When enabled, Talk DAT checks words you copy after dictation. These checks run
on this computer. Explicit Fix That spelling suggestions still require acceptance.
Suggest from history offers names used repeatedly in saved dictations. Choosing
a suggestion opens a draft; Save entry is what adds it. Deliberately deleted
words are not offered again or silently re-added from old pronunciation clips.
Adding that spelling yourself clears its dismissal.

## Packs

Import pack opens a local file picker and then previews how many entries will
be added. Existing entries are kept, and duplicate spellings, replacement
phrases and snippet triggers are skipped. Medical, legal, aviation and military
packs use the same preview. Confirm within five minutes; a vocabulary change
requires another preview so newer entries cannot be overwritten.

Export pack includes words, sounds-like spellings, trained pronunciation
metadata, replacements and snippets. It does not include account settings,
recordings or downloaded speech models. Review private names and snippet text
before sharing a pack. Packs are JSON files; you do not need to edit JSON to use
the workspace. Import accepts files up to 8 MB and up to 5,000 entries per
collection after merging. The editor accepts 512 characters for a spelling or
trigger and 32,000 characters for replacement or snippet text.

## Pronunciation practice

Save and select a word, then choose **Record pronunciation**. Say the word
three times when prompted. Each take lasts 2½ seconds, with a short pause
between takes. Practice uses the microphone selected in Dictation settings and
the local speech model. Install a local model before practising.

Cancel practice stops the capture and leaves the saved word unchanged. Panic
also stops practice. The microphone remains listed as active until its handle
closes; a failed close stays visible and Panic can retry it. Dictation waits
until practice finishes or is cancelled.

After all takes finish, sounds-like spellings are saved on this computer. Your
handwritten aliases are preserved. A vocabulary change during practice stops
the save so a newer edit cannot be overwritten. The recordings remain local
for future local-model changes. If they cannot be kept, the result says so.
An existing pronunciation folder stays readable, and distinct non-Latin names
now have separate recording locations.

The automated checks use isolated files and synthetic microphone input. Actual
microphone timing, recognition accuracy and the final installed Mac and Windows
packages still require their separate acceptance checks.
