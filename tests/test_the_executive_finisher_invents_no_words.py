"""X-437: Executive may change register, never invent a word.

The three entries from the founder's formatting journal on 2026-09-04 at
18:05, verbatim. The first is the fault: the local 4B finisher turned "I boot
up" into "IPad up" and Executive's validator let it through, because rewrite
mode suspends the word-retention floor by design. The other two are Executive
doing what X-125 asks of it (register up), and they stay accepted: this guard
is about invented words, not about the tier's contract. (Profanity out is no
longer Executive's call since 2026-09-23; see the profanity_removed check.)
"""
from __future__ import annotations

import unittest

from knight_flow.formatting import _invented_inner_capital_words, _valid_formatter_output

BOOT_UP_RAW = (
    "Massive, massive, massive talk DAT lag being caused the second I boot up talk DAT. "
    "Number two, the fucking context menu is retarded."
)
# The journal's final, minus the list the refine stage inherited from the
# stage before it (list structure is judged by a different guard).
BOOT_UP_SHIPPED = (
    "Massive, massive, massive talk DAT lag being caused the second IPad up talk DAT. "
    "Number two, the fucking context menu is retarded."
)


class TheExecutiveFinisherInventsNoWords(unittest.TestCase):
    def test_ipad_was_never_said(self) -> None:
        self.assertEqual(_invented_inner_capital_words(BOOT_UP_RAW, BOOT_UP_SHIPPED), ["IPad"])
        self.assertFalse(_valid_formatter_output(BOOT_UP_RAW, BOOT_UP_SHIPPED, preserve_meaning=False, rewrite_mode=True))

    def test_the_same_dictation_without_the_invention_passes(self) -> None:
        honest = BOOT_UP_SHIPPED.replace("IPad up", "I boot up")
        self.assertEqual(_invented_inner_capital_words(BOOT_UP_RAW, honest), [])
        self.assertTrue(_valid_formatter_output(BOOT_UP_RAW, honest, preserve_meaning=False, rewrite_mode=True))

    def test_register_changes_are_still_executive_business(self) -> None:
        # 2026-09-23, the owner's data-loss contract: profanity is the
        # speaker's and stays unless the censor_profanity setting is on, in
        # both finishes. X-437 accepted "profanity out" as Executive's job;
        # that part of this test is reversed on purpose.
        self.assertFalse(
            _valid_formatter_output(
                "And this shit didn't even format.", "This formatting failed.", preserve_meaning=False, rewrite_mode=True
            )
        )
        self.assertTrue(
            _valid_formatter_output(
                "And this shit didn't even format.", "This formatting failed.", preserve_meaning=False,
                rewrite_mode=True, censor_profanity=True,
            )
        )
        self.assertTrue(
            _valid_formatter_output(
                "Just as a heads up.", "As a preliminary notice,", preserve_meaning=False, rewrite_mode=True
            )
        )

    def test_brands_the_speaker_said_may_be_written_properly(self) -> None:
        self.assertEqual(
            _invented_inner_capital_words("we ship talk dat and d rec on open router", "We ship TalkDat and D-REC on OpenRouter."),
            [],
        )
        self.assertEqual(_invented_inner_capital_words("the iphone build is out", "The iPhone build is out."), [])

    def test_a_brand_never_said_is_caught_even_with_hyphens(self) -> None:
        self.assertEqual(
            _invented_inner_capital_words("send the numbers tonight", "Send the numbers via e-Mail tonight."), ["e-Mail"]
        )


if __name__ == "__main__":
    unittest.main()
