# Local diagnostic logs

Talk DAT keeps its main diagnostic log, talk-dat.log, in the app data folder.
It records application operations and errors to help troubleshoot a problem.
These files can contain private information. Review anything you choose to
share. Log storage is separate from dictation History, formatting journals and
protected voice recordings, which have their own controls.

The main log keeps up to 2 MiB in the current file and three rotated files,
8 MiB total for those four managed files. Newer entries replace the oldest
rotated file. An individual formatted entry is limited to 64 KiB and marked
when truncated. This is a size limit, not a promise to remove entries after a
fixed number of days.

On first launch after this update, an oversized existing main log or one of
its three rotations keeps its recent tail. The replacement is written before
the older file is replaced. Unrelated exports or copied logs are untouched.
Linked files and unexpected directory targets are refused. If the diagnostic
folder cannot be used, Talk DAT can still start. A later logging failure does
not interrupt dictation or print the failed record to a console.

Clear local data lists the categories it can remove. The main diagnostic log
is outside that operation. Feedback still requires an explicit choice before
including formatting-log excerpts. No server records, subscriptions, licences
or provider policies are changed by this local log limit.
