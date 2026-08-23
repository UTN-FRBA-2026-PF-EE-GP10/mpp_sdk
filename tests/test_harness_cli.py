"""Unit tests for the mpp-sdk CLI dispatcher (harness/cli.py)."""

import importlib
import sys
import types

import pytest

from harness import cli


@pytest.fixture(autouse=True)
def _fake_spidev(monkeypatch):
    # scripts/spi_test.py imports spidev unconditionally at module scope
    # (it's a real Linux-only C-backed module, not installed in this dev
    # env) - fake it out the same way tests/test_spi_mcu.py does, so
    # importing that module here doesn't require the hardware extra.
    monkeypatch.setitem(sys.modules, "spidev", types.ModuleType("spidev"))


def test_help_lists_all_subcommands(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    for name in cli._COMMANDS:
        assert name in out


def test_unknown_subcommand_exits_nonzero():
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["bogus"])
    assert exc_info.value.code != 0


@pytest.mark.parametrize(
    "slug",
    [
        "compare-static",
        "compare-dynamic",
        "compare-cyclic",
        "compare-noise",
        "compare-rescan",
        "compare-bank",
        "compare-seeds",
        "snapshot",
        "pvlib-demo",
        "export-plecs",
        "quickstart",
    ],
)
def test_dispatches_to_target_main(monkeypatch, slug):
    module_path, _ = cli._COMMANDS[slug]
    module = importlib.import_module(module_path)
    calls = []
    monkeypatch.setattr(module, "main", lambda: calls.append(True))
    cli.main([slug])
    assert calls == [True]


@pytest.mark.parametrize("slug", ["animate", "spi-test"])
def test_forwarding_subcommand_sets_argv_and_restores_it(monkeypatch, slug):
    module_path, _ = cli._COMMANDS[slug]
    module = importlib.import_module(module_path)
    seen_argv = []
    monkeypatch.setattr(module, "main", lambda: seen_argv.append(list(sys.argv)))
    original_argv = list(sys.argv)

    cli.main([slug, "--duty", "0.3"])

    assert seen_argv == [[module_path, "--duty", "0.3"]]
    assert sys.argv == original_argv


@pytest.mark.parametrize("slug", ["animate", "spi-test"])
def test_forwarding_subcommand_restores_argv_even_on_error(monkeypatch, slug):
    module_path, _ = cli._COMMANDS[slug]
    module = importlib.import_module(module_path)

    def _boom():
        raise RuntimeError("target script failed")

    monkeypatch.setattr(module, "main", _boom)
    original_argv = list(sys.argv)

    with pytest.raises(RuntimeError):
        cli.main([slug, "--duty", "0.3"])

    assert sys.argv == original_argv


def test_all_registered_modules_importable():
    for module_path, _ in cli._COMMANDS.values():
        importlib.import_module(module_path)
