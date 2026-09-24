import os
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(os.environ.get('TALKDAT_MAC_ROOT',Path(__file__).resolve().parents[1]))

def specification():
    hooks=ModuleType('PyInstaller.utils.hooks')
    hooks.collect_all=lambda name:([(name+'/fixture','package/'+name)],[],[name])
    hooks.collect_data_files=lambda name,**kwargs:[(name+'/__init__.py',name)]
    hooks.copy_metadata=lambda name:[(name+'.dist-info',name+'.dist-info')]
    helper=ModuleType('scripts.mac_bundle')
    helper.collect_system_audio=lambda root:[(str(root/'build-mac/native/TalkDATSystemAudio'),'knight_flow/native')]
    modules={'PyInstaller':ModuleType('PyInstaller'),'PyInstaller.utils':ModuleType('PyInstaller.utils'),
             'PyInstaller.utils.hooks':hooks,'scripts.mac_bundle':helper}
    captured={}
    def analysis(*args,**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(pure=[],scripts=[],binaries=kwargs['binaries'],datas=kwargs['datas'])
    objects={'SPECPATH':str(ROOT),'Analysis':analysis}
    objects.update({name:lambda *args,**kwargs:None for name in ('PYZ','EXE','COLLECT','BUNDLE')})
    with patch.dict(sys.modules,modules),patch.object(sys,'path',[str(ROOT),*sys.path]):
        runpy.run_path(str(ROOT/'TalkDat-mac.spec'),init_globals=objects)
    return captured

class MacBundleContractTests(unittest.TestCase):
    def test_pdf_runtime_is_replaceable_and_has_its_licenses(self):
        captured=specification()
        targets={str(destination) for _,destination in captured['datas']}
        self.assertIn('pdf_runtime/fpdf',targets)
        self.assertIn('pdf_runtime/licenses',targets)
        self.assertIn('uharfbuzz',captured['hiddenimports'])
        self.assertIn('fontTools',captured['hiddenimports'])

    def test_runtime_loads_replaceable_pdf_before_frozen_fallback(self):
        captured=specification()
        self.assertIn(str(ROOT/'scripts/pyi_pdf_runtime.py'),captured['runtime_hooks'])

    def test_native_audio_component_is_at_the_adapters_expected_path(self):
        captured=specification()
        self.assertIn((str(ROOT/'build-mac/native/TalkDATSystemAudio'),'knight_flow/native'),captured['binaries'])

if __name__=='__main__':unittest.main()
