"""Bounded local backups with SQLite snapshots and checked, reversible restore."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import time
import zipfile

from knight_flow import config

BACKUP_FILES = (
    'config.json', 'pinned.json', 'scratchpad-tabs.json', 'scratchpad.md',
    'history.jsonl', 'history.db', 'full-transcript-history.txt',
    'live-transcript-draft.txt', 'recovered-draft.txt',
)
MAX_BACKUP_MEMBER_BYTES = 256 * 1024 * 1024
MAX_BACKUP_TOTAL_BYTES = 1024 * 1024 * 1024


def _digest(stream):
    stream.seek(0)
    digest = hashlib.sha256()
    while chunk := stream.read(64 * 1024):
        digest.update(chunk)
    stream.seek(0)
    return digest.hexdigest()


def _database_copy(source, destination):
    """SQLite's backup API includes committed WAL pages and preserves open readers."""
    deadline = time.monotonic() + 15
    def progress(_status, _remaining, _total):
        if time.monotonic() > deadline:
            raise ValueError('History is busy. Finish using it, then try the backup again.')
    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as origin:
        with closing(sqlite3.connect(destination, timeout=2)) as target:
            origin.backup(target, pages=256, progress=progress, sleep=0.05)


def _validate_file(path, name):
    if name == 'history.db':
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as database:
            if database.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise ValueError('The backup history database is damaged.')
            columns = {row[1] for row in database.execute('PRAGMA table_info(history)')}
            if not {'id', 'created_at', 'type', 'text', 'original', 'command', 'transform', 'url', 'send_enter', 'extra'} <= columns:
                raise ValueError('The backup does not contain a Talk DAT history database.')
        return
    try:
        def reject_constant(_value):
            raise ValueError('The backup contains a non-finite JSON number.')
        with path.open(encoding='utf-8-sig') as stream:
            if name.endswith('.json'):
                data = json.load(stream, parse_constant=reject_constant)
                expected = list if name == 'pinned.json' else dict
                if type(data) is not expected:
                    raise ValueError('The backup contains an invalid ' + name + '.')
                if name == 'config.json' and any(type(value) is dict and key in data and type(data[key]) is not dict for key, value in config.DEFAULT_CONFIG.items()):
                    raise ValueError('The backup settings contain an invalid section.')
                if name == 'scratchpad-tabs.json':
                    from knight_flow.web_shell.notes_workspace import NotesWorkspace
                    NotesWorkspace(path, path.with_suffix('.unused'), lambda _text: None).load()
                elif name == 'pinned.json' and any(type(row) is not dict or type(row.get('text')) is not str for row in data):
                    raise ValueError('The backup contains invalid pinned entries.')
            elif name == 'history.jsonl':
                for line in stream:
                    if line.strip() and type(json.loads(line, parse_constant=reject_constant)) is not dict:
                        raise ValueError('The backup contains invalid history entries.')
            else:
                while stream.read(64 * 1024):
                    pass
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('The backup contains an unreadable ' + name + '.') from error


def _unpack(stream, stage):
    files, total = [], 0
    with zipfile.ZipFile(stream) as archive:
        for entry in archive.infolist():
            name = entry.filename
            if name not in BACKUP_FILES:
                continue
            if name in files:
                raise ValueError('The backup contains duplicate files. Nothing was restored.')
            mode = entry.external_attr >> 16
            if entry.is_dir() or stat.S_ISLNK(mode) or entry.flag_bits & 1:
                raise ValueError('Choose an unencrypted Talk DAT backup with regular files.')
            total += entry.file_size
            if entry.file_size > MAX_BACKUP_MEMBER_BYTES or total > MAX_BACKUP_TOTAL_BYTES:
                raise ValueError('This backup is too large to restore here (256 MB per file, 1 GB total).')
            destination = stage / name
            written = 0
            with archive.open(entry) as source, destination.open('xb') as target:
                config._restrict_to_owner(destination, 0o600)
                while chunk := source.read(64 * 1024):
                    written += len(chunk)
                    if written > entry.file_size or written > MAX_BACKUP_MEMBER_BYTES:
                        raise ValueError('The backup file size does not match its contents.')
                    target.write(chunk)
                target.flush(); os.fsync(target.fileno())
            _validate_file(destination, name)
            files.append(name)
    if not files:
        raise ValueError('No Talk DAT settings, notes or history were found in this backup.')
    return files, total


def inspect_backup(path):
    """Read and validate every supported file before showing a restore preview."""
    with Path(path).open('rb') as stream, tempfile.TemporaryDirectory(prefix='talkdat-backup-check-') as directory:
        digest = _digest(stream)
        files, total = _unpack(stream, Path(directory))
        if _digest(stream) != digest:
            raise ValueError('The backup changed while it was being checked. Choose it again.')
        return {'files': files, 'bytes': total, 'digest': digest}


def export_backup(path):
    from knight_flow.history import _sqlite_lock
    root, path = config.app_dir(), Path(path)
    if path.resolve() in {(root / name).resolve() for name in BACKUP_FILES}:
        raise ValueError('Save the backup as a separate ZIP file.')
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '-', suffix='.tmp', dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        with tempfile.TemporaryDirectory(prefix='talkdat-backup-') as directory:
            with config._SAVE_LOCK, _sqlite_lock, zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
                for name in BACKUP_FILES:
                    source = root / name
                    if source.is_symlink():
                        raise ValueError('A backup source is a link. Restore a regular local file before trying again.')
                    if not source.exists():
                        continue
                    if name == 'history.db':
                        snapshot = Path(directory) / name
                        _database_copy(source, snapshot)
                        source = snapshot
                    if source.stat().st_size > MAX_BACKUP_MEMBER_BYTES:
                        raise ValueError('A backup file exceeds 256 MB. Export large history separately.')
                    _validate_file(source, name)
                    archive.write(source, name)
            # Check CRC, formats, limits and actual decompression before replacing
            # a previous good backup at the requested destination.
            inspect_backup(temporary)
            with temporary.open('r+b') as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            config._restrict_to_owner(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def restore_backup(path, *, expected_digest=None):
    from knight_flow.history import _sqlite_lock
    root = config.app_dir().resolve()
    # Keep rollback copies on the same filesystem, with the existing app's
    # owner-only permissions. Cleanup is withheld if rollback itself fails.
    directory = Path(tempfile.mkdtemp(prefix='.restore-', dir=root))
    incoming, previous = directory / 'incoming', directory / 'previous'
    incoming.mkdir(); previous.mkdir()
    retain_recovery = False
    try:
        with Path(path).open('rb') as stream:
            digest = _digest(stream)
            if expected_digest is not None and digest != expected_digest:
                raise ValueError('The backup changed after the preview. Choose it again.')
            files, _total = _unpack(stream, incoming)
            if _digest(stream) != digest:
                raise ValueError('The backup changed while it was being read. Nothing was restored.')
        with config._SAVE_LOCK, _sqlite_lock:
            raw_database = False
            for name in files:
                target = root / name
                if target.is_symlink() or target.resolve().parent != root:
                    raise ValueError('A restore destination is a link. Nothing was restored.')
                if target.exists():
                    if name == 'history.db':
                        try:
                            _database_copy(target, previous / name)
                        except sqlite3.DatabaseError as error:
                            if (getattr(error, 'sqlite_errorcode', 0) & 255) not in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
                                raise
                            # Recovery must also work when the CURRENT database
                            # is corrupt. Preserve its exact bytes and sidecars;
                            # only this case replaces the file instead of using
                            # SQLite's live-reader-safe online restore.
                            raw_database = True
                            shutil.copy2(target, previous / name)
                            for suffix in ('-wal', '-shm'):
                                sidecar = root / (name + suffix)
                                if sidecar.is_symlink():
                                    raise ValueError('A database recovery file is a link. Nothing was restored.')
                                if sidecar.exists(): shutil.copy2(sidecar, previous / sidecar.name)
                    else: shutil.copy2(target, previous / name)
            applied = []
            try:
                for name in files:
                    # Include the attempted file so a partial SQLite operation
                    # or a platform-specific replace failure is rolled back too.
                    applied.append(name)
                    if name == 'history.db' and not raw_database: _database_copy(incoming / name, root / name)
                    else: os.replace(incoming / name, root / name)
                    if name == 'history.db' and raw_database:
                        for suffix in ('-wal', '-shm'): (root / (name + suffix)).unlink(missing_ok=True)
                    config._restrict_to_owner(root / name, 0o600)
            except BaseException as error:
                failures = []
                for name in reversed(applied):
                    try:
                        if (previous / name).exists():
                            if name == 'history.db' and not raw_database: _database_copy(previous / name, root / name)
                            else: os.replace(previous / name, root / name)
                            if name == 'history.db' and raw_database:
                                for suffix in ('-wal', '-shm'):
                                    saved = previous / (name + suffix)
                                    if saved.exists(): os.replace(saved, root / saved.name)
                                    else: (root / saved.name).unlink(missing_ok=True)
                        else:
                            (root / name).unlink(missing_ok=True)
                    except Exception:
                        failures.append(name)
                if failures:
                    retain_recovery = True
                    raise OSError('Restore failed and some previous files need recovery. They are kept in ' + str(previous)) from error
                raise
            if 'config.json' in files:
                config._RESTORED_CONFIG_ROOTS.add(root)
        return files
    finally:
        if not retain_recovery:
            shutil.rmtree(directory)
