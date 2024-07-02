# SPDX-License-Identifier: MIT
# Copyright © 2024 André Santos

###############################################################################
# Imports
###############################################################################

import cppbonsai

###############################################################################
# Tests
###############################################################################


def test_import_was_ok():
    assert True


def test_pkg_has_version():
    assert hasattr(cppbonsai, '__version__')
    assert isinstance(cppbonsai.__version__, str)
    assert cppbonsai.__version__ != ''
