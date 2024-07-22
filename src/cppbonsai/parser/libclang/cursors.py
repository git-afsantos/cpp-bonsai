# SPDX-License-Identifier: MIT
# Copyright © 2024 André Santos

###############################################################################
# Imports
###############################################################################

from typing import Any, Final, Iterable, List, Optional

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
# Cursor Handlers
###############################################################################


@define
class NodeAttributeGenerator:
    discard_on_reject: bool = True

    @property
    def key(self) -> ASTNodeAttribute:
        raise NotImplementedError()

    def consume(self, cursor: clang.Cursor) -> bool:
        raise NotImplementedError()

    def get(self) -> Any:
        raise NotImplementedError()


@define
class NamespaceReferenceHandler(NodeAttributeGenerator):
    items: List[str] = field(factory=list)

    @property
    def key(self) -> ASTNodeAttribute:
        return ASTNodeAttribute.BELONGS_TO

    def consume(self, cursor: clang.Cursor) -> bool:
        if cursor.kind == CK.NAMESPACE_REF:
            self.items.append(f'@N@{cursor.spelling}')
            return True
        if cursor.kind == CK.TYPE_REF:
            for token in cursor.get_tokens():
                if token.kind == TK.IDENTIFIER:
                    self.items.append(f'@S@{token.spelling}')
                    return True
        return False

    def get(self) -> str:
        return '' if not self.items else f'c:{"".join(self.items)}'


@define
class BaseClassHandler(NodeAttributeGenerator):
    items: List[str] = field(factory=list)

    @property
    def key(self) -> ASTNodeAttribute:
        return ASTNodeAttribute.BASE_CLASSES

    def consume(self, cursor: clang.Cursor) -> bool:
        if cursor.kind == CK.CXX_BASE_SPECIFIER:
            self.items.append(cursor.spelling)
            return True
        return False

    def get(self) -> str:
        return '' if not self.items else ','.join(self.items)


@define
class CppAttributeHandler(NodeAttributeGenerator):
    items: List[str] = field(factory=list)

    @property
    def key(self) -> ASTNodeAttribute:
        return ASTNodeAttribute.ATTRIBUTES

    def consume(self, cursor: clang.Cursor) -> bool:
        if cursor.kind == CK.UNEXPOSED_ATTR:
            for token in cursor.get_tokens():
                if token.kind == TK.IDENTIFIER:
                    self.items.append(token.spelling)
                    return True
        return False

    def get(self) -> str:
        return '' if not self.items else ','.join(self.items)


###############################################################################
# Cursor Data Extractor
###############################################################################


@define
class CursorDataExtractor:
    cursor: clang.Cursor = field()
    belongs_to: str = field(default='', eq=False)
    usr: str = field(default='', eq=False)

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

    def process(self, data: AttributeMap) -> Iterable['CursorDataExtractor']:
        class_name: str = self.__class__.__name__
        logger.debug(f'{class_name}.process()')
        self.usr = self.cursor.get_usr() or ''
        dependencies: List[CursorDataExtractor] = []
        for cursor in self.cursor.get_children():
            logger.debug(f'found child cursor: {cursor_str(cursor, verbose=True)}')
            dep = self._process_child_cursor(cursor)
            if dep is not None:
                logger.debug(f'{class_name}: new dependency found: {dep!r}')
                dependencies.append(dep)
        if self.belongs_to:
            data[ASTNodeAttribute.BELONGS_TO] = self.belongs_to
        if self.usr:
            data[ASTNodeAttribute.USR] = self.usr
        self._write_custom_attributes(data)
        return dependencies

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        raise NotImplementedError()

    def _setup(self):
        pass

    def _process_child_cursor(self, cursor: clang.Cursor) -> Optional['CursorDataExtractor']:
        raise NotImplementedError()

    def _write_custom_attributes(self, data: AttributeMap):
        pass


@define
class LeafCursorDataExtractor(CursorDataExtractor):
    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        return None  # children (if any) are ignored


###############################################################################
# Top-level Cursors
###############################################################################


@define
class TranslationUnitExtractor(CursorDataExtractor):
    workspace: Path | None = None

    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.FILE

    @property
    def location(self) -> SourceLocation:
        return SourceLocation(file=self.cursor.spelling)

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.TRANSLATION_UNIT

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        loc_file: clang.File | None = cursor.location.file
        if loc_file is None:
            return None
        file_path: Path = Path(loc_file.name)
        if self.workspace and (self.workspace not in file_path.parents):
            return None
        # if not loc_file.name.startswith(str(self.workspace)):
        #     return False
        if cursor.kind == CK.NAMESPACE:
            return NamespaceExtractor(cursor)
        if cursor.kind == CK.CLASS_DECL:
            return ClassDeclarationExtractor(cursor)
        if cursor.kind == CK.FUNCTION_DECL:
            return FunctionDeclarationExtractor(cursor)
        if cursor.kind == CK.STRUCT_DECL:
            pass  # dependencies.append(ClassDeclarationExtractor(cursor, belongs_to=usr))
        if cursor.kind == CK.CXX_METHOD:
            return MethodDeclarationExtractor(cursor, belongs_to=self.usr)
        if cursor.kind == CK.CONSTRUCTOR:
            pass
        if cursor.kind == CK.DESTRUCTOR:
            pass
        if cursor.kind == CK.UNION_DECL:
            pass
        return None


@define
class NamespaceExtractor(CursorDataExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.NAMESPACE

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.NAMESPACE

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        if cursor.kind == CK.NAMESPACE:
            return NamespaceExtractor(cursor, belongs_to=self.usr)
        if cursor.kind == CK.CLASS_DECL:
            return ClassDeclarationExtractor(cursor, belongs_to=self.usr)
        if cursor.kind == CK.FUNCTION_DECL:
            return FunctionDeclarationExtractor(cursor, belongs_to=self.usr)
        if cursor.kind == CK.STRUCT_DECL:
            pass  # return ClassDeclarationExtractor(cursor, belongs_to=self.usr)
        if cursor.kind == CK.CXX_METHOD:
            return MethodDeclarationExtractor(cursor, belongs_to=self.usr)
        if cursor.kind == CK.CONSTRUCTOR:
            pass
        if cursor.kind == CK.DESTRUCTOR:
            pass
        if cursor.kind == CK.UNION_DECL:
            pass
        return None

    def _write_custom_attributes(self, data: AttributeMap):
        data[ASTNodeAttribute.NAME] = self.cursor.spelling


###############################################################################
# Classes and Fields
###############################################################################


@define
class ClassDeclarationExtractor(CursorDataExtractor):
    base_classes: BaseClassHandler = field(factory=BaseClassHandler, eq=False)

    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.CLASS_DEF if self.cursor.is_definition() else ASTNodeType.CLASS_DECL

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.CLASS_DECL

    def _setup(self):
        self.base_classes = BaseClassHandler()

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        if (dep := self._process_member(cursor)) is not None:
            return dep
        self.base_classes.consume(cursor)
        return None

    def _write_custom_attributes(self, data: AttributeMap):
        data[ASTNodeAttribute.NAME] = self.cursor.spelling
        # data[ASTNodeAttribute.DISPLAY_NAME] = self.cursor.displayname
        # cursor = self.cursor.get_definition()
        if (bases := self.base_classes.get()):
            data[self.base_classes.key] = bases

    def _process_member(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        # more or less ordered by likelihood
        if cursor.kind == CK.CXX_METHOD:
            return MethodDeclarationExtractor(cursor, belongs_to=self.usr)
        if cursor.kind == CK.FIELD_DECL:
            return FieldDeclarationExtractor(cursor, belongs_to=self.usr)
        if cursor.kind == CK.CONSTRUCTOR:
            pass
        if cursor.kind == CK.DESTRUCTOR:
            pass
        if cursor.kind == CK.CLASS_DECL:
            return ClassDeclarationExtractor(cursor, belongs_to=self.usr)
        if cursor.kind == CK.STRUCT_DECL:
            pass  # return ClassDeclarationExtractor(cursor, belongs_to=self.usr)
        if cursor.kind == CK.UNION_DECL:
            pass
        if cursor.kind == CK.CXX_ACCESS_SPEC_DECL:
            pass  # handled via cursor properties
        return None


@define
class FieldDeclarationExtractor(LeafCursorDataExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.FIELD_DECL

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.FIELD_DECL

    def _write_custom_attributes(self, data: AttributeMap):
        data[ASTNodeAttribute.NAME] = self.cursor.spelling
        # data[ASTNodeAttribute.DISPLAY_NAME] = self.cursor.displayname
        data[ASTNodeAttribute.DATA_TYPE] = self.cursor.type.get_canonical().spelling
        data[ASTNodeAttribute.ACCESS_SPECIFIER] = get_access_specifier(self.cursor).value
        # boolean = self.cursor.is_mutable_field()


###############################################################################
# Functions, Methods, Constructors, Etc
###############################################################################


@define
class FunctionDeclarationExtractor(CursorDataExtractor):
    namespace: NamespaceReferenceHandler = field(factory=NamespaceReferenceHandler, eq=False)
    attributes: CppAttributeHandler = field(factory=CppAttributeHandler, eq=False)

    @property
    def node_type(self) -> ASTNodeType:
        if self.cursor.is_definition():
            return ASTNodeType.FUNCTION_DEF
        else:
            return ASTNodeType.FUNCTION_DECL

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.FUNCTION_DECL

    def _setup(self):
        self.namespace = NamespaceReferenceHandler()
        self.attributes = CppAttributeHandler()

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        if cursor.kind == CK.PARM_DECL:
            return ParameterDeclarationExtractor(cursor, belongs_to=self.usr)
        if cursor.kind == CK.COMPOUND_STMT:
            return CompoundStatementExtractor(cursor, belongs_to=self.usr)
        if self.namespace.consume(cursor):
            return None
        self.attributes.consume(cursor)
        return None

    def _write_custom_attributes(self, data: AttributeMap):
        data[ASTNodeAttribute.NAME] = self.cursor.spelling
        data[ASTNodeAttribute.DISPLAY_NAME] = self.cursor.displayname
        data[ASTNodeAttribute.RETURN_TYPE] = self.cursor.result_type.spelling
        # cursor = self.cursor.get_definition()
        if (value := self.namespace.get()):
            data[self.namespace.key] = value
        if (value := self.attributes.get()):
            data[self.attributes.key] = value


@define
class MethodDeclarationExtractor(FunctionDeclarationExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        if self.cursor.is_definition():
            return ASTNodeType.METHOD_DEF
        else:
            return ASTNodeType.METHOD_DECL

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.CXX_METHOD


@define
class ParameterDeclarationExtractor(LeafCursorDataExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.PARAMETER_DECL

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.PARM_DECL

    def _write_custom_attributes(self, data: AttributeMap):
        data[ASTNodeAttribute.NAME] = self.cursor.spelling
        # data[ASTNodeAttribute.DISPLAY_NAME] = self.cursor.displayname
        data[ASTNodeAttribute.DATA_TYPE] = self.cursor.type.get_canonical().spelling
        # include result type for function parameters
        if (result_type := self.cursor.result_type):
            if result_type.get_canonical().kind != clang.TypeKind.INVALID:
                data[ASTNodeAttribute.RETURN_TYPE] = result_type.spelling


###############################################################################
# Statements
###############################################################################


def _statement_cursor(cursor: clang.Cursor, belongs_to: str = '') -> CursorDataExtractor | None:
    k = cursor.kind
    if k == CK.DECL_STMT:
        return DeclarationStatementExtractor(cursor, belongs_to=belongs_to)
    # if k == CK.CALL_EXPR:
    #     return None
    if k == CK.WHILE_STMT:
        return WhileStatementExtractor(cursor, belongs_to=belongs_to)
    # if k == CK.RETURN_STMT:
    #     return None
    # if k == CK.CXX_NEW_EXPR:
    #     return None
    # if k == CK.CXX_DELETE_EXPR:
    #     return None
    if k == CK.COMPOUND_STMT:
        return CompoundStatementExtractor(cursor, belongs_to=belongs_to)
    if k == CK.NULL_STMT:
        return NullStatementExtractor(cursor, belongs_to=belongs_to)
    if k.is_statement():
        return StatementExtractor(cursor, belongs_to=belongs_to)
    return None


@define
class NullStatementExtractor(LeafCursorDataExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.NULL_STMT

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.NULL_STMT


@define
class StatementExtractor(CursorDataExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.UNKNOWN_STMT

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind.is_statement()

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        return (
            _expression_cursor(cursor, belongs_to=self.belongs_to)
            or _statement_cursor(cursor, belongs_to=self.belongs_to)
        )

    def _write_custom_attributes(self, data: AttributeMap):
        data[ASTNodeAttribute.CURSOR] = str(self.cursor.kind)


@define
class CompoundStatementExtractor(CursorDataExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.COMPOUND_STMT

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.COMPOUND_STMT

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        return _statement_cursor(cursor, belongs_to=self.belongs_to)


@define
class DeclarationStatementExtractor(CursorDataExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.DECLARATION_STMT

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.DECL_STMT

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        if cursor.kind == CK.VAR_DECL:
            return VariableDeclarationExtractor(cursor, belongs_to=self.belongs_to)
        return None


@define
class VariableDeclarationExtractor(CursorDataExtractor):
    # type_ref: NamespaceReferenceHandler = field(factory=NamespaceReferenceHandler, eq=False)

    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.VARIABLE_DECL

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.VAR_DECL

    # def _setup(self):
    #     self.type_ref = NamespaceReferenceHandler()

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        if (expr := _expression_cursor(cursor, belongs_to=self.usr)) is not None:
            return expr
        # ignore TYPE_REF and NAMESPACE_REF cursors
        # self.type_ref.consume(cursor)
        return None

    def _write_custom_attributes(self, data: AttributeMap):
        data[ASTNodeAttribute.NAME] = self.cursor.spelling
        data[ASTNodeAttribute.DATA_TYPE] = self.cursor.type.get_canonical().spelling
        # if (value := self.type_ref.get()):
        #     data[self.type_ref.key] = value


@define
class WhileStatementExtractor(CursorDataExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.WHILE_STMT

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.WHILE_STMT

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        return (
            _expression_cursor(cursor, belongs_to=self.belongs_to)
            or _statement_cursor(cursor, belongs_to=self.belongs_to)
        )


###############################################################################
# Expressions
###############################################################################


def _expression_cursor(cursor: clang.Cursor, belongs_to: str = '') -> CursorDataExtractor | None:
    if cursor.kind.is_expression():
        return ExpressionExtractor(cursor)
    return None


@define
class ExpressionExtractor(CursorDataExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.UNKNOWN_EXPR

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind.is_expression()

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        return _expression_cursor(cursor, belongs_to=self.belongs_to)

    def _write_custom_attributes(self, data: AttributeMap):
        data[ASTNodeAttribute.DATA_TYPE] = self.cursor.type.get_canonical().spelling
        data[ASTNodeAttribute.CURSOR] = str(self.cursor.kind)
