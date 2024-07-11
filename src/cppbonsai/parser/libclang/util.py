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

from cppbonsai.ast.common import SourceLocation

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
        text = cursor_str(cursor)
        logger.debug(f'unable to extract location from cursor: {text}')
    return SourceLocation(line=line, column=column, file=name)


def cursor_str(cursor: clang.Cursor, indent: int = 0, verbose: bool = False) -> str:
    line = 0
    col = 0
    try:
        if cursor.location.file:
            line = cursor.location.line
            col = cursor.location.column
    except ArgumentError as e:
        pass
    name = repr(cursor.kind)[11:]
    spell = cursor.spelling or '[no spelling]'
    tokens = [(t.spelling, t.kind.name) for t in cursor.get_tokens()]
    prefix = indent * '| '
    if not verbose or len(tokens) >= 5:
        return f'{prefix}[{line}:{col}] {name}: {spell} [{len(tokens)} tokens]'
    usr = cursor.get_usr()
    return f'{prefix}[{line}:{col}][{usr}] {name}: {spell} [{len(tokens)} tokens] {tokens}'


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
