# SPDX-License-Identifier: MIT
# Copyright © 2024 André Santos

###############################################################################
# Imports
###############################################################################

from typing import Any, Final, Iterable, Mapping, NewType

from collections import UserDict
from enum import Enum, auto

from attrs import field, frozen

###############################################################################
# Constants
###############################################################################

ASTNodeId = NewType('ASTNodeId', int)

NULL_ID: Final[ASTNodeId] = ASTNodeId(0)


class ASTNodeType(Enum):
    UNKNOWN = auto()
    FILE = auto()
    NAMESPACE = auto()

    # C++ Declarations and Definitions
    CLASS_DECL = auto()
    CLASS_DEF = auto()
    FIELD_DECL = auto()
    FUNCTION_DECL = auto()
    FUNCTION_DEF = auto()
    METHOD_DECL = auto()
    METHOD_DEF = auto()
    CONSTRUCTOR_DECL = auto()
    CONSTRUCTOR_DEF = auto()
    PARAMETER_DECL = auto()

    # C++ Statement
    STATEMENT = auto()
    IF_STMT = auto()

    # C++ Expression
    EXPRESSION = auto()
    LITERAL = auto()

    # C++ Helper Node
    HELPER = auto()

    @property
    def is_file(self) -> bool:
        return self == ASTNodeType.FILE

    @property
    def is_namespace(self) -> bool:
        return self == ASTNodeType.NAMESPACE

    @property
    def is_declaration(self) -> bool:
        return (
            self == ASTNodeType.CLASS_DECL
            or self == ASTNodeType.FIELD_DECL
            or self == ASTNodeType.FUNCTION_DECL
            or self == ASTNodeType.CONSTRUCTOR_DECL
            or self == ASTNodeType.METHOD_DECL
            or self == ASTNodeType.PARAMETER_DECL
        )

    @property
    def is_definition(self) -> bool:
        return (
            self == ASTNodeType.CLASS_DEF
            or self == ASTNodeType.FUNCTION_DEF
            or self == ASTNodeType.METHOD_DEF
            or self == ASTNodeType.CONSTRUCTOR_DEF
        )

    @property
    def is_function(self) -> bool:
        return (
            self == ASTNodeType.FUNCTION_DECL
            or self == ASTNodeType.FUNCTION_DEF
            or self == ASTNodeType.METHOD_DECL
            or self == ASTNodeType.METHOD_DEF
            or self == ASTNodeType.CONSTRUCTOR_DECL
            or self == ASTNodeType.CONSTRUCTOR_DEF
        )

    @property
    def is_statement(self) -> bool:
        return (
            self == ASTNodeType.IF_STMT
            # or self == ASTNodeType.ASSIGNMENT_STMT
        )

    @property
    def is_expression(self) -> bool:
        return (
            self == ASTNodeType.LITERAL
        )

    @property
    def is_helper(self) -> bool:
        return (
            self == ASTNodeType.HELPER
        )


class ASTNodeAttribute(Enum):
    NAME = auto()
    USR = auto()
    DISPLAY_NAME = auto()
    DATA_TYPE = auto()
    RETURN_TYPE = auto()
    ACCESS_SPECIFIER = auto()
    BASE_CLASSES = auto()
    BELONGS_TO = auto()
    ATTRIBUTES = auto()


class AccessSpecifier(Enum):
    PUBLIC = 'public'
    PRIVATE = 'private'
    PROTECTED = 'protected'


###############################################################################
# Common Structures
###############################################################################


@frozen
class SourceLocation:
    line: int = 0
    column: int = 0
    file: str = ''

    def pretty_str(self) -> str:
        return f'{self.file}:{self.line}:{self.column}'


@frozen
class AttributeMap:
    data: Mapping[str, Any] = field(factory=dict)

    def get(self, key: ASTNodeAttribute, default: Any):
        return self.data.get(key.name, default=default)

    def __getitem__(self, key: ASTNodeAttribute):
        return self.data[key.name]

    def __setitem__(self, key: ASTNodeAttribute, value: Any):
        self.data[key.name] = value


###############################################################################
# AST Nodes
###############################################################################


@frozen
class ASTNode:
    id: ASTNodeId
    type: ASTNodeType
    parent: ASTNodeId = field(default=NULL_ID, eq=False)
    children: Iterable[ASTNodeId] = field(factory=tuple, converter=tuple, eq=False)
    annotations: Mapping[str, Any] = field(factory=dict, eq=False)
    location: SourceLocation = field(factory=SourceLocation, eq=False)

    @property
    def is_root(self) -> bool:
        return self.id == NULL_ID

    def pretty_str(self, indent: int = 0) -> str:
        ws = ' ' * indent
        lines = []
        lines.append(f'{ws}type: {self.type.name}')
        lines.append(f'{ws}parent: {self.parent}')
        lines.append(f'{ws}children: {self.children}')
        lines.append(f'{ws}location: {self.location.pretty_str()}')
        if self.annotations:
            lines.append(f'{ws}annotations:')
            for key, value in self.annotations.items():
                lines.append(f'{ws}  {key}: {value}')
        else:
            lines.append(f'{ws}annotations: {{}}')
        return '\n'.join(lines)


###############################################################################
# AST Structure
###############################################################################


def _ast_factory() -> Mapping[ASTNodeId, ASTNode]:
    return {NULL_ID: ASTNode(NULL_ID, ASTNodeType.FILE)}


@frozen
class AST:
    name: str = ''
    nodes: Mapping[ASTNodeId, ASTNode] = field(factory=_ast_factory)

    # @property
    # def root(self) -> CppGlobalQueryContext:
    #     return CppGlobalQueryContext(self.nodes)

    def traverse(self, start: ASTNodeId) -> Iterable[ASTNode]:
        node: ASTNode = self.nodes[start]
        yield node
        stack = list(reversed(node.children))
        while stack:
            cid: ASTNodeId = stack.pop()
            node = self.nodes[cid]
            yield node
            stack.extend(reversed(node.children))

    def pretty_str(self, indent: int = 0) -> str:
        ws = ' ' * indent
        lines = [f'{ws}AST:', f'{ws}  name: {self.name!r}']
        entries = list(self.nodes.items())
        entries.sort(key=lambda e: e[0])
        for key, node in entries:
            lines.append(f'{ws}  {key}:')
            lines.append(node.pretty_str(indent=(indent + 4)))
        return '\n'.join(lines)
