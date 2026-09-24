import unittest

from knight_flow.address_text import compose_addresses


class SpokenAddressTests(unittest.TestCase):
    def test_addresses_compose_with_explicit_markers(self):
        for spoken, expected in (
            ("send it to build at knight ai av dot com", "send it to build@knightaiav.com"),
            ("email jane dot doe at example dot org", "email jane.doe@example.org"),
            ("mail first underscore last at example dot com", "mail first_last@example.com"),
            ("the docs are at talk dat dot app slash docs", "the docs are at talkdat.app/docs"),
            ("visit example dot com slash user dash guide", "visit example.com/user-guide"),
            ("visit my dash site dot com", "visit my-site.com"),
            ("the url is docs dot example dot com slash guide slash api", "the url is docs.example.com/guide/api"),
            ("email sam at example dot co dot uk", "email sam@example.co.uk"),
            ("open knight flow slash formatting dot py", "open knight_flow/formatting.py"),
            ("open my underscore app slash main dot py", "open my_app/main.py"),
        ):
            with self.subTest(spoken=spoken):
                self.assertEqual(compose_addresses(spoken), expected)

    def test_written_literals_and_ordinary_prose_remain_intact(self):
        for text in ("meet at the office", "the dot on the page", "there is a slash here", "`send to me at example dot com`", "https://github.com/new_line", "open my project slash main dot py"):
            with self.subTest(text=text):
                self.assertEqual(compose_addresses(text), text)

    def test_explicit_path_alias_supplies_spelling(self):
        self.assertEqual(compose_addresses("open my project slash main dot py", {"my project": "my-project"}), "open my-project/main.py")

    def test_malformed_optional_aliases_do_not_lose_the_dictation(self):
        self.assertEqual(compose_addresses("visit example dot com", []), "visit example.com")
        self.assertEqual(compose_addresses("visit example dot com", ["bad"]), "visit example.com")


if __name__ == "__main__":
    unittest.main()
