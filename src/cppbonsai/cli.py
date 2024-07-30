# SPDX-License-Identifier: MIT
# Copyright © 2024 André Santos

"""
Module that contains the command line program.

Why does this file exist, and why not put this in __main__?

  In some cases, it is possible to import `__main__.py` twice.
  This approach avoids that. Also see:
  https://click.palletsprojects.com/en/5.x/setuptools/#setuptools-integration

Some of the structure of this file came from this StackExchange question:
  https://softwareengineering.stackexchange.com/q/418600
"""

###############################################################################
# Imports
###############################################################################

from typing import Any, Dict, Final, List, Optional

import argparse
import logging
from pathlib import Path
import sys

from cppbonsai import __version__ as current_version
from cppbonsai.parser.libclang import ClangParser

###############################################################################
# Constants
###############################################################################

PROG: Final[str] = 'cppbonsai'

logger: Final[logging.Logger] = logging.getLogger(__name__)

###############################################################################
# Argument Parsing
###############################################################################


def parse_arguments(argv: Optional[List[str]]) -> Dict[str, Any]:
    msg = 'A short description of the project.'
    parser = argparse.ArgumentParser(description=msg)

    parser.add_argument(
        '--version',
        action='version',
        version=f'{PROG} {current_version}',
        help='prints the program version',
    )

    parser.add_argument(
        '-v',
        '--verbosity',
        metavar='N',
        default=argparse.SUPPRESS,
        type=int,
        help='the desired verbosity level',
    )

    parser.add_argument(
        '--print',
        action='store_true',
        help='print only the clang AST',
    )

    parser.add_argument(
        '-i',
        '--include',
        metavar='PATH',
        action='append',
        help='add an include path',
    )

    parser.add_argument(
        'args',
        metavar='ARG',
        nargs=argparse.REMAINDER,
        help='Arguments for the program.'
    )

    args = parser.parse_args(args=argv)
    return vars(args)


###############################################################################
# Setup
###############################################################################


def load_configs(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        config: Dict[str, Any] = {}
        # with open(args['config_path'], 'r') as file_pointer:
        # yaml.safe_load(file_pointer)

        # arrange and check configs here

        return config
    except Exception as err:
        # log or raise errors
        logger.exception(str(err))
        if str(err) == 'Really Bad':
            raise err

        # Optional: return some sane fallback defaults.
        sane_defaults: Dict[str, Any] = {}
        return sane_defaults


###############################################################################
# Commands
###############################################################################


def do_real_work(args: Dict[str, Any], configs: Dict[str, Any]) -> None:
    logger.debug(f'Arguments: {args}')
    logger.debug(f'Configurations: {configs}')

    parser = ClangParser(
        lib_path=Path('/usr/lib/llvm-15/lib'),
        lib_file=Path('/usr/lib/llvm-15/lib/libclang.so'),
        includes=Path('/usr/lib/llvm-15/lib/clang/15.0.7/include'),
    )

    includes: List[Path] = []
    for arg in args.get('include', ()):
        logger.debug(f'add include path: {arg}')
        path = Path(arg).resolve(strict=True)
        logger.debug(f'resolved include path: {path}')
        includes.append(path)
    parser.user_includes = includes

    for arg in args['args']:
        logger.debug(f'file path argument: {arg}')
        file_path = Path(arg).resolve(strict=True)
        parser.workspace = file_path.parent
        logger.debug(f'resolved file path: {file_path}')
        print('[AST]', file_path)
        if args.get('print', False):
            verbosity = args.get('verbosity', 0)
            print(parser.get_clang_ast(file_path, verbosity=verbosity))
        else:
            ast = parser.parse(file_path)
            print(ast.pretty_str(hierarchical=True))


###############################################################################
# Entry Point
###############################################################################


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_arguments(argv)
    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

    try:
        # Load additional config files here, e.g., from a path given via args.
        # Alternatively, set sane defaults if configuration is missing.
        config = load_configs(args)
        do_real_work(args, config)

    except KeyboardInterrupt:
        logging.error('Aborted manually.')
        return 1

    except Exception as err:
        # In real code the `except` would probably be less broad.
        # Turn exceptions into appropriate logs and/or console output.

        print('An unhandled exception crashed the application!', file=sys.stderr)
        logging.exception(str(err))

        # Non-zero return code to signal error.
        # It can, of course, be more fine-grained than this general code.
        return 1

    return 0  # success
