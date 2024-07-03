# SPDX-License-Identifier: MIT
# Copyright © 2024 André Santos

###############################################################################
# Imports
###############################################################################

from typing import Final, Iterable, List, Optional, Tuple

from contextlib import contextmanager
from ctypes import ArgumentError
import logging
import os
from pathlib import Path

from attrs import define, field
import clang.cindex as clang

###############################################################################
# Constants
###############################################################################

CK = clang.CursorKind

logger: Final[logging.Logger] = logging.getLogger(__name__)

###############################################################################
# Parser
###############################################################################


@define
class ClangParser:
    lib_path: Optional[Path] = None
    lib_file: Optional[Path] = None
    includes: Optional[Path] = None
    user_includes: Iterable[Path] = field(factory=list)
    database: Optional[clang.CompilationDatabase] = None
    db_path: Optional[Path] = None
    _index: Optional[clang.Index] = None
    workspace: Optional[Path] = None

    def parse(self, file_path: Path):
        if self.database is None:
            unit: clang.TranslationUnit = self._parse_without_db(file_path)
        else:
            unit = self._parse_from_db(file_path)
        check_compilation_problems(unit)
        return ast_str(unit.cursor, workspace=self.workspace)

    def _parse_from_db(self, file_path: Path) -> clang.TranslationUnit:
        key = str(file_path)
        commands: Iterable[clang.CompileCommand] = self.database.getCompileCommands(key)
        if not commands:
            logger.error(f'no compile commands for "{key}"')
            raise KeyError(key)
        for cmd in commands:
            if not cmd.arguments:
                continue
            with working_directory(self.db_path / cmd.directory):
                args = ['-I' + self.includes]
                args.extend(list(cmd.arguments)[1:])
                if self._index is None:
                    self._index = clang.Index.create()
                return self._index.parse(None, args=args)
                #self._ast_analysis(unit.cursor)
        #self.global_scope._afterpass()
        #return self.global_scope
        logger.error(f'no arguments given for any compile command')
        raise RuntimeError(f'no arguments given for any compile command')

    def _parse_without_db(self, file_path: Path) -> clang.TranslationUnit:
        with working_directory(file_path.parent):
            args = [f'-I{self.includes}']
            for include_dir in self.user_includes:
                args.append(f'-I{include_dir}')
            if self._index is None:
                self._index = clang.Index.create()
            return self._index.parse(str(file_path), args=args)
            #self._ast_analysis(unit.cursor)
        #self.global_scope._afterpass()
        #return self.global_scope


###############################################################################
# Helpers
###############################################################################


@contextmanager
def working_directory(path: Path):
    """Changes working directory and returns to previous on exit."""
    prev_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev_cwd)


def check_compilation_problems(translation_unit: clang.TranslationUnit):
    for diagnostic in (translation_unit.diagnostics or ()):
        if diagnostic.severity >= clang.Diagnostic.Error:
            logger.warning(diagnostic.spelling)


def cursor_str(cursor: clang.Cursor, indent: int = 0) -> str:
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
    tokens = len(list(cursor.get_tokens()))
    prefix = indent * '| '
    return f'{prefix}[{line}:{col}] {name}: {spell} [{tokens} tokens]'


def ast_str(top_cursor: clang.Cursor, workspace: Optional[Path] = None) -> str:
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
        lines.append(cursor_str(cursor, indent=indent))
        for child in reversed(list(cursor.get_children())):
            stack.append((indent + 1, child))

    return '\n'.join(lines)
