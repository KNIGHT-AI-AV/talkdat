# App preferences

Open **Writing > App preferences** to make an exception to your normal dictation
settings. You can also search for “per app”, “tone” or “learned writing style”.

Choose **Add app**, enter part of its name, and choose the settings that should
change there. For example, `Slack` matches Slack on Windows and Mac. Matching
ignores capitals. The first enabled match wins, so place a specific name above
a broader name with **Move up** and **Move down**. A browser preference applies
to every website in that browser; it does not distinguish individual sites.

**Use default** leaves a setting inherited. Formatting controls the existing
cleanup level. Tone uses the existing AI formatter when available. Language is
a hint for speech recognition; the selected model must support the language,
and some local models detect it themselves. The hint reaches the selected
provider before recording begins. Spoken Enter enables or disables the spoken
command to press Enter. It does not automatically submit every dictation.

The app preference is captured when dictation starts and remains the same
through final formatting. Saving an edit applies it to the next dictation.
Disable a preference to keep it without applying it, or choose **Remove** and
confirm to delete that entry. Failed saves retain the draft. If another window
has changed the preferences, refresh the list before trying to save again;
the editor asks what to do with your draft first.

The editor supports up to 100 saved app preferences. Older custom values and
extra configuration fields are preserved when an entry is edited. Malformed or
oversized older entries are disclosed and kept unchanged. Keep a backup before
recovering those entries.

**Learned writing style** shows local weighted counts from saved text. The
current learner recognizes a small set of English contractions, openers and
connectors, plus sentence length. Manual Fix That rewrites can use the resulting
instruction with your selected local or user-key text provider. It does not
automatically restyle every dictation. At least 20 samples are needed before an
instruction can be produced, and older counts gradually reduce as new text is
saved. **Clear style counts** requires confirmation and preserves History and
app preferences. Later saved text can build the counts again.
