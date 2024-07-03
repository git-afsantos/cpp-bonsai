# SPDX-License-Identifier: MIT
# Copyright © 2024 André Santos

###############################################################################
# Imports
###############################################################################

from typing import Iterable, Optional

from contextlib import contextmanager
from ctypes import ArgumentError
import os
from pathlib import Path

from attrs import define, field
import clang.cindex as clang

###############################################################################
# Constants
###############################################################################

CK = clang.CursorKind

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
    workspace: str = ''

    def parse(self, file_path: Path):
        if self.database is None:
            return self._parse_without_db(file_path)
        return self._parse_from_db(file_path)

    def _parse_from_db(self, file_path: Path, just_ast: bool = True):
        # ----- command retrieval ---------------------------------------------
        cmd: Iterable[clang.CompileCommand] = self.database.getCompileCommands(file_path) or ()
        if not cmd:
            return None
        for c in cmd:
            with working_directory(self.db_path / c.directory):
                args = ['-I' + self.includes] + list(c.arguments)[1:]
                if self._index is None:
                    self._index = clang.Index.create()

                # ----- parsing and AST analysis ------------------------------
                unit: clang.TranslationUnit = self._index.parse(None, args=args)
                check_compilation_problems(unit)
                if just_ast:
                    return self._ast_str(unit.cursor)
                #self._ast_analysis(unit.cursor)

        #self.global_scope._afterpass()
        #return self.global_scope
        return self._ast_str(unit.cursor)

    def _parse_without_db(self, file_path: Path, just_ast: bool = True):
        # ----- command retrieval ---------------------------------------------
        with working_directory(file_path.parent):
            args = [f'-I{self.includes}']

            for include_dir in self.user_includes:
                args.append(f'-I{include_dir}')

            # args.append(str(file_path))
            self.workspace = str(file_path.parent)

            if self._index is None:
                self._index = clang.Index.create()

            # ----- parsing and AST analysis ----------------------------------
            unit = self._index.parse(str(file_path), args)
            check_compilation_problems(unit)
            if just_ast:
                return self._ast_str(unit.cursor)
            #self._ast_analysis(unit.cursor)

        #self.global_scope._afterpass()
        #return self.global_scope
        return self._ast_str(unit.cursor)

    def _ast_str(self, top_cursor: clang.Cursor) -> str:
        assert top_cursor.kind == CK.TRANSLATION_UNIT

        lines = []
        for cursor in top_cursor.get_children():
            if (cursor.location.file
                    and cursor.location.file.name.startswith(self.workspace)):
                lines.append(cursor_str(cursor, 0))
                indent = 0
                stack = list(cursor.get_children())
                stack.reverse()
                stack.append(1)
                while stack:
                    c = stack.pop()
                    if isinstance(c, int):
                        indent += c
                    else:
                        lines.append(cursor_str(c, indent))
                        stack.append(-1)
                        stack.extend(reversed(list(c.get_children())))
                        stack.append(1)
        return '\n'.join(lines)


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
    if translation_unit.diagnostics:
        for diagnostic in translation_unit.diagnostics:
            if diagnostic.severity >= clang.Diagnostic.Error:
                # logging.warning(diagnostic.spelling)
                print('WARNING', diagnostic.spelling)


def cursor_str(cursor: clang.Cursor, indent: int) -> str:
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
