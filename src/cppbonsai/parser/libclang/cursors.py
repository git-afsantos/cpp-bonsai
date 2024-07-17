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
from cppbonsai.parser.libclang.util import cursor_str, get_access_specifier, location_from_cursor

###############################################################################
# Constants
###############################################################################

TK = clang.TokenKind
CK = clang.CursorKind

logger: Final[logging.Logger] = logging.getLogger(__name__)

###############################################################################
# Base Class
###############################################################################


@define
class CursorHandler:
    cursor: clang.Cursor = field()

    @cursor.validator
    def check_valid_cursor(self, _attr, cursor: clang.Cursor):
        if not self._is_valid_cursor(cursor):
            raise ValueError(f'invalid cursor type: {cursor_str(cursor, verbose=True)}')

    @property
    def node_type(self) -> ASTNodeType:
        raise NotImplementedError()

    @property
    def location(self) -> SourceLocation:
        return location_from_cursor(self.cursor)

    def process(self, data: AttributeMap) -> Iterable['CursorHandler']:
        raise NotImplementedError()

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        raise NotImplementedError()


@define
class ScopedCursorHandler(CursorHandler):
    belongs_to: str = field(default='', eq=False)

    def process(self, data: AttributeMap) -> Iterable[CursorHandler]:
        if self.belongs_to:
            data[ASTNodeAttribute.BELONGS_TO] = self.belongs_to
        return self._process(data)

    def _process(self, data: AttributeMap) -> Iterable[CursorHandler]:
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

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.TRANSLATION_UNIT

    def process(self, data: AttributeMap) -> Iterable[CursorHandler]:
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
            elif cursor.kind == CK.STRUCT_DECL:
                pass  # dependencies.append(ClassDeclarationHandler(cursor, belongs_to=usr))
            elif cursor.kind == CK.UNION_DECL:
                pass
            elif cursor.kind == CK.FUNCTION_DECL:
                dependencies.append(FunctionDeclarationHandler(cursor))
            else:
                pass #raise TypeError(f'unexpected cursor kind: {cursor_str(cursor)}')

        return dependencies


@define
class NamespaceHandler(ScopedCursorHandler):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.NAMESPACE

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.NAMESPACE

    def _process(self, data: AttributeMap) -> Iterable[CursorHandler]:
        usr: str = self.cursor.get_usr()
        data[ASTNodeAttribute.USR] = usr
        data[ASTNodeAttribute.NAME] = self.cursor.spelling

        dependencies: List[CursorHandler] = []
        for cursor in self.cursor.get_children():
            logger.debug(f'found child cursor: {cursor_str(cursor)}')
            if cursor.kind == CK.NAMESPACE:
                dependencies.append(NamespaceHandler(cursor, belongs_to=usr))
            elif cursor.kind == CK.CLASS_DECL:
                dependencies.append(ClassDeclarationHandler(cursor, belongs_to=usr))
            elif cursor.kind == CK.STRUCT_DECL:
                pass  # dependencies.append(ClassDeclarationHandler(cursor, belongs_to=usr))
            elif cursor.kind == CK.UNION_DECL:
                pass
            elif cursor.kind == CK.FUNCTION_DECL:
                dependencies.append(FunctionDeclarationHandler(cursor, belongs_to=usr))
            else:
                pass #raise TypeError(f'unexpected cursor kind: {cursor_str(cursor)}')

        return dependencies


###############################################################################
# Classes and Fields
###############################################################################


@define
class ClassDeclarationHandler(ScopedCursorHandler):
    _stack: List[clang.Cursor] = field(factory=list, eq=False)

    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.CLASS_DEF if self.cursor.is_definition() else ASTNodeType.CLASS_DECL

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.CLASS_DECL

    def _process(self, data: AttributeMap) -> Iterable[CursorHandler]:
        # extract attributes from the cursor
        usr: str = self.cursor.get_usr()
        data[ASTNodeAttribute.USR] = usr
        data[ASTNodeAttribute.NAME] = self.cursor.spelling
        # data[ASTNodeAttribute.DISPLAY_NAME] = self.cursor.displayname
        # cursor = self.cursor.get_definition()

        # process child cursors using a state machine
        self._stack.extend(reversed(list(self.cursor.get_children())))
        if not self._stack:
            return ()
        # stage 1: process base classes
        self._handle_base_classes(data)
        # stage 2: process members
        return self._handle_members(usr)

    def _handle_base_classes(self, data: AttributeMap):
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

    def _handle_members(self, usr: str) -> Iterable[CursorHandler]:
        dependencies: List[CursorHandler] = []
        while self._stack:
            cursor = self._stack.pop()
            logger.debug(f'found child cursor: {cursor_str(cursor)}')

            # more or less ordered by likelihood
            if cursor.kind == CK.CXX_METHOD:
                dependencies.append(MethodDeclarationHandler(cursor, belongs_to=usr))
            elif cursor.kind == CK.FIELD_DECL:
                dependencies.append(FieldDeclarationHandler(cursor, belongs_to=usr))
            elif cursor.kind == CK.CONSTRUCTOR:
                pass
            elif cursor.kind == CK.DESTRUCTOR:
                pass
            elif cursor.kind == CK.CLASS_DECL:
                dependencies.append(ClassDeclarationHandler(cursor, belongs_to=usr))
            elif cursor.kind == CK.STRUCT_DECL:
                pass  # dependencies.append(ClassDeclarationHandler(cursor, belongs_to=usr))
            elif cursor.kind == CK.UNION_DECL:
                pass
            elif cursor.kind == CK.CXX_ACCESS_SPEC_DECL:
                pass  # handled via cursor properties
            else:
                pass #raise TypeError(f'unexpected cursor kind: {cursor_str(cursor)}')

        return dependencies


@define
class FieldDeclarationHandler(ScopedCursorHandler):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.FIELD_DECL

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.FIELD_DECL

    def _process(self, data: AttributeMap) -> Iterable[CursorHandler]:
        # extract attributes from the cursor
        data[ASTNodeAttribute.USR] = self.cursor.get_usr()
        data[ASTNodeAttribute.NAME] = self.cursor.spelling
        # data[ASTNodeAttribute.DISPLAY_NAME] = self.cursor.displayname
        data[ASTNodeAttribute.DATA_TYPE] = self.cursor.type.get_canonical().spelling
        data[ASTNodeAttribute.ACCESS_SPECIFIER] = get_access_specifier(self.cursor).value
        # boolean = self.cursor.is_mutable_field()
        return ()  # no dependencies


###############################################################################
# Functions, Methods, Constructors, Etc
###############################################################################


@define
class FunctionDeclarationHandler(ScopedCursorHandler):
    _stack: List[clang.Cursor] = field(factory=list, eq=False)

    @property
    def node_type(self) -> ASTNodeType:
        if self.cursor.is_definition():
            return ASTNodeType.FUNCTION_DEF
        else:
            return ASTNodeType.FUNCTION_DECL

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.FUNCTION_DECL

    def _process(self, data: AttributeMap) -> Iterable[CursorHandler]:
        usr: str = self._extract_attributes(data)
        # process child cursors using a state machine
        self._stack.extend(reversed(list(self.cursor.get_children())))
        if not self._stack:
            return ()
        self._handle_cpp_attributes(data)
        self._handle_namespaces(data)
        return self._handle_params_and_body(usr)

    def _extract_attributes(self, data: AttributeMap) -> str:
        # extract attributes from the cursor
        usr: str = self.cursor.get_usr()
        data[ASTNodeAttribute.USR] = usr
        data[ASTNodeAttribute.NAME] = self.cursor.spelling
        data[ASTNodeAttribute.DISPLAY_NAME] = self.cursor.displayname
        data[ASTNodeAttribute.RETURN_TYPE] = self.cursor.result_type.spelling
        # cursor = self.cursor.get_definition()
        return usr

    def _handle_cpp_attributes(self, data: AttributeMap):
        tags: List[str] = []
        while self._stack:
            cursor = self._stack.pop()
            if cursor.kind != CK.UNEXPOSED_ATTR:
                # return non-namespace cursor to the stack
                self._stack.append(cursor)
                break
            logger.debug(f'found child cursor: {cursor_str(cursor)}')
            for token in cursor.get_tokens():
                if token.kind == TK.IDENTIFIER:
                    tags.append(token.spelling)
                    break
        if tags:
            data[ASTNodeAttribute.ATTRIBUTES] = ','.join(tags)

    def _handle_namespaces(self, data: AttributeMap):
        parts: List[str] = []
        while self._stack:
            cursor = self._stack.pop()
            if cursor.kind == CK.NAMESPACE_REF:
                logger.debug(f'found child cursor: {cursor_str(cursor)}')
                parts.append(f'@N@{cursor.spelling}')
            elif cursor.kind == CK.TYPE_REF:
                logger.debug(f'found child cursor: {cursor_str(cursor)}')
                for token in cursor.get_tokens():
                    if token.kind == TK.IDENTIFIER:
                        parts.append(f'@S@{token.spelling}')
                        break
            else:
                # return non-namespace cursor to the stack
                self._stack.append(cursor)
                break
        if parts:
            usr = ''.join(parts)
            usr = f'c:{usr}'
            data[ASTNodeAttribute.BELONGS_TO] = usr

    def _handle_params_and_body(self, usr: str) -> Iterable[CursorHandler]:
        dependencies: List[CursorHandler] = []
        while self._stack:
            cursor = self._stack.pop()
            logger.debug(f'found child cursor: {cursor_str(cursor)}')

            # more or less ordered by likelihood
            if cursor.kind == CK.PARM_DECL:
                dependencies.append(ParameterDeclarationHandler(cursor, belongs_to=usr))
            elif cursor.kind == CK.COMPOUND_STMT:
                pass
            else:
                pass #raise TypeError(f'unexpected cursor kind: {cursor_str(cursor)}')

        return dependencies


@define
class MethodDeclarationHandler(FunctionDeclarationHandler):
    @property
    def node_type(self) -> ASTNodeType:
        if self.cursor.is_definition():
            return ASTNodeType.METHOD_DEF
        else:
            return ASTNodeType.METHOD_DECL

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.CXX_METHOD


@define
class ParameterDeclarationHandler(ScopedCursorHandler):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.PARAMETER_DECL

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.PARM_DECL

    def _process(self, data: AttributeMap) -> Iterable[CursorHandler]:
        # extract attributes from the cursor
        data[ASTNodeAttribute.USR] = self.cursor.get_usr()
        data[ASTNodeAttribute.NAME] = self.cursor.spelling
        # data[ASTNodeAttribute.DISPLAY_NAME] = self.cursor.displayname
        data[ASTNodeAttribute.DATA_TYPE] = self.cursor.type.get_canonical().spelling
        # include result type for function parameters
        if (result_type := self.cursor.result_type):
            if result_type.get_canonical().kind != clang.TypeKind.INVALID:
                data[ASTNodeAttribute.RETURN_TYPE] = result_type.spelling
        return ()  # no dependencies
