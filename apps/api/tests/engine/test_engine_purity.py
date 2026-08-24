"""The engine's purity is a property of the code, not a promise in a comment."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import kira.engine

ENGINE_DIR = Path(kira.engine.__file__).parent
ENGINE_FILES = sorted(ENGINE_DIR.glob("*.py"))

FORBIDDEN_CALLS = {"round", "float", "open", "print", "input"}
FORBIDDEN_IMPORT_ROOTS = {
    "kira.api",
    "kira.services",
    "kira.adapters",
    "kira.db",
    "kira.agent",
    "kira.seed",
    "sqlalchemy",
    "fastapi",
    "httpx",
    "requests",
    "asyncio",
    "random",
    "time",
}


def parsed(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def test_engine_has_files():
    assert ENGINE_FILES


@pytest.mark.parametrize("path", ENGINE_FILES, ids=lambda p: p.name)
def test_no_float_anywhere(path: Path):
    for node in ast.walk(parsed(path)):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            pytest.fail(f"{path.name}:{node.lineno} contains the float literal {node.value!r}")
        if isinstance(node, ast.Name) and node.id == "float":
            pytest.fail(f"{path.name}:{node.lineno} references float")


@pytest.mark.parametrize("path", ENGINE_FILES, ids=lambda p: p.name)
def test_no_true_division(path: Path):
    for node in ast.walk(parsed(path)):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            pytest.fail(
                f"{path.name}:{node.lineno} uses '/', which produces a float. "
                "Use round_half_up or Money.divide_floor."
            )


@pytest.mark.parametrize("path", ENGINE_FILES, ids=lambda p: p.name)
def test_no_builtin_round_or_io(path: Path):
    for node in ast.walk(parsed(path)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                pytest.fail(
                    f"{path.name}:{node.lineno} calls {node.func.id}(). "
                    "The engine is pure and rounds half-up via round_half_up."
                )


@pytest.mark.parametrize("path", ENGINE_FILES, ids=lambda p: p.name)
def test_no_clock_reads(path: Path):
    for node in ast.walk(parsed(path)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"today", "now", "utcnow"}:
                pytest.fail(
                    f"{path.name}:{node.lineno} reads the clock. "
                    "Dates arrive on the Snapshot."
                )


@pytest.mark.parametrize("path", ENGINE_FILES, ids=lambda p: p.name)
def test_imports_only_stdlib_and_money(path: Path):
    for node in ast.walk(parsed(path)):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            for forbidden in FORBIDDEN_IMPORT_ROOTS:
                if name == forbidden or name.startswith(forbidden + "."):
                    pytest.fail(f"{path.name}:{node.lineno} imports {name}")
            if name.startswith("kira.") and name not in {"kira.money"} and not name.startswith(
                "kira.engine"
            ):
                pytest.fail(f"{path.name}:{node.lineno} imports {name}")


def test_import_linter_contracts_hold():
    # `python -m importlinter.cli lint` is a documented-looking but inert
    # invocation: importlinter/cli.py defines the `import_linter` click group
    # and its `lint` subcommand but has no `if __name__ == "__main__":` block,
    # so running the module with `-m` imports it and does nothing (exit 0)
    # regardless of whether any contract holds -- a silent, vacuous pass.
    # Invoke the click group's entry point function directly instead, the
    # same way the installed `import-linter` console script does, so this
    # test actually exercises import-linter's contract checking.
    code = (
        "import sys\n"
        "from importlinter.cli import import_linter\n"
        "sys.argv = ['import-linter', 'lint']\n"
        "import_linter()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(kira.engine.__file__).parents[2],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
