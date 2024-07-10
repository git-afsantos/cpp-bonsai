# SPDX-License-Identifier: MIT
# Copyright © 2024 André Santos

###############################################################################
# Imports
###############################################################################

from typing import Any, Dict, Final, Iterable, List, Mapping, NewType, Optional, Tuple

from enum import Enum, auto

from attrs import field, frozen

###############################################################################
# Constants
###############################################################################

ASTNodeId = NewType('ASTNodeId', int)

NULL_ID: Final[ASTNodeId] = ASTNodeId(0)


class ASTNodeType(Enum):
    FILE = auto()
    NAMESPACE = auto()

    # C++ Statement
    STATEMENT = auto()
    EXPRESSION_STMT = auto()
    ASSIGNMENT_STMT = auto()
    DELETE_STMT = auto()
    PASS_STMT = auto()
    BREAK_STMT = auto()
    CONTINUE_STMT = auto()
    RETURN_STMT = auto()
    RAISE_STMT = auto()
    IMPORT_STMT = auto()
    GLOBAL_STMT = auto()
    NONLOCAL_STMT = auto()
    ASSERT_STMT = auto()
    IF_STMT = auto()
    WHILE_STMT = auto()
    FOR_STMT = auto()
    TRY_STMT = auto()
    MATCH_STMT = auto()
    WITH_STMT = auto()
    FUNCTION_DEF = auto()
    CLASS_DEF = auto()

    # C++ Expression
    EXPRESSION = auto()
    LITERAL = auto()
    REFERENCE = auto()
    ITEM_ACCESS = auto()
    FUNCTION_CALL = auto()
    STAR_EXPR = auto()
    GENERATOR_EXPR = auto()
    OPERATOR = auto()
    CONDITIONAL_EXPR = auto()
    LAMBDA_EXPR = auto()
    ASSIGNMENT_EXPR = auto()  # Python >= 3.8
    YIELD_EXPR = auto()
    AWAIT_EXPR = auto()

    # C++ Helper Node
    HELPER = auto()
    KEY_VALUE_NODE = auto()
    SUBSCRIPT_NODE = auto()
    ITERATOR_NODE = auto()
    ARGUMENT_NODE = auto()
    IMPORT_BASE = auto()
    IMPORTED_NAME = auto()
    FUNCTION_PARAMETER = auto()
    CONDITIONAL_BLOCK = auto()
    EXCEPT_CLAUSE = auto()
    DECORATOR = auto()
    CONTEXT_MANAGER = auto()
    CASE_STATEMENT = auto()
    CASE_PATTERN = auto()

    @property
    def is_file(self) -> bool:
        return self == ASTNodeType.FILE

    @property
    def is_statement(self) -> bool:
        return (
            self == ASTNodeType.EXPRESSION_STMT
            or self == ASTNodeType.ASSIGNMENT_STMT
            or self == ASTNodeType.DELETE_STMT
            or self == ASTNodeType.PASS_STMT
            or self == ASTNodeType.BREAK_STMT
            or self == ASTNodeType.CONTINUE_STMT
            or self == ASTNodeType.RETURN_STMT
            or self == ASTNodeType.RAISE_STMT
            or self == ASTNodeType.IMPORT_STMT
            or self == ASTNodeType.GLOBAL_STMT
            or self == ASTNodeType.NONLOCAL_STMT
            or self == ASTNodeType.ASSERT_STMT
            or self == ASTNodeType.IF_STMT
            or self == ASTNodeType.WHILE_STMT
            or self == ASTNodeType.FOR_STMT
            or self == ASTNodeType.TRY_STMT
            or self == ASTNodeType.MATCH_STMT
            or self == ASTNodeType.WITH_STMT
            or self == ASTNodeType.FUNCTION_DEF
            or self == ASTNodeType.CLASS_DEF
        )

    @property
    def is_expression(self) -> bool:
        return (
            self == ASTNodeType.LITERAL
            or self == ASTNodeType.REFERENCE
            or self == ASTNodeType.ITEM_ACCESS
            or self == ASTNodeType.FUNCTION_CALL
            or self == ASTNodeType.STAR_EXPR
            or self == ASTNodeType.GENERATOR_EXPR
            or self == ASTNodeType.OPERATOR
            or self == ASTNodeType.CONDITIONAL_EXPR
            or self == ASTNodeType.LAMBDA_EXPR
            or self == ASTNodeType.ASSIGNMENT_EXPR
            or self == ASTNodeType.YIELD_EXPR
            or self == ASTNodeType.AWAIT_EXPR
        )

    @property
    def is_helper(self) -> bool:
        return (
            self == ASTNodeType.KEY_VALUE_NODE
            or self == ASTNodeType.SUBSCRIPT_NODE
            or self == ASTNodeType.ITERATOR_NODE
            or self == ASTNodeType.ARGUMENT_NODE
            or self == ASTNodeType.IMPORT_BASE
            or self == ASTNodeType.IMPORTED_NAME
            or self == ASTNodeType.FUNCTION_PARAMETER
            or self == ASTNodeType.CONDITIONAL_BLOCK
            or self == ASTNodeType.EXCEPT_CLAUSE
            or self == ASTNodeType.DECORATOR
            or self == ASTNodeType.CONTEXT_MANAGER
            or self == ASTNodeType.CASE_STATEMENT
            or self == ASTNodeType.CASE_PATTERN
        )


###############################################################################
# Common Structures
###############################################################################


@frozen
class SourceLocation:
    line: int = 0
    column: int = 0
    file: str = ''


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


###############################################################################
# AST Structure
###############################################################################


def _ast_factory() -> Mapping[ASTNodeId, ASTNode]:
    return {NULL_ID: ASTNode(NULL_ID, ASTNodeType.FILE)}


@frozen
class AST:
    nodes: Mapping[ASTNodeId, ASTNode] = field(factory=_ast_factory)

    # @property
    # def root(self) -> CppGlobalQueryContext:
    #     return CppGlobalQueryContext(self.nodes)

    def traverse(self, start: ASTNodeId) -> None:
        node: ASTNode = self.nodes[start]
        yield node
        stack = list(reversed(node.children))
        while stack:
            cid: ASTNodeId = stack.pop()
            node = self.nodes[cid]
            yield node
            stack.extend(reversed(node.children))
