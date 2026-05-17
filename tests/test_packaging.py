"""Locks in the wheel-packaging contract: only `src/` ships, never `tests/`.

Plan 5a deferred review issue #4. The original setup.py used bare
`find_packages()` which discovers tests/ via its `__init__.py` and bundled
the test suite into the installable wheel. The fix is in pyproject.toml's
`[tool.setuptools.packages.find]`; this test guards against accidental
regressions to that config.
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore


ROOT = Path(__file__).resolve().parent.parent


def _load_pyproject() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)


def test_pyproject_restricts_wheel_to_src_only():
    pyproj = _load_pyproject()
    find_cfg = (
        pyproj.get("tool", {})
        .get("setuptools", {})
        .get("packages", {})
        .get("find", {})
    )
    include = find_cfg.get("include", [])
    assert any(pat.startswith("src") for pat in include), (
        f"pyproject must restrict packages.find.include to src*, got {include}"
    )
    assert "tests" not in include and "tests*" not in include, (
        f"tests must not be in packages.find.include, got {include}"
    )


def test_setup_py_has_been_removed():
    """The legacy setup.py with bare find_packages() must be gone — we drive
    the build entirely from pyproject.toml now."""
    assert not (ROOT / "setup.py").exists(), (
        "setup.py with find_packages() reintroduces the test-bundling bug; "
        "drive packaging from pyproject.toml's [tool.setuptools.packages.find]"
    )
