SHELL := /bin/bash

CURRENT_VERSION := $(shell python -c "import sys; import completeme; sys.stdout.write(completeme.__version__)")
NEXT_VERSION := $(shell python -c "import sys; curr = map(int, '$(CURRENT_VERSION)'.split('.')); curr[-1] += 1; sys.stdout.write('.'.join(map(str,curr)));")

default:
	@echo "Run make release to build and commit a new version of the library"

build_sdist:
	bash check_build.sh

	python setup.py sdist upload

	# bump version
	sed -i '' 's/^__version__ = .*/__version__ = "$(NEXT_VERSION)"/' completeme/__init__.py

	# add the new dist, commit, and add tag
	git add completeme/__init__.py
	git commit -m "Releasing version $(CURRENT_VERSION)"
	git tag "v$(CURRENT_VERSION)"

release: build_sdist clean

clean:
	rm -rf build *.egg-info
