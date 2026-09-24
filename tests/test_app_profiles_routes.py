import unittest
from tests import test_web_shell_app


class AppPreferenceRouteTests(unittest.TestCase):
    def test_preferences_are_discoverable_as_a_shared_writing_page(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        page=next(page for page in shell.backend.snapshot()['pages'] if page['id']=='app-profiles')
        self.assertIn('per app',page['keywords'])
        self.assertIn('learned writing style',page['keywords'])
    def test_shared_bridge_reads_app_preferences_without_a_native_dialog(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        app.config['profiles']=[{'match':'Slack','tone':'friendly'}]
        result=shell.backend.handle('workspace',{'area':'app-profiles','operation':'list'})
        self.assertEqual(result['entries'][0]['record']['tone'],'friendly')


if __name__=='__main__':unittest.main()
