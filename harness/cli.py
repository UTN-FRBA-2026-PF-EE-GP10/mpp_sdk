"""Single entry point (``mpp-sdk``) for every harness/example/script.

Every script under ``harness/``, ``examples/``, and ``scripts/`` (plus the
top-level ``main.py`` quickstart) already exposes its own ``main() -> None``
and stays directly runnable on its own (``python harness/compare_static.py``,
``python main.py``, ...) — this dispatcher is a second, discoverable way to
reach the same entry points, not a replacement. Run ``mpp-sdk --help`` (or
``python -m harness --help``) to list everything.
"""

import argparse
import importlib
import sys
from collections.abc import Sequence

# subcommand -> (module path, does the script parse its own argv?)
_COMMANDS: dict[str, tuple[str, bool]] = {
    "compare-static": ("harness.compare_static", False),
    "compare-dynamic": ("harness.compare_dynamic", False),
    "compare-cyclic": ("harness.compare_cyclic", False),
    "compare-noise": ("harness.compare_noise", False),
    "compare-rescan": ("harness.compare_rescan", False),
    "compare-bank": ("harness.compare_bank", False),
    "compare-seeds": ("harness.compare_seeds", False),
    "animate": ("harness.animate", True),
    "snapshot": ("harness.snapshot", False),
    "pvlib-demo": ("examples.pvlib_demo", False),
    "export-plecs": ("scripts.export_iv_plecs", False),
    "spi-test": ("scripts.spi_test", True),
    "quickstart": ("main", False),
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mpp-sdk",
        description="Run any mpp-sdk harness script, demo, or utility from one place.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="command")
    for name, (module_path, _) in _COMMANDS.items():
        subparsers.add_parser(name, help=module_path)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Commands that parse their own argv (animate, spi-test) get their
    # remaining args forwarded untouched. This is done by hand rather than
    # via argparse subparsers + nargs=REMAINDER: that combination mishandles
    # "-"-prefixed tokens (a known argparse limitation - REMAINDER on a
    # subparser doesn't reliably capture them), so anything past the command
    # name is never even shown to this wrapper's own parser.
    if argv and argv[0] in _COMMANDS and _COMMANDS[argv[0]][1]:
        command, rest = argv[0], argv[1:]
    else:
        command, rest = _build_parser().parse_args(argv).command, []

    module_path, forwards_argv = _COMMANDS[command]
    module = importlib.import_module(module_path)
    if forwards_argv:
        sys.argv = [module_path, *rest]
    module.main()


if __name__ == "__main__":
    main()
