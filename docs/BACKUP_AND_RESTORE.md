# Back up and restore your Talk DAT data

Open **Tools > Back up your data** to save a ZIP on this computer. Finish any
recording first. Choose somewhere you will be able to find again.

The backup includes saved items that exist on this computer:

- Settings, your vocabulary, replacements and voice snippets.
- Notes, including an older scratchpad that has not been converted to tabs.
- Pinned dictations, text history and the full transcript archive.
- The last live text draft and recovered text draft, when present.

Both text-file history and database history are included. The database is
copied as a consistent snapshot, including words that have already been saved.

Audio recordings, pronunciation recordings, downloaded models and system
credential-store keys are not included. Keep recordings you need separately.
On a different computer, you may need to sign in, enter provider keys and
choose its microphone again. Treat the ZIP as private: it contains your text
and settings and is not encrypted. Older settings can also contain keys.

To restore, open **Tools > Restore a backup** and choose the ZIP. Talk DAT
checks the saved files and shows which items it will replace. Items absent
from the backup stay as they are. Choose **Keep current data** to cancel or
**Restore and quit** to continue, then open Talk DAT again. Save or discard
any open settings changes before restoring.

A failed check changes nothing. A failed replacement attempts to restore the
previous files. If that recovery also fails, the error identifies the folder
where the previous copies remain. A failed export keeps an existing backup at
the selected destination intact.

Backups support up to 256 MB per saved file and 1 GB in total. For larger text
history, use the text or Markdown export in History. The ZIP format remains
compatible with earlier Talk DAT backups containing the original supported
settings, pins, notes and text-history files.
