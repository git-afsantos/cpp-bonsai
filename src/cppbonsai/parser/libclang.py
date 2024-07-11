# SPDX-License-Identifier: MIT
# Copyright © 2024 André Santos

###############################################################################
# Imports
###############################################################################

from typing import Any, Deque, Final, Generator, Iterable, List, Mapping, Optional, Tuple

from collections import deque
from contextlib import contextmanager
from ctypes import ArgumentError
import logging
import os
from pathlib import Path

from attrs import define, field, frozen
import clang.cindex as clang

from cppbonsai.ast.common import AST, NULL_ID, ASTNode, ASTNodeId, ASTNodeType, SourceLocation

###############################################################################
# Notes
###############################################################################

"""
The main entry point is ClangParser.
This class is responsible for handling the setup of libclang, handling files,
reading input and so on.

ASTBuilder is responsible for the main loop that builds an AST.
It traverses the Cursor tree given by libclang and processes a series of
AST node builders from a queue.

ASTNodeBuilder handles the common steps to build an AST node.
It uses CursorHandler instances as strategies to implement the behaviour
that is specific to the cursor being handled.
It also receives the working queue as a dependency injection, so that it can
append new tasks originating from the current cursor.

A CursorHandler processes a cursor and extracts information from it.
It receives the 'annotations' dictionary for the current AST node, and adds
whatever information it can from the cursor. It also produces a list of new
CursorHandler that will each handle relevant cursor children.
"""

###############################################################################
# Constants
###############################################################################

CK = clang.CursorKind

logger: Final[logging.Logger] = logging.getLogger(__name__)

###############################################################################
# Builders
###############################################################################


@define
class IdGenerator:
    _id: int = 1

    def get(self) -> ASTNodeId:
        previous = self._id
        self._id += 1
        return ASTNodeId(previous)


@define
class CursorHandler:
    cursor: clang.Cursor

    @property
    def node_type(self) -> ASTNodeType:
        raise NotImplementedError()

    @property
    def location(self) -> SourceLocation:
        return location_from_cursor(self.cursor)

    def process(self, annotations: Mapping[str, Any]) -> Iterable['CursorHandler']:
        raise NotImplementedError()


@define
class TranslationUnitHandler(CursorHandler):
    workspace: Optional[Path] = None

    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.FILE

    @property
    def location(self) -> SourceLocation:
        return SourceLocation(file=self.cursor.spelling)

    def process(self, annotations: Mapping[str, Any]) -> Iterable[CursorHandler]:
        assert self.cursor.kind == CK.TRANSLATION_UNIT
        logger.debug(f'processing cursor: {cursor_str(self.cursor)}')

        children: List[CursorHandler] = []
        for cursor in self.cursor.get_children():
            loc_file: Optional[clang.File] = cursor.location.file
            if loc_file is None:
                continue
            file_path: Path = Path(loc_file.name)
            if self.workspace and (self.workspace not in file_path.parents):
                continue
            # if not loc_file.name.startswith(str(self.workspace)):
            #     continue

            logger.debug(f'found child cursor: {cursor_str(cursor)}')
            if cursor.kind == CK.NAMESPACE:
                children.append(NamespaceHandler(cursor))
            else:
                pass #raise TypeError(f'unexpected cursor kind: {cursor_str(cursor)}')

        return children


@define
class NamespaceHandler(CursorHandler):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.NAMESPACE

    def process(self, annotations: Mapping[str, Any]) -> Iterable[CursorHandler]:
        assert self.cursor.kind == CK.NAMESPACE
        logger.debug(f'processing cursor: {cursor_str(self.cursor)}')

        children: List[CursorHandler] = []
        for cursor in self.cursor.get_children():
            logger.debug(f'found child cursor: {cursor_str(cursor)}')
            if cursor.kind == CK.NAMESPACE:
                children.append(NamespaceHandler(cursor))
            else:
                pass #raise TypeError(f'unexpected cursor kind: {cursor_str(cursor)}')

        return children


@define
class BuilderQueue:
    def append(self, handler: CursorHandler, parent: ASTNodeId) -> ASTNodeId:
        raise NotImplementedError()


@define
class ASTNodeBuilder:
    id: ASTNodeId
    parent: ASTNodeId
    handler: CursorHandler

    def build(self, queue: BuilderQueue) -> ASTNode:
        children: List[ASTNodeId] = []
        annotations: Mapping[str, Any] = {}
        for dependency in self.handler.process(annotations):
            node_id = queue.append(dependency, self.id)
            children.append(node_id)
        return ASTNode(
            self.id,
            self.handler.node_type,
            parent=self.parent,
            children=children,
            annotations=annotations,
            location=self.handler.location,
        )


@define
class ASTBuilder(BuilderQueue):
    _next_id: IdGenerator = field(factory=IdGenerator, eq=False)
    _queue: Deque[ASTNodeBuilder] = field(factory=deque, eq=False)

    def build_from_unit(self, tu: clang.TranslationUnit, workspace: Optional[Path] = None) -> AST:
        self._next_id = IdGenerator(id=NULL_ID)
        handler = TranslationUnitHandler(tu.cursor, workspace=workspace)
        ast = AST()
        self.append(handler, NULL_ID)
        self._process_queue(ast)
        return ast

    def _process_queue(self, ast: AST):
        while self._queue:
            builder = self._queue.popleft()
            logger.debug(f'starting builder #{builder.id} (in queue: {len(self._queue)})')
            node = builder.build(self)
            logger.debug(f'finished node #{node.id} (in queue: {len(self._queue)})')
            ast.nodes[node.id] = node

    def append(self, handler: CursorHandler, parent: ASTNodeId) -> ASTNodeId:
        node_id = self._next_id.get()
        logger.debug(f'enqueue builder #{node_id} for: {cursor_str(handler.cursor)}')
        builder = ASTNodeBuilder(node_id, parent, handler)
        self._queue.append(builder)
        return node_id


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
    workspace: Optional[Path] = None
    _index: Optional[clang.Index] = None

    def parse(self, file_path: Path, verbose: bool = False):
        if self.database is None:
            unit: clang.TranslationUnit = self._parse_without_db(file_path)
        else:
            unit = self._parse_from_db(file_path)
        check_compilation_problems(unit)
        return self._build_ast(unit)
        # return ast_str(unit.cursor, workspace=self.workspace, verbose=verbose)

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

    def _build_ast(self, unit: clang.TranslationUnit) -> AST:
        builder = ASTBuilder()
        return builder.build_from_unit(unit, workspace=self.workspace)


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
