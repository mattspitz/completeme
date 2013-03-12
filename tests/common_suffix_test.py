import unittest

from completeme.completeme import _common_suffix

class CommonSuffixTest(unittest.TestCase):

    def test_common_suffix(self):
        """ Ensures that we properly return the common suffix for two input strings. """
        self.assertEqual(_common_suffix("hello there", "there you go"), "")
        self.assertEqual(_common_suffix("hello there", "we're here"), "here")
        self.assertEqual(_common_suffix("", "there you go"), "")
        self.assertEqual(_common_suffix("hello there", ""), "")
        self.assertEqual(_common_suffix("hello there", "helo there"), "lo there")
        self.assertEqual(_common_suffix("hello/there", "helo/there"), "lo/there")
        self.assertEqual(_common_suffix("hello there", "hello there"), "hello there")
