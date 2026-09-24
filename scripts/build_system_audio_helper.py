"""Compile the bundled Mac audio helper during packaging, never at runtime."""
from pathlib import Path
import argparse,platform,subprocess,sys


def build(output: Path, architecture: str | None = None) -> Path:
    if sys.platform != 'darwin':
        raise RuntimeError('The Mac system-audio helper must be built on a Mac.')
    architecture = architecture or platform.machine()
    if architecture not in {'arm64','x86_64'}:
        raise ValueError('Choose arm64 or x86_64 for the Mac audio helper.')
    source = Path(__file__).resolve().parents[1] / 'knight_flow/native/TalkDATSystemAudio.swift'
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['xcrun','swiftc','-swift-version','5','-warnings-as-errors',
        '-target',architecture+'-apple-macos13.0',str(source),'-o',str(output)],check=True)
    subprocess.run([str(output),'--self-test'],check=True)
    return output


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--architecture',choices=('arm64','x86_64'))
    args=parser.parse_args()
    print(build(args.output,args.architecture))
