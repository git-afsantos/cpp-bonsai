# SPDX-License-Identifier: MIT
# Copyright © 2024 André Santos

###############################################################################
# Imports
###############################################################################

import codebonsai

###############################################################################
# Tests
###############################################################################


def test_import_was_ok():
    assert True


def test_pkg_has_version():
    assert hasattr(codebonsai, '__version__')
    assert isinstance(codebonsai.__version__, str)
    assert codebonsai.__version__ != ''
