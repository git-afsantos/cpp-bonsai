# SPDX-License-Identifier: MIT
# Copyright © 2024 André Santos

###############################################################################
# Imports
###############################################################################

from typing import Any, Final, Iterable, List, Mapping, Optional

import logging
from pathlib import Path

from attrs import define
import clang.cindex as clang

from cppbonsai.ast.common import ASTNodeType, SourceLocation
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

    def process(self, annotations: Mapping[str, Any]) -> Iterable['CursorHandler']:
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
