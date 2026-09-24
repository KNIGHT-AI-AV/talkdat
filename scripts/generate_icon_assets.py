from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "knight_flow" / "assets"
TALK_STONE = ROOT / "branding" / "talk-stone" / "talk-stone-transparent.png"


def resample() -> int:
    return getattr(Image.Resampling, "LANCZOS", Image.LANCZOS)


def save_png(source: Image.Image, path: Path, size: int) -> None:
    image = source.resize((size, size), resample())
    image.save(path, compress_level=3)


def save_ico(source: Image.Image, path: Path) -> None:
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    source.save(path, sizes=sizes)


def save_assets() -> None:
    if not TALK_STONE.exists():
        raise FileNotFoundError(f"Talk Stone source image not found: {TALK_STONE}")
    ASSETS.mkdir(parents=True, exist_ok=True)
    source = Image.open(TALK_STONE).convert("RGBA")

    save_png(source, ASSETS / "app_icon.png", 1024)
    save_png(source, ASSETS / "logo.png", 1024)
    save_png(source, ASSETS / "favicon.png", 256)

    icon_source = source.resize((256, 256), resample())
    save_ico(icon_source, ASSETS / "app_icon.ico")
    save_ico(icon_source, ASSETS / "logo.ico")
    save_ico(icon_source, ASSETS / "favicon.ico")

    print("Updated Talk Stone icon assets:")
    for name in ("app_icon.png", "logo.png", "favicon.png", "app_icon.ico", "logo.ico", "favicon.ico"):
        path = ASSETS / name
        print(f"- {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    save_assets()
