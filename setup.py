#!/usr/bin/env python

from setuptools import setup

setup(
        name = "completeme",
        version = open("VERSION").read().strip(),
        description = "Automagic ctrl+t filename completion to launch in your favorite editor",
        long_description = open("README.rst").read(),
        author = "Matt Spitz",
        author_email = "mattspitz@gmail.com",
        url = "https://github.com/mattspitz/completeme",

        packages = ["completeme"],
        package_data = {"completeme": ["conf/completeme.json"]},
        entry_points = {
            "console_scripts": [
                    "completeme = completeme:main"
                ]
            },
        scripts = ["setup_completeme_key_binding.sh"],
        install_requires = ["setuptools"]
)
