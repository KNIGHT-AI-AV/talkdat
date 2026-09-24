"""Material access must not turn the renderer bridge into a file reader."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from knight_flow.web_shell.shell_host import _RendererApi, bundled_html

ROOT = Path(__file__).resolve().parents[1]


class MaterialBridgeTests(unittest.TestCase):
    def api(self, trusted=True):
        api = _RendererApi(Mock())
        api._guard_ready = True
        api._window = Mock()
        api._window.get_current_url.return_value = 'about:blank' if trusted else 'https://example.org'
        return api

    def test_a_bundled_material_arrives_without_using_the_engine_pipe(self):
        api = self.api()
        answer = api.request('theme_asset', {'theme': 'Flow Dark', 'size': 'preview'})
        self.assertTrue(answer['ok'], answer)
        uri = answer['result']['uri']
        self.assertTrue(uri.startswith('data:image/webp;base64,'))
        self.assertTrue(base64.b64decode(uri.split(',', 1)[1]).startswith(b'RIFF'))
        api._connection.send_bytes.assert_not_called()

    def test_foreign_pages_cannot_read_even_an_allowed_material(self):
        answer = self.api(False).request('theme_asset', {'theme': 'Flow Dark', 'size': 'preview'})
        self.assertFalse(answer['ok'])

    def test_only_known_themes_and_exact_payloads_are_allowed(self):
        for payload in (None, [], {'theme': '../../config.json', 'size': 'preview'},
                        {'theme': 'Flow Dark', 'size': '../full'},
                        {'theme': 'Flow Dark', 'size': 'preview', 'path': 'config.json'},
                        {'theme': ['Flow Dark'], 'size': 'preview'}):
            with self.subTest(payload=payload):
                self.assertFalse(self.api().request('theme_asset', payload)['ok'])

    def test_materials_do_not_inflate_the_bundled_document(self):
        document = bundled_html(ROOT / 'knight_flow/web_shell/shell_assets')
        self.assertLess(len(document.encode()), 2 * 1024 * 1024)
        self.assertIn('img-src data:', document)
        self.assertIn("connect-src 'none'", document)

    def test_oversize_and_escaping_assets_are_rejected_before_encoding(self):
        from knight_flow.web_shell.theme_assets import MaterialLibrary, MAX_ASSET_BYTES
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / 'outside.png'
            outside.write_bytes(b'private-data')
            assets = root / 'assets'
            assets.mkdir()
            large = assets / 'large.png'
            with large.open('wb') as stream:
                stream.truncate(MAX_ASSET_BYTES + 1)
            library = MaterialLibrary(assets, {'bad': {'preview': outside}, 'large': {'preview': large}})
            for name in ('bad', 'large'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    library.read(name, 'preview')

    def test_every_material_decodes_and_the_cache_stays_bounded(self):
        from knight_flow.web_shell.theme_assets import MaterialLibrary, MAX_CACHED_BYTES
        from knight_flow.themes import SETTINGS_THEME_FAMILIES
        library = MaterialLibrary()
        self.assertEqual(len(library.catalog), len(SETTINGS_THEME_FAMILIES) * 2)
        for name in library.catalog:
            for size in ('preview', 'full'):
                with self.subTest(theme=name, size=size):
                    self.assertTrue(library.read(name, size).startswith('data:image/'))
                    self.assertLessEqual(library._cache_bytes, MAX_CACHED_BYTES)

    def test_shared_material_bytes_match_the_recorded_owner_assets(self):
        for folder in ('shared', 'original-v2'):
            root = ROOT / 'knight_flow/assets/materials' / folder
            manifest = json.loads((root/'provenance.json').read_text(encoding='utf-8'))
            for item in manifest['files']:
                path = root / item['file']
                with self.subTest(asset=item['file']):
                    digest = 'sha256-' + base64.b64encode(hashlib.sha256(path.read_bytes()).digest()).decode('ascii')
                    self.assertEqual(digest, item['integrity'])

    def test_gallery_previews_have_bounded_decoded_dimensions(self):
        from io import BytesIO
        from PIL import Image
        from knight_flow.web_shell.theme_assets import MaterialLibrary
        library = MaterialLibrary()
        for theme in ('Flow Dark', 'Brass Lamp Dark', 'Emerald Vault Light'):
            preview = base64.b64decode(library.read(theme, 'preview').split(',',1)[1])
            full = base64.b64decode(library.read(theme, 'full').split(',',1)[1])
            self.assertLess(len(preview), len(full))
            with Image.open(BytesIO(preview)) as picture:
                self.assertLessEqual(picture.width,512)
                self.assertLessEqual(picture.height,256)

    def test_build_bundles_shared_materials(self):
        spec = (ROOT / 'Talk Dat!.spec').read_text(encoding='utf-8')
        self.assertIn('"knight_flow/assets/materials/shared"', spec)
        self.assertIn('"knight_flow/assets/materials/original-v2"', spec)
        self.assertIn('"knight_flow/assets/materials/enhanced"', spec)

    def test_enhanced_art_has_verified_sources_and_bounded_decoded_size(self):
        from PIL import Image
        root=ROOT/'knight_flow/assets/materials'
        manifest=json.loads((root/'enhanced/provenance.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['assets']),54)
        for item in manifest['assets']:
            with self.subTest(asset=item['asset']):
                for path,key in ((item['asset'],'integrity'),(item['source'],'source_integrity')):
                    digest='sha256-'+base64.b64encode(hashlib.sha256((root/path).read_bytes()).digest()).decode('ascii')
                    self.assertEqual(digest,item[key])
                with Image.open(root/item['asset']) as picture:
                    self.assertGreaterEqual(min(picture.size),704)
                    self.assertLess(picture.width*picture.height,10_000_000)


if __name__ == '__main__':
    unittest.main()
