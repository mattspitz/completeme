import os
import random
import time
import unittest

import completeme

class UserInputRegexTest(unittest.TestCase):

    def compute_eligible_filenames(self, input_str, candidates):
        """ Helper for spinning up a thread and waiting for results. """

        bg_thread = completeme.SearchThread(
                input_str,
                completeme.CurrentFilenames(
                    candidates=candidates,
                    candidate_computation_complete=True,
                    current_search_dir=os.path.abspath("."),
                    git_root_dir=None)
                )
        bg_thread.start()

        start = time.time()
        while True:
            eligible_fns = bg_thread.get_eligible_filenames()
            if not eligible_fns.search_complete:
                if time.time() - start > 2:
                    raise Exception("This should have taken way less than two seconds...")
                time.sleep(0.01)
                continue
            return eligible_fns.eligible

    def test_regexy_characters(self):
        """ Ensures that even if the user inputs things like . and * and ? that we won't explode. """

        SPACE_QUESTION_DOT = "a/b/this directory/c/d/e?.txt"
        SPACE_ASTERISK_QUESTION_DOT = "oh dear what* have we done?.txt"
        BRACKET_DOT_SPACE = "An artist [in the evening].mp3"
        NORMAL_DIR = "a/b/c/thisisnormal.txt"
        NORMAL_FILE = "normalfilefinally.txt"

        ELIGIBLE_FILENAMES = [ SPACE_QUESTION_DOT,
                               SPACE_ASTERISK_QUESTION_DOT,
                               BRACKET_DOT_SPACE,
                               NORMAL_DIR,
                               NORMAL_FILE ]

        def run_test(input_str, expected):
            # we use sorted to check for presence, not order
            self.assertEqual(
                    sorted(self.compute_eligible_filenames(input_str, ELIGIBLE_FILENAMES)),
                    sorted(expected)
                    )

        run_test("*", [SPACE_ASTERISK_QUESTION_DOT])
        run_test("?", [SPACE_QUESTION_DOT, SPACE_ASTERISK_QUESTION_DOT])
        run_test(".", ELIGIBLE_FILENAMES)
        run_test("?.", [SPACE_QUESTION_DOT, SPACE_ASTERISK_QUESTION_DOT])
        run_test(".?", [])
        run_test("[.*]", [])
        run_test("].", [BRACKET_DOT_SPACE])
        run_test(" ", [ SPACE_QUESTION_DOT, SPACE_ASTERISK_QUESTION_DOT, BRACKET_DOT_SPACE ])
        run_test("? ", [])
        run_test(" ?", [ SPACE_QUESTION_DOT, SPACE_ASTERISK_QUESTION_DOT ])

    def test_ignorecase(self):
        """ Ensures that we properly ignore case in the input and in eligible filenames. """
        CAPS = "The quick brown FoX jumped over the lazy dog."
        LOWER = "the quick brown fox jumped over the lazy dog."

        for input_str in ["fox", "FOX", "FoX", "fOX"]:
            self.assertEqual(
                    sorted(self.compute_eligible_filenames(input_str, [CAPS, LOWER])),
                    sorted([CAPS, LOWER])
                    )

    def test_ranking(self):
        """ Ensures that we rank long-matching substrings above short-matching substrings and shorter gaps between matches over longer. """

        def run_test(input_str, eligible, expected):
            random.shuffle(eligible)
            self.assertEqual(
                    self.compute_eligible_filenames(input_str, eligible),
                    expected
                    )

        A = "My Documents/Wow/Remember Those Days?.txt"
        B = "My Documents/Wow/Wow/Wow/Remember Those Days?.txt"
        run_test("My Days", [A, B], [A, B]) # prefer shorter distance between My and Days

        C = "My Documents/Gross Stuff/Gross and Gross/Created By/YoursTruly.txt"
        D = "My Documents/Pictures/Dogs and Cats.jpg"
        run_test("dogs and cats", [C, D], [D, C]) # find the shortest gaps between matching substrings

        E = "MavisBeaconEnters/src/main/resources/whatever.txt"
        F = "MavisBeaconEnters/src/main/java/com/mavisbeacon/app/enters/typing/is/fun/MBEResource.java"
        run_test("mberesource", [E, F], [F, E]) # push off the match as much as possible to get the grouping at the end
