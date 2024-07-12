# SPDX-License-Identifier: MIT
# Copyright © 2024 André Santos

###############################################################################
# Imports
###############################################################################

from typing import Final, List, Optional, Tuple

from ctypes import ArgumentError
import logging
from pathlib import Path

import clang.cindex as clang

from cppbonsai.ast.common import AccessSpecifier, SourceLocation

###############################################################################
# Constants
###############################################################################

CK = clang.CursorKind

logger: Final[logging.Logger] = logging.getLogger(__name__)

###############################################################################
# Helpers
###############################################################################


def location_from_cursor(cursor: clang.Cursor) -> SourceLocation:
    name = ''
    line = 0
    column = 0
    try:
        if cursor.location.file:
            name = cursor.location.file.name
            line = cursor.location.line
            column = cursor.location.column
    except ArgumentError as e:
        logger.debug(f'unable to extract location from cursor: {cursor_str(cursor, verbose=True)}')
    return SourceLocation(line=line, column=column, file=name)


def get_access_specifier(cursor: clang.Cursor) -> AccessSpecifier:
    access: clang.AccessSpecifier = cursor.access_specifier
    if access == clang.AccessSpecifier.PUBLIC:
        return AccessSpecifier.PUBLIC
    if access == clang.AccessSpecifier.PRIVATE:
        return AccessSpecifier.PRIVATE
    if access == clang.AccessSpecifier.PROTECTED:
        return AccessSpecifier.PROTECTED
    raise ValueError(f'invalid access specifier: {cursor_str(cursor, verbose=True)}')


def cursor_str(cursor: clang.Cursor, indent: int = 0, verbose: bool = False) -> str:
    line = 0
    col = 0
    try:
        if cursor.location.file:
            line = cursor.location.line
            col = cursor.location.column
    except ArgumentError as e:
        pass
    prefix = indent * '| '
    items: List[str] = [f'{prefix}[{line}:{col}]']
    if verbose:
        usr = cursor.get_usr()
        items.append(f'[{usr}]')
        access = cursor.access_specifier
        items.append(f'({access})')
    name = repr(cursor.kind)[11:]
    items.append(f'{name}:')
    spelling = cursor.spelling or '[no spelling]'
    items.append(spelling)
    tokens = [(t.spelling, t.kind.name) for t in cursor.get_tokens()]
    items.append(f'[{len(tokens)} tokens]')
    if verbose and len(tokens) < 5:
        items.append(f'{tokens}')
    return ' '.join(items)


def ast_str(
    top_cursor: clang.Cursor,
    workspace: Optional[Path] = None,
    verbose: bool = False,
) -> str:
    assert top_cursor.kind == CK.TRANSLATION_UNIT

    stack: List[Tuple[int, clang.Cursor]] = []
    for cursor in top_cursor.get_children():
        loc_file: Optional[clang.File] = cursor.location.file
        if loc_file is None:
            continue
        file_path: Path = Path(loc_file.name)
        if workspace and (workspace not in file_path.parents):
            continue
        # if not loc_file.name.startswith(str(self.workspace)):
        #     continue
        stack.append((0, cursor))

    stack.reverse()
    lines: List[str] = []
    while stack:
        indent, cursor = stack.pop()
        lines.append(cursor_str(cursor, indent=indent, verbose=verbose))
        for child in reversed(list(cursor.get_children())):
            stack.append((indent + 1, child))

    return '\n'.join(lines)
