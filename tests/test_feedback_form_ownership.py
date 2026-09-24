import ast,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

SOURCE=Path(__file__).resolve().parents[1]/'knight_flow/overlay.py'


class NativeFeedbackOwnershipTests(unittest.TestCase):
    def compose(self):
        source=ast.parse(SOURCE.read_text(encoding='utf-8'))
        parent=next(node for node in ast.walk(source) if isinstance(node,ast.FunctionDef) and node.name=='open_feedback_form')
        method=next(node for node in ast.walk(parent) if isinstance(node,ast.FunctionDef) and node.name=='compose')
        owner=threading.get_ident();errors=[];workers=[];callbacks=[]
        def value(text):
            def read(*args):
                if threading.get_ident()!=owner:raise RuntimeError('Tk value read on worker')
                return text
            return SimpleNamespace(get=read)
        def start_thread(*,target,**kwargs):
            def run():
                try:target()
                except Exception as error:errors.append(error)
            thread=threading.Thread(target=run,**kwargs);workers.append(thread);return thread
        callback=Mock(return_value=False);window=SimpleNamespace(alive=True,winfo_exists=lambda:window.alive)
        def configure(**kwargs):
            if not window.alive:raise RuntimeError('Destroyed form touched')
        button=SimpleNamespace(configure=Mock(side_effect=configure))
        overlay=SimpleNamespace(callbacks={'feedback':callback},root=SimpleNamespace(after=lambda delay,fn:callbacks.append(fn)),set_state=Mock(),_request_utility_close=Mock())
        namespace={'self':overlay,'mode':'feature','title_var':value('A synthetic idea'),'details':value('Synthetic detail'),
                   'contact_var':value('test@example.invalid'),'logs_var':value(False),'send_button':button,'window':window,
                   'threading':SimpleNamespace(Thread=start_thread)}
        exec(compile(ast.Module(body=[method],type_ignores=[]),str(SOURCE),'exec'),namespace)
        namespace['compose']()
        for worker in workers:worker.join(2)
        return callback,window,callbacks,errors
    def test_contact_and_log_consent_are_captured_before_the_worker(self):
        callback,window,callbacks,errors=self.compose()
        self.assertEqual(errors,[])
        callback.assert_called_once_with('feature','A synthetic idea','Synthetic detail','test@example.invalid','',include_logs=False)
    def test_a_closed_form_is_not_touched_by_late_completion(self):
        callback,window,callbacks,errors=self.compose()
        window.alive=False
        for callback in callbacks:callback()

if __name__=='__main__':unittest.main()
