"""Compile and exercise the audio-only helper before adding it to the bundle."""
from pathlib import Path
import os
import platform
import subprocess
import tempfile


def collect_system_audio(root: Path):
    if platform.system() != 'Darwin':
        raise RuntimeError('Build the Mac audio helper on macOS.')
    architecture = platform.machine()
    if architecture not in {'arm64', 'x86_64'}:
        raise RuntimeError('Unsupported Mac build architecture.')
    source = root / 'knight_flow/native/TalkDATSystemAudio.swift'
    folder = root / 'build-mac/native'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'TalkDATSystemAudio'
    with tempfile.TemporaryDirectory(prefix='audio-helper-', dir=folder) as temporary:
        candidate = Path(temporary) / target.name
        subprocess.run([
            'xcrun', 'swiftc', '-O', '-target', architecture + '-apple-macosx14.0',
            str(source), '-framework', 'ScreenCaptureKit', '-framework', 'AVFoundation',
            '-framework', 'CoreMedia', '-o', str(candidate),
        ], check=True)
        # This path exercises conversion only: no audio capture or permission prompt.
        subprocess.run([str(candidate), '--self-test'], check=True)
        os.chmod(candidate, 0o755)
        os.replace(candidate, target)
    return [(str(target), 'knight_flow/native')]
