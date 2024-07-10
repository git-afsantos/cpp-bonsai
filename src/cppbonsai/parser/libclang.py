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
entity builders from a queue.

EntityBuilder is the base class for each Cursor handler.
These builders work with Python generators.
They yield dependencies (child cursors, turned into builders) as they find them.
The generators are bidirectional, allowing the higer-level ASTBuilder to send
back the constructed child AST node ID to the builder as the result of yield.
This is done so that a given builder has access to all its children node IDs
(assigned upon construction).
In short, processing of a high-level Cursor is halted (via yield) until all of
its dependencies have an ID and are queued for processing.
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
class EntityBuilder:
    cursor: clang.Cursor
    parent: ASTNodeId = field(default=NULL_ID)

    def build(self, node_id: ASTNodeId) -> ASTNode:
        raise NotImplementedError()


BuilderGenerator = Generator[EntityBuilder, ASTNode, ASTNode]


@define
class TranslationUnitBuilder(EntityBuilder):
    workspace: Optional[Path] = None

    def build(self, node_id: ASTNodeId) -> ASTNode:
        assert node_id == NULL_ID
        assert self.cursor.kind == CK.TRANSLATION_UNIT

        cursors: List[clang.Cursor] = []
        for cursor in self.cursor.get_children():
            loc_file: Optional[clang.File] = cursor.location.file
            if loc_file is None:
                continue
            file_path: Path = Path(loc_file.name)
            if self.workspace and (self.workspace not in file_path.parents):
                continue
            # if not loc_file.name.startswith(str(self.workspace)):
            #     continue
            cursors.append(cursor)

        children: List[ASTNodeId] = []
        for cursor in cursors:
            if cursor.kind == CK.NAMESPACE:
                child_id: ASTNodeId = yield NamespaceBuilder(cursor, parent=node_id)
                children.append(child_id)
            else:
                pass #raise TypeError(f'unexpected cursor kind: {cursor_str(cursor)}')

        return ASTNode(node_id, ASTNodeType.FILE, children=children)


@define
class NamespaceBuilder(EntityBuilder):
    def build(self, node_id: ASTNodeId) -> ASTNode:
        assert self.cursor.kind == CK.NAMESPACE
        children: List[ASTNodeId] = []
        for cursor in self.cursor.get_children():
            if cursor.kind == CK.NAMESPACE:
                child_id: ASTNodeId = yield NamespaceBuilder(cursor, parent=node_id)
                children.append(child_id)
            else:
                pass #raise TypeError(f'unexpected cursor kind: {cursor_str(cursor)}')

        return ASTNode(node_id, ASTNodeType.NAMESPACE, children=children)


@define
class EntityBuilderTask:
    id: ASTNodeId
    generator: BuilderGenerator
    ast: AST

    def send(self, node_id: ASTNodeId) -> EntityBuilder:
        return self.generator.send(node_id)

    def __iter__(self):
        node: ASTNode = yield from self.generator
        self.ast.nodes[node.id] = node


@define
class ASTBuilder:
    ast: AST = field(factory=AST, eq=False)
    _next_id: IdGenerator = field(factory=IdGenerator, eq=False)
    _queue: Deque[EntityBuilderTask] = field(factory=deque, eq=False)

    def build_from_unit(self, tu: clang.TranslationUnit, workspace: Optional[Path] = None) -> AST:
        self._queue = deque()
        self._next_id = IdGenerator(id=NULL_ID)
        builder = TranslationUnitBuilder(tu.cursor, workspace=workspace)
        ast = AST()
        self._enqueue(builder, ast)
        self._process_queue(ast)
        return ast

    def _process_queue(self, ast: AST):
        while self._queue:
            task = self._queue.popleft()
            child_id: Optional[ASTNodeId] = None
            try:
                while True:
                    dependency: EntityBuilder = task.send(child_id)
                    child_id = self._enqueue(dependency, ast)
            except StopIteration:
                pass  # return value handled in the generator wrapper

    # def _builder_generator(self, builder: EntityBuilder) -> BuilderGenerator:
    #     node_id = self._next_id.get()
    #     generator = builder.build(node_id)
    #     node: ASTNode = yield from generator
    #     self.ast.nodes[node.id] = node

    def _enqueue(self, builder: EntityBuilder, ast: AST) -> ASTNodeId:
        node_id = self._next_id.get()
        task = EntityBuilderTask(node_id, builder.build(node_id), ast)
        self._queue.append(task)
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
    _stack: List[EntityBuilder] = field(factory=list)

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
