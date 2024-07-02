# SPDX-License-Identifier: MIT
# Copyright © 2024 André Santos

###############################################################################
# Imports
###############################################################################

from importlib.metadata import PackageNotFoundError, version  # pragma: no cover

###############################################################################
# Constants
###############################################################################

try:
    __version__ = version('cppbonsai')
except PackageNotFoundError:  # pragma: no cover
    # package is not installed
    __version__ = 'unknown'
