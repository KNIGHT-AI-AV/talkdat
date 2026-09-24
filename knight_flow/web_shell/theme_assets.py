"""Allowlisted local material images, loaded in the renderer process on demand.

No paths or arbitrary URLs cross the bridge. Large images never enter the app's
state pipe, and opening settings does not decode all eighty theme variants.
"""
from __future__ import annotations

import base64
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
import threading

from knight_flow.themes import SETTINGS_THEME_FAMILIES, SETTINGS_THEME_GROUPS

ASSET_ROOT = Path(__file__).resolve().parents[1] / 'assets' / 'materials'
MAX_ASSET_BYTES = 2 * 1024 * 1024
MAX_CACHED_BYTES = 8 * 1024 * 1024

# These owner-created materials are shared with D-REC. The provenance manifest
# records source bytes. Existing names and palette preferences stay intact.
SHARED_MATERIALS = {
    'Aqua Noir': 'nami', 'Terminal Rain': 'matrix',
    'Brass Lamp': 'brass', 'Sunset Coast': 'sunset', 'Bone China': 'bone',
    'Moss Stone': 'moss', 'Olive Grove': 'olive', 'Jade Garden': 'jade',
    'Rose Quartz': 'rose', 'Neon Wire': 'neon', 'Plum Velvet': 'plum',
}
ORIGINAL_MATERIALS = {
    'Amber Lantern', 'Fire Opal', 'Rust Belt', 'Paper Press',
    'Emerald Vault', 'Ultraviolet Hour',
}


def material_catalog():
    catalog = {}
    for family in SETTINGS_THEME_FAMILIES:
        for mode in ('Dark', 'Light'):
            if family in SHARED_MATERIALS:
                folder = ASSET_ROOT / 'shared' / SHARED_MATERIALS[family]
                catalog[family + ' ' + mode] = {'preview': folder / 'material.webp', 'full': folder / 'material.webp'}
            elif family in ORIGINAL_MATERIALS:
                extension = '.png' if family == 'Fire Opal' else '.webp'
                path = ASSET_ROOT / 'original-v2' / (family.lower().replace(' ', '-') + extension)
                catalog[family + ' ' + mode] = {'preview': path, 'full': path}
            else:
                slug = family.lower().replace(' ', '-')
                path = ASSET_ROOT / (slug + '-' + mode.lower() + '.png')
                catalog[family + ' ' + mode] = {'preview': path, 'full': path}
    for spec in catalog.values():
        source = spec['full']
        enhanced = ASSET_ROOT / 'enhanced' / (source.parent.name + '-' + source.stem + '.webp')
        if enhanced.is_file():
            spec['preview'] = enhanced
            spec['full'] = enhanced
    return catalog


def material_metadata(family):
    group = next(label for label, families in SETTINGS_THEME_GROUPS if family in families)
    return {'family': family, 'group': group,
            'material_art': family in SHARED_MATERIALS or family in ORIGINAL_MATERIALS,
            'material_note': 'Photographic material'}


class MaterialLibrary:
    def __init__(self, root=ASSET_ROOT, catalog=None):
        self.root = Path(root).resolve()
        self.catalog = material_catalog() if catalog is None else catalog
        self._cache = OrderedDict()
        self._cache_bytes = 0
        self._lock = threading.Lock()

    def read(self, theme, size):
        if type(theme) is not str or type(size) is not str or size not in {'preview', 'full'}:
            raise ValueError('Unknown theme material')
        spec = self.catalog.get(theme)
        if spec is None or size not in spec:
            raise ValueError('Unknown theme material')
        path = Path(spec[size]).resolve()
        if not path.is_relative_to(self.root) or path.suffix not in {'.png', '.webp'}:
            raise ValueError('Unknown theme material')
        with self._lock:
            key = (path, size)
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            # Bound the read itself, including files changed between stat/read.
            with path.open('rb') as stream:
                data = stream.read(MAX_ASSET_BYTES + 1)
            if len(data) > MAX_ASSET_BYTES:
                raise ValueError('Theme material exceeds its limit')
            valid = data.startswith(b'\x89PNG\r\n\x1a\n') if path.suffix == '.png' else data[:4] == b'RIFF' and data[8:12] == b'WEBP'
            if not valid:
                raise ValueError('Theme material has an invalid format')
            if size == 'preview':
                from PIL import Image
                with Image.open(BytesIO(data)) as picture:
                    if picture.width * picture.height > 10_000_000:
                        raise ValueError('Theme material exceeds its pixel limit')
                    picture.thumbnail((512, 256), Image.Resampling.LANCZOS)
                    preview = BytesIO()
                    picture.save(preview, format='PNG' if path.suffix == '.png' else 'WEBP')
                    data = preview.getvalue()
            uri = 'data:image/' + path.suffix[1:] + ';base64,' + base64.b64encode(data).decode('ascii')
            while self._cache and self._cache_bytes + len(uri) > MAX_CACHED_BYTES:
                _, old = self._cache.popitem(last=False)
                self._cache_bytes -= len(old)
            self._cache[key] = uri
            self._cache_bytes += len(uri)
            return uri
