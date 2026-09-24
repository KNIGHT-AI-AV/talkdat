from __future__ import annotations

import unittest

from knight_flow.text_pipeline import apply_vocabulary_terms
from knight_flow.vocabulary import Term, apply_vocabulary, parse_terms, similarity, sound_key


class TheFailuresThisWasBuiltForTests(unittest.TestCase):
    """The two cases that motivated the feature, kept as the specification.

    Both come from real dictation. A recognizer writes what it hears using
    ordinary English spelling, so an unknown name becomes the nearest common
    words -- and the two spellings then share almost no letters, which is why
    ordinary text matching cannot repair it and phonetic matching can.
    """

    def test_a_name_heard_as_three_common_words(self) -> None:
        """Mayowa is heard as "my yo wa"; no plain string match would find it."""
        out = apply_vocabulary("I was talking to my yo wa about the release", [Term("Mayowa")])
        self.assertEqual(out, "I was talking to Mayowa about the release")

    def test_the_same_name_spelled_a_different_plausible_way(self) -> None:
        out = apply_vocabulary("my name is maiowa", [Term("Mayowa")])
        self.assertEqual(out, "my name is Mayowa")

    def test_a_product_name_heard_as_a_sentence_fragment(self) -> None:
        """"Talk DAT!" arrives as "talk that", which reads as ordinary English."""
        out = apply_vocabulary("talk that needs to know about my app", [Term("Talk DAT!")])
        self.assertEqual(out, "Talk DAT! needs to know about my app")

    def test_an_explicit_pronunciation_is_honoured(self) -> None:
        out = apply_vocabulary("I listened to salve last night", [Term("SAHVVV", ("salve",))])
        self.assertEqual(out, "I listened to SAHVVV last night")

    def test_a_term_carrying_its_own_punctuation_does_not_double_it(self) -> None:
        out = apply_vocabulary("talk that shipped today", [Term("Talk DAT!")])
        self.assertEqual(out, "Talk DAT! shipped today")
        self.assertNotIn("!!", out)


class OrdinaryWordsAreLeftAloneTests(unittest.TestCase):
    """The cost of a false match is rewriting somebody's words, so it matters more
    than a missed one. Every case here must pass through untouched."""

    TERMS = [Term("Mayowa"), Term("Talk DAT!"), Term("Dat")]

    def test_similar_but_different_words_do_not_match(self) -> None:
        for sentence in (
            "the market is growing and marketing is hard",
            "we need to fix the login and ship the update",
            "she said the data was already loaded",
        ):
            with self.subTest(sentence=sentence[:34]):
                self.assertEqual(apply_vocabulary(sentence, self.TERMS), sentence)

    def test_a_term_already_spelled_correctly_is_not_rewritten(self) -> None:
        sentence = "Mayowa shipped Talk DAT! today"
        self.assertEqual(apply_vocabulary(sentence, self.TERMS), sentence)

    def test_short_words_are_refused_as_too_ambiguous(self) -> None:
        """A two-character key collides with half the language, so it never fires."""
        self.assertEqual(apply_vocabulary("I saw Dan and Dana", [Term("Don")]), "I saw Dan and Dana")

    def test_empty_and_missing_input_is_survivable(self) -> None:
        self.assertEqual(apply_vocabulary("", [Term("Mayowa")]), "")
        self.assertEqual(apply_vocabulary("hello there", []), "hello there")


class TheBrandCorrectsItselfOnEveryInstallTests(unittest.TestCase):
    """"Talk DAT!" and "Knight AI+AV" are defaults, not opt-ins.

    Every recognizer writes the product's name as "talk that", because to the
    ear that is what it is. The context guard is what makes shipping the
    correction on by default safe: identical words, told apart only by what
    follows them.
    """

    def _apply(self, text: str, config: dict | None = None) -> str:
        from knight_flow.text_pipeline import apply_vocabulary_terms

        return apply_vocabulary_terms(text, config or {})

    def test_the_name_is_corrected_with_an_empty_dictionary(self) -> None:
        """An empty dictionary is precisely the install that needs this."""
        self.assertEqual(self._apply("I built talk that for Windows"),
                         "I built Talk DAT! for Windows")

    def test_dat_is_capitalized_in_the_correction(self) -> None:
        out = self._apply("download talk dat today")
        self.assertIn("Talk DAT!", out)
        # The lowercase-Dat spelling is retired everywhere; "Dat" here is the
        # old casing deliberately, which is why this line must never be swept.
        self.assertNotIn("Talk " + "Dat!", out)

    def test_talking_something_over_is_left_alone(self) -> None:
        """"that" as a pronoun carries a continuation; a name does not."""
        for sentence in (
            "we should talk that over tomorrow",
            "let's talk that through before Friday",
            "can we talk that out first",
            "I want to talk that over with the team",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(self._apply(sentence), sentence)

    def test_the_company_name_is_corrected_too(self) -> None:
        self.assertEqual(self._apply("night ai and av built it"),
                         "Knight AI+AV built it")

    def test_a_users_own_spelling_of_the_name_wins_over_the_default(self) -> None:
        config = {"dictionary": {"terms": [{"text": "talk dat", "sounds_like": ["talk that"]}]}}
        self.assertEqual(self._apply("I built talk that for Windows", config),
                         "I built talk dat for Windows")


class SoundKeyTests(unittest.TestCase):
    def test_voiced_and_unvoiced_pairs_agree(self) -> None:
        """"dat" and "that" differ by voicing, which is exactly what is mis-heard."""
        self.assertEqual(sound_key("talk dat"), sound_key("talk that"))

    def test_a_glide_spelled_i_or_y_lands_on_one_key(self) -> None:
        self.assertEqual(sound_key("Mayowa"), sound_key("Maiowa"))

    def test_unrelated_words_score_low(self) -> None:
        self.assertLess(similarity(sound_key("market"), sound_key("marketing")), 0.86)


class ConfigShapesTests(unittest.TestCase):
    """`dictionary` is hand-edited and has had more than one shape over time."""

    def test_plain_strings_and_structured_entries_both_parse(self) -> None:
        terms = parse_terms(["Mayowa", {"text": "Talk DAT!", "sounds_like": "talk that"}])
        self.assertEqual([term.text for term in terms], ["Mayowa", "Talk DAT!"])
        self.assertEqual(terms[1].sounds_like, ("talk that",))

    def test_junk_entries_are_skipped_rather_than_raising(self) -> None:
        self.assertEqual(parse_terms([None, 7, {}, {"text": "   "}, "ok"]), [Term("ok")])
        self.assertEqual(parse_terms("not a list"), [])

    def test_both_config_stores_feed_the_same_pass(self) -> None:
        config = {"dictionary": {"words": ["Mayowa"], "terms": [{"text": "Talk DAT!"}]}}
        self.assertEqual(
            apply_vocabulary_terms("my yo wa built talk that", config),
            "Mayowa built Talk DAT!",
        )

    def test_a_broken_dictionary_never_costs_the_dictation(self) -> None:
        """A missed correction is acceptable; losing the words is not."""
        config = {"dictionary": {"terms": [{"text": object()}]}}
        self.assertEqual(apply_vocabulary_terms("keep my words", config), "keep my words")


if __name__ == "__main__":
    unittest.main()


class TheBrandRegistryCorrectsPublicNamesTests(unittest.TestCase):
    """A brand's spelling is a fact, not a preference. "you tube" and "git hub"
    are what those names sound like, and correcting them should not require
    every user to teach them. The house products lead the registry."""

    def _apply(self, text: str, config: dict | None = None) -> str:
        return apply_vocabulary_terms(text, config or {})

    def test_knight_products_correct_themselves(self) -> None:
        for heard, expected in (
            ("check out nav orb today", "check out NavOrb today"),
            ("task rune is like trello", "TaskRune is like trello"),
            ("open knight chat now", "open KnightChat now"),
        ):
            with self.subTest(heard=heard):
                self.assertEqual(self._apply(heard), expected)

    def test_world_brands_correct_themselves(self) -> None:
        for heard, expected in (
            ("watch it on you tube", "watch it on YouTube"),
            ("push it to git hub", "push it to GitHub"),
            ("my i phone died", "my iPhone died"),
            ("ask chat gpt about it", "ask ChatGPT about it"),
        ):
            with self.subTest(heard=heard):
                self.assertEqual(self._apply(heard), expected)

    def test_common_english_words_were_kept_out_of_the_registry(self) -> None:
        """"Excel" and "Word" are verbs and nouns before they are trademarks.
        A registry that rewrites them rewrites ordinary sentences."""
        from knight_flow.vocabulary import BRAND_TERMS

        texts = {term.text.lower() for term in BRAND_TERMS}
        for banned in ("excel", "word", "pages", "teams", "meet", "drive"):
            self.assertNotIn(banned, texts)
        for sentence in ("I excel at work", "keep your word", "drive safely home"):
            with self.subTest(sentence=sentence):
                self.assertEqual(self._apply(sentence), sentence)

    def test_wife_is_never_rewritten_to_wifi(self) -> None:
        """Wi-Fi was cut from the registry for exactly this: its key is two
        letters, and matching loose enough to admit "wifi" rewrites "wife"."""
        for sentence in ("my wife called earlier", "ask my wife about it"):
            with self.subTest(sentence=sentence):
                self.assertEqual(self._apply(sentence), sentence)

    def test_fused_compounds_correct_themselves(self) -> None:
        """Found by the feature check on the SHIPPED local model: it heard
        'talk dat' as the single token 'TalkDad', and two-word terms never
        tried one-word windows. Recognizers fuse compounds constantly."""
        for heard, expected in (
            ("I built TalkDad for Windows", "I built Talk DAT! for Windows"),
            ("I built talkdat for windows", "I built Talk DAT! for windows"),
            ("push it to github now", "push it to GitHub now"),
            ("send it via paypal today", "send it via PayPal today"),
        ):
            with self.subTest(heard=heard):
                self.assertEqual(self._apply(heard), expected)

    def test_exact_casing_is_the_only_thing_left_alone(self) -> None:
        """A brand's casing IS part of the correction: lowercase 'github'
        recases, while a letter-for-letter 'GitHub' is untouched."""
        self.assertEqual(self._apply("GitHub is down again today"), "GitHub is down again today")

    def test_claude_heard_for_cloud_corrects_with_context_intact(self) -> None:
        """Field report 2026-08-10: Deepgram writes 'Claude' when users say
        'cloud'. Bare Claude corrects; Claude-the-AI survives its context."""
        for heard, expected in (
            ("switch me to claude now", "switch me to cloud now"),
            ("put it on the claude please", "put it on the cloud please"),
        ):
            with self.subTest(heard=heard):
                self.assertEqual(self._apply(heard), expected)
        for sentence in (
            "I asked claude code to fix it",
            "the claude model is fast",
            "claude agents run my fleet",
        ):
            with self.subTest(sentence=sentence):
                out = self._apply(sentence)
                self.assertIn("claude", out.lower())
                self.assertNotIn("cloud", out.lower())

    def test_open_a_never_becomes_openai(self) -> None:
        """X-14: 'open a' corrupted a real dictation to 'OpenAI' three times in
        one message. OpenAI was cut from the registry -- the sound collision
        with one of English's most common bigrams is unwinnable."""
        from knight_flow.vocabulary import BRAND_TERMS

        self.assertNotIn("openai", {term.text.lower() for term in BRAND_TERMS})
        for sentence in (
            "when I open a window that window should open",
            "open a file for me please",
            "it pops open a quick note",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(self._apply(sentence), sentence)

    def test_common_verbs_never_become_brands(self) -> None:
        """The pair that found the length guard: built and Bluetooth share a
        sound key, and only five letters against nine tells them apart."""
        for sentence in ("I built it yesterday", "we built the whole thing", "open the door"):
            with self.subTest(sentence=sentence):
                self.assertEqual(self._apply(sentence), sentence)

    def test_a_user_respelling_outranks_the_registry(self) -> None:
        config = {"dictionary": {"terms": [{"text": "Tik Tok Consulting", "sounds_like": ["tik tok"]}]}}
        out = self._apply("call tik tok about the contract", config)
        self.assertIn("Tik Tok Consulting", out)
        self.assertNotIn("TikTok ", out)

    def test_the_registry_can_be_switched_off(self) -> None:
        config = {"dictionary": {"brand_names": False}}
        self.assertEqual(self._apply("watch it on you tube", config),
                         "watch it on you tube")

    def test_a_long_transcript_formats_in_well_under_a_second_of_cpu(self) -> None:
        """Perf regression pin. Field-measured 2026-08-10: an 800-word talk
        spent 7.6 SECONDS in this matcher because sound keys and similarity
        were recomputed for strings already seen; memoization brought the
        same text to ~0.7s. The bound is loose for slow CI, but any return
        of the quadratic recomputation blows straight through it."""
        import time

        from knight_flow.text_pipeline import apply_vocabulary_terms

        words = ("we need to make this much better people keep saying the "
                 "latency is high and the corrections are messy and i want the "
                 "cloud model to be the best version of itself on every platform ")
        text = (words * 30)[:4400]
        start = time.perf_counter()
        apply_vocabulary_terms(text, {})
        elapsed_ms = (time.perf_counter() - start) * 1000
        self.assertLess(elapsed_ms, 2500,
                        f"vocabulary pass took {elapsed_ms:.0f}ms on 4400 chars")
