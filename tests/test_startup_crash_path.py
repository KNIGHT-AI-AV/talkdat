"""Early crash reports use the chosen data home, including portable installs."""
import ast,builtins,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


class StartupCrashPathTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        self.home=self.root/'home';self.cwd=self.root/'working';self.binary=self.root/'program'
        for path in (self.home,self.cwd,self.binary):path.mkdir()
        self.environment={'APPDATA':str(self.home/'roaming')}
        self.opened=[];self.handler=Mock()

    def run_startup(self,platform='win32',frozen=True,fail_open=False):
        source=Path(__file__).resolve().parents[1]/'talk_dat.py'
        tree=ast.parse(source.read_text(encoding='utf-8'))
        block=next(node for node in tree.body if isinstance(node,ast.Try) and '_crash_log' in ast.unparse(node))
        def full(value):
            path=Path(value)
            return path if path.is_absolute() else self.cwd/path
        def open_log(value,*args,**kwargs):
            if fail_open:raise OSError('synthetic unwritable data home')
            path=full(value);self.opened.append(path)
            stream=builtins.open(path,*args,**kwargs);self.addCleanup(stream.close);return stream
        paths=SimpleNamespace(join=os.path.join,dirname=os.path.dirname,exists=lambda value:full(value).exists(),
                              realpath=lambda value:str(full(value).resolve()),abspath=lambda value:str(full(value).absolute()),
                              expanduser=lambda value:str(self.home)+value[1:] if value.startswith('~') else value)
        operating=SimpleNamespace(name='nt' if platform=='win32' else 'posix',path=paths,environ=self.environment,
                                  makedirs=lambda value,**kwargs:full(value).mkdir(parents=True,exist_ok=kwargs.get('exist_ok',False)))
        system=SimpleNamespace(platform=platform,frozen=frozen,executable=str(self.binary/'TalkDat'),argv=[str(self.binary/'talk_dat.py')])
        context={'_os':operating,'_sys':system,'_faulthandler':self.handler,'open':open_log}
        exec(compile(ast.Module(body=[block],type_ignores=[]),str(source),'exec'),context)

    def test_windows_custom_home_owns_its_crash_report(self):
        self.environment['TALK_DAT_HOME']=str(self.root/'isolated')
        self.run_startup()
        self.assertEqual(self.opened,[self.root/'isolated/crash-traceback.log'])

    def test_mac_custom_home_owns_its_crash_report(self):
        self.environment['TALK_DAT_HOME']=str(self.root/'isolated')
        self.run_startup('darwin')
        self.assertEqual(self.opened,[self.root/'isolated/crash-traceback.log'])

    def test_mac_default_does_not_fall_back_to_working_directory_or_appdata(self):
        self.run_startup('darwin')
        self.assertEqual(self.opened,[self.home/'Library/Application Support/TalkDat/crash-traceback.log'])

    def test_windows_default_keeps_the_existing_roaming_location(self):
        self.run_startup()
        self.assertEqual(self.opened,[self.home/'roaming/TalkDat/crash-traceback.log'])

    def test_portable_frozen_app_keeps_crash_report_beside_its_data(self):
        (self.binary/'portable.flag').touch()
        self.run_startup()
        self.assertEqual(self.opened,[self.binary/'TalkDatData/crash-traceback.log'])

    def test_source_portable_and_custom_home_precedence(self):
        (self.binary/'portable.flag').touch()
        self.environment['TALK_DAT_HOME']='~/custom'
        self.run_startup('darwin',frozen=False)
        self.assertEqual(self.opened,[self.home/'custom/crash-traceback.log'])

    def test_unwritable_crash_report_never_prevents_startup(self):
        self.run_startup(fail_open=True)
        self.handler.enable.assert_not_called()


if __name__=='__main__':unittest.main()
