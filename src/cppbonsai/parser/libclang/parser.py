# SPDX-License-Identifier: MIT
# Copyright © 2024 André Santos

###############################################################################
# Imports
###############################################################################

from typing import Any, Deque, Final, Iterable, List, Mapping, Optional

from collections import deque
from contextlib import contextmanager
import logging
import os
from pathlib import Path

from attrs import define, field
import clang.cindex as clang

from cppbonsai.ast.common import AST, NULL_ID, ASTNode, ASTNodeAttribute, ASTNodeId, AttributeMap
from cppbonsai.parser.libclang.cursors import CursorHandler, TranslationUnitHandler
from cppbonsai.parser.libclang.util import cursor_str

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
class BuilderQueue:
    def append(self, handler: CursorHandler, parent: ASTNodeId) -> ASTNodeId:
        raise NotImplementedError(f'BuilderQueue.append({handler!r}, {parent!r})')


@define
class ASTNodeBuilder:
    id: ASTNodeId
    parent: ASTNodeId
    handler: CursorHandler

    def build(self, queue: BuilderQueue) -> ASTNode:
        children: List[ASTNodeId] = []
        annotations: Mapping[str | ASTNodeAttribute, Any] = AttributeMap()
        for dependency in self.handler.process(annotations):
            node_id = queue.append(dependency, self.id)
            children.append(node_id)
        return ASTNode(
            self.id,
            self.handler.node_type,
            parent=self.parent,
            children=children,
            annotations=annotations.data,
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
# Helper Functions
###############################################################################


def check_compilation_problems(translation_unit: clang.TranslationUnit):
    for diagnostic in (translation_unit.diagnostics or ()):
        if diagnostic.severity >= clang.Diagnostic.Error:
            logger.warning(diagnostic.spelling)


@contextmanager
def working_directory(path: Path):
    """Changes working directory and returns to previous on exit."""
    prev_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev_cwd)
