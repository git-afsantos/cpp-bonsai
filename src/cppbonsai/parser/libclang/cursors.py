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

UNARY_POSTFIX_OPERATORS: Final[Iterable[str]] = ('++', '--')
UNARY_PREFIX_OPERATORS: Final[Iterable[str]] = ('++', '--', '~', '!', '+', '-')

BINARY_OPERATORS: Final[Mapping[int, str]] = {}
try:
    BINARY_OPERATORS[clang.BinaryOperator.PtrMemD.value] = '->*'
    BINARY_OPERATORS[clang.BinaryOperator.PtrMemI.value] = '.*'
    BINARY_OPERATORS[clang.BinaryOperator.Mul.value] = '*'
    BINARY_OPERATORS[clang.BinaryOperator.Div.value] = '/'
    BINARY_OPERATORS[clang.BinaryOperator.Rem.value] = '%'
    BINARY_OPERATORS[clang.BinaryOperator.Add.value] = '+'
    BINARY_OPERATORS[clang.BinaryOperator.Sub.value] = '-'
    BINARY_OPERATORS[clang.BinaryOperator.Shl.value] = '<<'
    BINARY_OPERATORS[clang.BinaryOperator.Shr.value] = '>>'
    BINARY_OPERATORS[clang.BinaryOperator.Cmp.value] = '<=>'
    BINARY_OPERATORS[clang.BinaryOperator.LT.value] = '<'
    BINARY_OPERATORS[clang.BinaryOperator.GT.value] = '>'
    BINARY_OPERATORS[clang.BinaryOperator.LE.value] = '<='
    BINARY_OPERATORS[clang.BinaryOperator.GE.value] = '>='
    BINARY_OPERATORS[clang.BinaryOperator.EQ.value] = '=='
    BINARY_OPERATORS[clang.BinaryOperator.NE.value] = '!='
    BINARY_OPERATORS[clang.BinaryOperator.And.value] = '&'
    BINARY_OPERATORS[clang.BinaryOperator.Xor.value] = '^'
    BINARY_OPERATORS[clang.BinaryOperator.Or.value] = '|'
    BINARY_OPERATORS[clang.BinaryOperator.LAnd.value] = '&&'
    BINARY_OPERATORS[clang.BinaryOperator.LOr.value] = '||'
    BINARY_OPERATORS[clang.BinaryOperator.Assign.value] = '='
    BINARY_OPERATORS[clang.BinaryOperator.MulAssign.value] = '*='
    BINARY_OPERATORS[clang.BinaryOperator.DivAssign.value] = '/='
    BINARY_OPERATORS[clang.BinaryOperator.RemAssign.value] = '%='
    BINARY_OPERATORS[clang.BinaryOperator.AddAssign.value] = '+='
    BINARY_OPERATORS[clang.BinaryOperator.SubAssign.value] = '-='
    BINARY_OPERATORS[clang.BinaryOperator.ShlAssign.value] = '<<='
    BINARY_OPERATORS[clang.BinaryOperator.ShrAssign.value] = '>>='
    BINARY_OPERATORS[clang.BinaryOperator.AndAssign.value] = '&='
    BINARY_OPERATORS[clang.BinaryOperator.XorAssign.value] = '^='
    BINARY_OPERATORS[clang.BinaryOperator.OrAssign.value] = '|='
    BINARY_OPERATORS[clang.BinaryOperator.Comma.value] = ','
except AttributeError:
    pass  # old version of libclang

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
        logger.debug(f'{self.__class__.__name__}.process()')
        self.usr = self.cursor.get_usr() or ''
        self._setup()
        dependencies: List[CursorDataExtractor] = self._process_child_cursors()
        if self.belongs_to:
            data[ASTNodeAttribute.BELONGS_TO] = self.belongs_to
        if self.usr:
            data[ASTNodeAttribute.USR] = self.usr
        self._write_custom_attributes(data)
        self._cleanup()
        return dependencies

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        raise NotImplementedError()

    def _setup(self):
        pass

    def _cleanup(self):
        pass

    def _process_child_cursors(self) -> List['CursorDataExtractor']:
        dependencies: List[CursorDataExtractor] = []
        for cursor in self.cursor.get_children():
            logger.debug(f'found child cursor: {cursor_str(cursor, verbose=True)}')
            dep = self._process_child_cursor(cursor)
            if dep is not None:
                logger.debug(f'{self.__class__.__name__}: new dependency found: {dep!r}')
                dependencies.append(dep)
        return dependencies

    def _process_child_cursor(self, cursor: clang.Cursor) -> Optional['CursorDataExtractor']:
        return None  # children (if any) are ignored

    def _write_custom_attributes(self, data: AttributeMap):
        pass


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
            return ConstructorExtractor(cursor, belongs_to=self.usr)
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
            return ConstructorExtractor(cursor, belongs_to=self.usr)
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
            return ConstructorExtractor(cursor, belongs_to=self.usr)
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
class FieldDeclarationExtractor(CursorDataExtractor):
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

    def _write_custom_attributes(self, data: AttributeMap):
        data[ASTNodeAttribute.ACCESS_SPECIFIER] = get_access_specifier(self.cursor).value
        return super()._write_custom_attributes(data)


@define
class ConstructorExtractor(FunctionDeclarationExtractor):
    _member: Optional['MemberInitializerExtractor'] = field(default=None, eq=False)

    @property
    def node_type(self) -> ASTNodeType:
        if self.cursor.is_definition():
            return ASTNodeType.CONSTRUCTOR_DEF
        else:
            return ASTNodeType.CONSTRUCTOR_DECL

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.CONSTRUCTOR

    def _setup(self):
        self._member = None

    def _cleanup(self):
        self._member = None

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        # https://en.cppreference.com/w/cpp/language/constructor
        if cursor.kind == CK.MEMBER_REF:
            self._member = MemberInitializerExtractor(cursor)
            return None
        if self._member is not None and cursor.kind.is_expression():
            member = self._member
            self._member = None
            member.expr = cursor
            return member
        return super()._process_child_cursor(cursor)

    def _write_custom_attributes(self, data: AttributeMap):
        data[ASTNodeAttribute.ACCESS_SPECIFIER] = get_access_specifier(self.cursor).value
        return super()._write_custom_attributes(data)


@define
class ParameterDeclarationExtractor(CursorDataExtractor):
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
    if k == CK.RETURN_STMT:
        return ReturnStatementExtractor(cursor, belongs_to=belongs_to)
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
class NullStatementExtractor(CursorDataExtractor):
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
        return (
            _statement_cursor(cursor, belongs_to=self.belongs_to)
            or _expression_cursor(cursor, belongs_to=self.belongs_to)
        )


@define
class ReturnStatementExtractor(CursorDataExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.RETURN_STMT

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.RETURN_STMT

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        return _expression_cursor(cursor, belongs_to=self.belongs_to)


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


@define
class MemberInitializerExtractor(CursorDataExtractor):
    expr: clang.Cursor | None = field(default=None, eq=False)

    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.MEMBER_INITIALIZER

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.MEMBER_REF

    def _process_child_cursors(self) -> List[CursorDataExtractor]:
        dependencies: List[CursorDataExtractor] = super()._process_child_cursors()
        if self.expr is not None:
            if (dep := _expression_cursor(self.expr, belongs_to=self.belongs_to)) is not None:
                dependencies.insert(0, dep)
        return dependencies

    def _write_custom_attributes(self, data: AttributeMap):
        data[ASTNodeAttribute.NAME] = self.cursor.spelling
        # data[ASTNodeAttribute.DISPLAY_NAME] = self.cursor.displayname
        data[ASTNodeAttribute.DATA_TYPE] = self.cursor.type.get_canonical().spelling


###############################################################################
# Expressions
###############################################################################


def _expression_cursor(
    cursor: clang.Cursor,
    belongs_to: str = '',
    param_index: int = -1,
) -> CursorDataExtractor | None:
    data_type: str = ''
    if cursor.kind == CK.UNEXPOSED_EXPR:
        children = list(cursor.get_children())
        if len(children) != 1:
            logger.error(f'unknown unexposed expression with {len(children)} children')
            for child in children:
                logger.debug(f'child cursor: {cursor_str(child, verbose=True)}')
            return None
        data_type = cursor.type.get_canonical().spelling
        while cursor.kind == CK.UNEXPOSED_EXPR:
            cursor = next(cursor.get_children())

    if cursor.kind == CK.CALL_EXPR:
        return FunctionCallExtractor(
            cursor,
            belongs_to=belongs_to,
            param_index=param_index,
            data_type=data_type,
        )
    if cursor.kind == CK.DECL_REF_EXPR:
        return ReferenceExtractor(
            cursor,
            belongs_to=belongs_to,
            param_index=param_index,
            data_type=data_type,
        )
    if cursor.kind == CK.MEMBER_REF_EXPR:
        return MemberReferenceExtractor(
            cursor,
            belongs_to=belongs_to,
            param_index=param_index,
            data_type=data_type,
        )
    if cursor.kind == CK.CXX_THIS_EXPR:
        return ThisReferenceExtractor(
            cursor,
            belongs_to=belongs_to,
            param_index=param_index,
            data_type=data_type,
        )
    if cursor.kind == CK.BINARY_OPERATOR:
        return BinaryOperatorExtractor(
            cursor,
            belongs_to=belongs_to,
            param_index=param_index,
            data_type=data_type,
        )
    if cursor.kind == CK.UNARY_OPERATOR:
        return UnaryOperatorExtractor(
            cursor,
            belongs_to=belongs_to,
            param_index=param_index,
            data_type=data_type,
        )
    if cursor.kind == CK.INTEGER_LITERAL:
        return IntegerLiteralExtractor(
            cursor,
            belongs_to=belongs_to,
            param_index=param_index,
            data_type=data_type,
        )
    if cursor.kind == CK.FLOATING_LITERAL:
        return FloatLiteralExtractor(
            cursor,
            belongs_to=belongs_to,
            param_index=param_index,
            data_type=data_type,
        )
    if cursor.kind == CK.CXX_BOOL_LITERAL_EXPR:
        return BooleanLiteralExtractor(
            cursor,
            belongs_to=belongs_to,
            param_index=param_index,
            data_type=data_type,
        )
    if cursor.kind == CK.PAREN_EXPR:
        return ParenthesisExpressionExtractor(
            cursor,
            belongs_to=belongs_to,
            param_index=param_index,
            data_type=data_type,
        )
    if cursor.kind.is_expression():
        return UnknownExpressionExtractor(
            cursor,
            belongs_to=belongs_to,
            param_index=param_index,
            data_type=data_type,
        )
    return None


@define
class ExpressionExtractor(CursorDataExtractor):
    data_type: str = field(default='', eq=False)
    # if this is an argument for a function call, store its position
    param_index: int = field(default=-1, eq=False)

    def _write_custom_attributes(self, data: AttributeMap):
        data_type = self.data_type or self.cursor.type.get_canonical().spelling
        data[ASTNodeAttribute.DATA_TYPE] = data_type
        if self.param_index >= 0:
            data[ASTNodeAttribute.PARAMETER_INDEX] = str(self.param_index)


@define
class UnknownExpressionExtractor(ExpressionExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.UNKNOWN_EXPR

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind.is_expression()

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        return _expression_cursor(cursor, belongs_to=self.belongs_to)

    def _write_custom_attributes(self, data: AttributeMap):
        super()._write_custom_attributes(data)
        data[ASTNodeAttribute.CURSOR] = str(self.cursor.kind)


@define
class ParenthesisExpressionExtractor(ExpressionExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.PARENTHESIS_EXPR

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.PAREN_EXPR

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        return _expression_cursor(cursor, belongs_to=self.belongs_to)


@define
class IntegerLiteralExtractor(ExpressionExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.INTEGER_LITERAL

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.INTEGER_LITERAL

    def _write_custom_attributes(self, data: AttributeMap):
        super()._write_custom_attributes(data)
        for token in self.cursor.get_tokens():
            if token.kind == TK.LITERAL:
                if (value := token.spelling).isnumeric():
                    data[ASTNodeAttribute.VALUE] = value
                    break


@define
class FloatLiteralExtractor(ExpressionExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.FLOAT_LITERAL

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.FLOATING_LITERAL

    def _write_custom_attributes(self, data: AttributeMap):
        super()._write_custom_attributes(data)
        for token in self.cursor.get_tokens():
            if token.kind == TK.LITERAL:
                if (value := token.spelling).isnumeric():
                    data[ASTNodeAttribute.VALUE] = value
                    break


@define
class BooleanLiteralExtractor(ExpressionExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.BOOLEAN_LITERAL

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.CXX_BOOL_LITERAL_EXPR

    def _write_custom_attributes(self, data: AttributeMap):
        super()._write_custom_attributes(data)
        for token in self.cursor.get_tokens():
            if token.kind == TK.KEYWORD:
                if (value := token.spelling) == 'true' or value == 'false':
                    data[ASTNodeAttribute.VALUE] = value
                    break


@define
class OperatorExtractor(ExpressionExtractor):
    _arg_index: int = field(default=-1, eq=False)

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        self._arg_index += 1
        return _expression_cursor(cursor, belongs_to=self.belongs_to, param_index=self._arg_index)


@define
class UnaryOperatorExtractor(OperatorExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.UNARY_OPERATOR

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.UNARY_OPERATOR

    def _write_custom_attributes(self, data: AttributeMap):
        super()._write_custom_attributes(data)
        # post-fix operators have priority
        # https://cplusplus.com/doc/tutorial/operators/
        tokens = list(self.cursor.get_tokens())
        if (name := tokens[-1].spelling) in UNARY_POSTFIX_OPERATORS:
            data[ASTNodeAttribute.NAME] = name
            data[ASTNodeAttribute.DISPLAY_NAME] = f'operator{name}'
        elif (name := tokens[0].spelling) in UNARY_PREFIX_OPERATORS:
            data[ASTNodeAttribute.NAME] = name
            data[ASTNodeAttribute.DISPLAY_NAME] = f'operator{name}'
        else:
            logger.debug(f'unknown unary operator: {tokens}')


@define
class BinaryOperatorExtractor(OperatorExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.BINARY_OPERATOR

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.BINARY_OPERATOR

    def _write_custom_attributes(self, data: AttributeMap):
        super()._write_custom_attributes(data)
        if BINARY_OPERATORS:
            opcode = self.cursor.binary_operator.value
            name: str = BINARY_OPERATORS[opcode]
        else:
            # older version of libclang
            # all operators are infix
            prefix: int = len(list(next(self.cursor.get_children()).get_tokens()))
            tokens = list(self.cursor.get_tokens())[prefix:]
            for token in tokens:
                if token.kind == TK.PUNCTUATION:
                    data[ASTNodeAttribute.NAME] = token.spelling
                    data[ASTNodeAttribute.DISPLAY_NAME] = f'operator{token.spelling}'
                    break
7

@define
class ThisReferenceExtractor(ExpressionExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.THIS_REFERENCE

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.CXX_THIS_EXPR


@define
class ReferenceExtractor(ExpressionExtractor):
    namespace: NamespaceReferenceHandler = field(factory=NamespaceReferenceHandler, eq=False)

    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.DECL_REFERENCE

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.DECL_REF_EXPR

    def _setup(self):
        self.namespace = NamespaceReferenceHandler()

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        consumed = self.namespace.consume(cursor)
        assert consumed
        return None

    def _write_custom_attributes(self, data: AttributeMap):
        super()._write_custom_attributes(data)
        name: str = self.cursor.spelling
        data[ASTNodeAttribute.NAME] = name
        if (ns := self.namespace.get()):
            data[ASTNodeAttribute.DISPLAY_NAME] = f'{ns}::{name}'
        else:
            data[ASTNodeAttribute.DISPLAY_NAME] = name
        if (cursor := self.cursor.get_definition()):
            if (usr := cursor.get_usr()):
                data[ASTNodeAttribute.DEFINITION] = usr


@define
class MemberReferenceExtractor(ReferenceExtractor):
    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.MEMBER_REFERENCE

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.MEMBER_REF_EXPR

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        if (value := _expression_cursor(cursor, belongs_to=self.belongs_to)) is not None:
            return value
        return super()._process_child_cursor(cursor)


@define
class FunctionCallExtractor(ExpressionExtractor):
    _arguments: List[clang.Cursor] = field(factory=list, eq=False)
    _arg_index: int = field(default=0, eq=False)

    @property
    def node_type(self) -> ASTNodeType:
        return ASTNodeType.FUNCTION_CALL

    def _is_valid_cursor(self, cursor: clang.Cursor) -> bool:
        return cursor.kind == CK.CALL_EXPR

    def _setup(self):
        # Build a stack of arguments so that lookup and removal
        # are more efficient. This assumes that child cursors
        # will always respect the ordering of argument cursors.
        self._arguments = list(self.cursor.get_arguments())
        self._arguments.reverse()
        self._arg_index = 0

    def _cleanup(self):
        for cursor in self._arguments:
            logger.error(
                f'{self.__class__.__name__}: unhandled argument cursor: '
                f'{cursor_str(cursor, verbose=True)}'
            )

    def _process_child_cursor(self, cursor: clang.Cursor) -> CursorDataExtractor | None:
        i = -1
        if self._arguments and cursor == self._arguments[-1]:
            self._arguments.pop()
            i = self._arg_index
            self._arg_index += 1
        return _expression_cursor(cursor, belongs_to=self.belongs_to, param_index=i)

    def _write_custom_attributes(self, data: AttributeMap):
        super()._write_custom_attributes(data)
        data[ASTNodeAttribute.NAME] = self.cursor.spelling
