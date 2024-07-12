# SPDX-License-Identifier: MIT
# Copyright © 2024 André Santos

###############################################################################
# Imports
###############################################################################

from typing import Any, Final, Iterable, List, Mapping, Optional

import logging
from pathlib import Path

from attrs import define, field
import clang.cindex as clang

from cppbonsai.ast.common import ASTNodeAttribute, ASTNodeType, AttributeMap, SourceLocation
from cppbonsai.parser.libclang.util import cursor_str, location_from_cursor

###############################################################################
# Constants
###############################################################################

CK = clang.CursorKind

logger: Final[logging.Logger] = logging.getLogger(__name__)

###############################################################################
# Base Class
###############################################################################


@define
class CursorHandler:
    cursor: clang.Cursor

    @property
    def node_type(self) -> ASTNodeType:
        raise NotImplementedError()

    @property
    def location(self) -> SourceLocation:
        return location_from_cursor(self.cursor)

    def process(self, data: AttributeMap) -> Iterable['CursorHandler']:
        raise NotImplementedError()


###############################################################################
# Top-level Cursors
###############################################################################


@define
class TranslationUnitHandler(CursorHandler):
    workspace: Optional[Path] = None

    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.FILE

    @property
    def location(self) -> SourceLocation:
        return SourceLocation(file=self.cursor.spelling)

    def process(self, data: AttributeMap) -> Iterable[CursorHandler]:
        assert self.cursor.kind == CK.TRANSLATION_UNIT
        logger.debug(f'processing cursor: {cursor_str(self.cursor)}')

        dependencies: List[CursorHandler] = []
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
                dependencies.append(NamespaceHandler(cursor))
            elif cursor.kind == CK.CLASS_DECL:
                dependencies.append(ClassDeclarationHandler(cursor))
            else:
                pass #raise TypeError(f'unexpected cursor kind: {cursor_str(cursor)}')

        return dependencies


@define
class NamespaceHandler(CursorHandler):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.NAMESPACE

    def process(self, data: AttributeMap) -> Iterable[CursorHandler]:
        assert self.cursor.kind == CK.NAMESPACE
        logger.debug(f'processing cursor: {cursor_str(self.cursor)}')

        data[ASTNodeAttribute.NAME] = self.cursor.spelling

        dependencies: List[CursorHandler] = []
        for cursor in self.cursor.get_children():
            logger.debug(f'found child cursor: {cursor_str(cursor)}')
            if cursor.kind == CK.NAMESPACE:
                dependencies.append(NamespaceHandler(cursor))
            elif cursor.kind == CK.CLASS_DECL:
                dependencies.append(ClassDeclarationHandler(cursor))
            else:
                pass #raise TypeError(f'unexpected cursor kind: {cursor_str(cursor)}')

        return dependencies


@define
class ClassDeclarationHandler(CursorHandler):
    _stack: List[clang.Cursor] = field(factory=list, eq=False)

    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.CLASS_DEF if self.cursor.is_definition() else ASTNodeType.CLASS_DECL

    def process(self, data: AttributeMap) -> Iterable[CursorHandler]:
        assert self.cursor.kind == CK.CLASS_DECL
        logger.debug(f'processing cursor: {cursor_str(self.cursor)}')

        # extract attributes from the cursor
        data[ASTNodeAttribute.NAME] = self.cursor.spelling
        data[ASTNodeAttribute.USR] = self.cursor.get_usr()
        data[ASTNodeAttribute.DISPLAY_NAME] = self.cursor.displayname
        # cursor = self.cursor.get_definition()

        # process child cursors using a state machine
        self._stack.extend(reversed(list(self.cursor.get_children())))
        if not self._stack:
            return []
        # stage 1: process base classes
        self._handle_base_classes(data)
        # stage 2: process members
        return self._handle_members()

    def _handle_base_classes(self, data: Mapping[str | ASTNodeAttribute, Any]):
        bases: List[str] = []
        while self._stack:
            cursor = self._stack.pop()
            if cursor.kind != CK.CXX_BASE_SPECIFIER:
                # return non-base specifier cursor to the stack
                self._stack.append(cursor)
                break
            logger.debug(f'found child cursor: {cursor_str(cursor)}')
            bases.append(cursor.spelling)
        if bases:
            data[ASTNodeAttribute.BASE_CLASSES] = ','.join(bases)

    def _handle_members(self) -> Iterable[CursorHandler]:
        dependencies: List[CursorHandler] = []
        while self._stack:
            cursor = self._stack.pop()
            logger.debug(f'found child cursor: {cursor_str(cursor)}')

            # more or less ordered by likelihood
            if cursor.kind == CK.CXX_METHOD:
                pass
            elif cursor.kind == CK.FIELD_DECL:
                pass
            elif cursor.kind == CK.CONSTRUCTOR:
                pass
            elif cursor.kind == CK.CLASS_DECL:
                dependencies.append(ClassDeclarationHandler(cursor))
            elif cursor.kind == CK.CXX_ACCESS_SPEC_DECL:
                pass  # handled via cursor properties
            else:
                pass #raise TypeError(f'unexpected cursor kind: {cursor_str(cursor)}')

        return dependencies


###############################################################################
# Functions, Methods, Constructors, Etc
###############################################################################

