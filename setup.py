#!/usr/bin/env python

from setuptools import setup

setup(
        name = "completeme",
        version = open("VERSION").read().strip(),
        description = "Automagic ctrl+t filename completion to launch in your favorite editor",
        long_description = open("README.md").read(),
        author = "Matt Spitz",
        url = "https://github.com/mattspitz/completeme",

        py_modules = ["completeme"],
        entry_points = {
            "console_scripts": [
                    "completeme = completeme:main"
                ]
            },
        scripts = ["setup_completeme_key_binding.sh"]
        )

