"""Resumable local Scribe transcription with explicit gaps and durable words."""
from __future__ import annotations
import hashlib,json,os,tempfile,wave
from dataclasses import dataclass,field
from pathlib import Path
from .scribe import Chunk,chunk_wav_for_transcription,merge_turns,heuristic_summary,render_notes

LABELS = {'you': 'Microphone', 'them': 'System audio'}
MAX_LEDGER_BYTES = 8_000_000


def _save_ledger(path, value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')
    if len(raw) > MAX_LEDGER_BYTES:
        raise ValueError('This transcript reached its recovery-file limit. The original audio is kept.')
    descriptor, temporary = tempfile.mkstemp(prefix='.transcript-', suffix='.tmp', dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


@dataclass
class TranscriptResult:
    chunks: list[Chunk] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    completed: int = 0
    retried: int = 0
    reused: int = 0
    gaps: set = field(default_factory=set)

    @property
    def turns(self):
        return merge_turns(self.chunks)


def transcribe_tracks(tracks, recognize, *, folder, identity, offsets=None, cancelled=None, progress=None, retry_empty=False):
    """Call recognize(PCM16 mono 16k) only for missing or failed sections.

    Identity must describe the local model and language, with no credential.
    Each original PCM section has its own digest, so changed recordings cannot
    silently reuse an earlier transcript. Recognition errors remain visible.
    """
    offsets = offsets or {}
    path = Path(folder) / 'transcript-v1.json'
    ledger = {'version': 1, 'identity': str(identity), 'parts': {}}
    if path.exists():
        if path.stat().st_size > MAX_LEDGER_BYTES:
            raise ValueError('Saved transcription progress is too large to read safely. The original audio is kept.')
        try:
            previous = json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):
            raise ValueError('Saved transcription progress could not be read. The original file and audio are kept.') from None
        if not isinstance(previous,dict) or previous.get('version') != 1 or not isinstance(previous.get('parts'),dict):
            raise ValueError('Saved transcription progress is not a supported format. The original file and audio are kept.')
        if previous.get('identity') == str(identity):
            ledger = previous
    result = TranscriptResult()
    for track in ('you', 'them'):
        if track not in tracks:
            continue
        try:
            for start, pcm in chunk_wav_for_transcription(Path(tracks[track])):
                if cancelled is not None and cancelled.is_set():
                    result.issues.append('Transcription paused. Saved progress and original audio are kept for retry.')
                    return result
                key = f'{track}:{start}'
                digest = hashlib.sha256(pcm).hexdigest()
                item = ledger['parts'].get(key)
                usable = isinstance(item,dict) and item.get('digest') == digest and item.get('ok') is True and isinstance(item.get('text'),str)
                if usable and retry_empty and not item['text'].strip():usable=False
                if usable:
                    text = item['text']; result.reused += 1
                else:
                    result.retried += 1
                    try:
                        text = recognize(pcm)
                        if not isinstance(text,str):
                            raise ValueError('Recognition did not return text.')
                        item = {'digest':digest,'ok':True,'text':text}
                    except Exception:
                        text = ''
                        item = {'digest':digest,'ok':False,'text':''}
                    ledger['parts'][key] = item
                    try:
                        _save_ledger(path,ledger)
                    except Exception:
                        # Words still reach the result if recovery storage fails.
                        result.chunks.append(Chunk(LABELS[track],float(start)+float(offsets.get(track,0)),text))
                        result.issues.append('Transcription progress could not be saved. Copy or save the available words; original audio is kept.')
                        return result
                absolute = float(start) + float(offsets.get(track,0))
                if item['ok'] is not True:
                    result.gaps.add((LABELS[track],absolute))
                    marker = f'Transcription unavailable near {int(absolute)//60:02d}:{int(absolute)%60:02d}. Original audio is retained.'
                    text = '[' + marker + ']'
                    result.issues.append(f'{LABELS[track]}: {marker}')
                else:
                    result.completed += 1
                result.chunks.append(Chunk(LABELS[track],absolute,text))
                if progress is not None:
                    progress(result)
        except (OSError,EOFError,ValueError,wave.Error):
            result.issues.append(f'{LABELS[track]} recording could not be read completely. Its original file is kept.')
    return result


def notes_body(result, when, *, summarize=None, recording_issues=()):
    turns = result.turns
    spoken = merge_turns([chunk for chunk in result.chunks if (chunk.speaker,chunk.start) not in result.gaps])
    summary = heuristic_summary(spoken)
    label = 'Selected lines'
    warnings = list(recording_issues) + list(result.issues)
    transcript = '\n'.join(f'{speaker}: {text}' for speaker,text in spoken)
    if summarize is not None and spoken:
        if warnings:
            warnings.append('The summary uses selected lines because parts of this recording need review.')
        elif len(transcript) > 38000:
            warnings.append('The conversation exceeds the summary input limit. Selected lines are shown; the full transcript remains below.')
        else:
            try:
                polished = summarize(transcript)
                if not isinstance(polished,str) or not polished.strip():
                    raise ValueError('No summary returned')
                points = [line.strip('-* ').strip() for line in polished.splitlines() if line.strip()]
                if points:
                    summary = points[:6]; label = 'AI summary'
            except Exception:
                warnings.append('The writing model did not return a summary. Selected lines are shown instead.')
    body = render_notes(turns,summary,when)
    body = body.replace('## Summary\n','## '+label+'\n',1)
    details = 'Sources label audio tracks, not identified speakers. Sections are ordered in approximate 30-second blocks.\n'
    if warnings:
        details += '\n## Review needed\n\n' + '\n'.join('- '+message for message in dict.fromkeys(warnings)) + '\n'
    position = body.find('\n## ')
    if position < 0:
        return body + '\n' + details
    return body[:position] + '\n' + details + body[position:]
