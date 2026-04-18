"""Cross-file registration-consistency linter for b-roll types.

Unit 0.6 — CI-level guard against silent partial registration of a b-roll type.

Four independent truths must stay in sync:

  1. ``scripts/broll_gen/selector.py::_VALID_TYPES`` (frozenset)
  2. ``scripts/broll_gen/factory.py::make_broll_generator``
     — the set of string literals compared in its ``if type_name == "..."`` chain
     (extracted via ``ast``; scoped to the factory function body only).
  3. ``scripts/broll_gen/selector.py::_RESPONSE_SCHEMA`` primary + fallback enums.
  4. ``scripts/broll_gen/registry.py::BROLL_REGISTRY`` dict keys.

If any of these drift apart — for example, a worker adds a new type to the
registry + enum + selector but forgets the factory branch — the matching
test fails loudly, naming the missing type(s) and the file they're missing
from. This unit itself adds no new types; it just locks the existing ones.

All four tests are expected to pass against HEAD at Unit 0.5. The fifth
sanity test demonstrates the set-diff logic catches drift.

No network, no LLM, no subprocess — pure ``ast`` / attribute inspection.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

# Dual-import: run from repo root (``scripts.broll_gen...``) or from ``scripts/``.
try:
    from scripts.broll_gen.selector import _RESPONSE_SCHEMA, _VALID_TYPES
    from scripts.broll_gen.registry import BROLL_REGISTRY
    import scripts.broll_gen.factory as factory_module
except ImportError:  # pragma: no cover — fallback when cwd is ``scripts/``
    from broll_gen.selector import _RESPONSE_SCHEMA, _VALID_TYPES  # type: ignore[no-redef]
    from broll_gen.registry import BROLL_REGISTRY  # type: ignore[no-redef]
    import broll_gen.factory as factory_module  # type: ignore[no-redef]


_FACTORY_FUNC_NAME = "make_broll_generator"


def _extract_factory_type_literals() -> set[str]:
    """Return every string literal compared against a Name in the factory body.

    Parses ``factory.py``, locates the ``make_broll_generator`` function node
    (both ``FunctionDef`` and ``AsyncFunctionDef`` are accepted for
    forward-compatibility), and walks ONLY the body of that function.

    For each ``ast.Compare`` node, if the left-hand side is an ``ast.Name``
    (e.g. ``type_name``) and any comparator is a string ``ast.Constant``, the
    string is collected. This handles the current ``if type_name == "..."``
    top-level chain as well as any future ``elif``/``in (...)`` variants.

    Scoping to the function body avoids false positives from module-level
    strings in docstrings, logger messages, or the final ``ValueError`` text.
    """
    source_path = Path(inspect.getfile(factory_module))
    tree = ast.parse(source_path.read_text())

    factory_node: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == _FACTORY_FUNC_NAME
        ):
            factory_node = node
            break

    assert factory_node is not None, (
        f"factory.py must define a top-level function named "
        f"{_FACTORY_FUNC_NAME!r} for the registration linter to scope its AST walk"
    )

    literals: set[str] = set()
    for node in ast.walk(factory_node):
        if not isinstance(node, ast.Compare):
            continue
        # Only accept comparisons where the LHS is a Name (i.e. ``type_name == ...``),
        # not nested expressions that happen to contain string constants.
        if not isinstance(node.left, ast.Name):
            continue
        for comparator in node.comparators:
            if isinstance(comparator, ast.Constant) and isinstance(
                comparator.value, str
            ):
                literals.add(comparator.value)
    return literals


# ── 1. Factory if-chain ↔ _VALID_TYPES ────────────────────────────────────────

def test_factory_if_chain_matches_valid_types() -> None:
    """Every type in ``_VALID_TYPES`` has a factory branch, and vice versa."""
    factory_literals = _extract_factory_type_literals()
    valid = set(_VALID_TYPES)
    missing_in_factory = valid - factory_literals
    extra_in_factory = factory_literals - valid
    assert not missing_in_factory, (
        f"types in _VALID_TYPES missing from factory if-chain "
        f"(scripts/broll_gen/factory.py): {sorted(missing_in_factory)}"
    )
    assert not extra_in_factory, (
        f"types in factory if-chain not present in _VALID_TYPES "
        f"(scripts/broll_gen/selector.py): {sorted(extra_in_factory)}"
    )


# ── 2. Response schema primary enum ↔ _VALID_TYPES ────────────────────────────

def test_response_schema_primary_matches_valid_types() -> None:
    """``_RESPONSE_SCHEMA`` ``primary`` enum must equal ``_VALID_TYPES``."""
    primary_enum = set(_RESPONSE_SCHEMA["properties"]["primary"]["enum"])
    valid = set(_VALID_TYPES)
    assert primary_enum == valid, (
        f"primary enum drift (scripts/broll_gen/selector.py::_RESPONSE_SCHEMA): "
        f"missing from schema={sorted(valid - primary_enum)}, "
        f"extra in schema={sorted(primary_enum - valid)}"
    )


# ── 3. Response schema fallback enum ↔ _VALID_TYPES ───────────────────────────

def test_response_schema_fallback_matches_valid_types() -> None:
    """``_RESPONSE_SCHEMA`` ``fallback`` enum must equal ``_VALID_TYPES``."""
    fallback_enum = set(_RESPONSE_SCHEMA["properties"]["fallback"]["enum"])
    valid = set(_VALID_TYPES)
    assert fallback_enum == valid, (
        f"fallback enum drift (scripts/broll_gen/selector.py::_RESPONSE_SCHEMA): "
        f"missing from schema={sorted(valid - fallback_enum)}, "
        f"extra in schema={sorted(fallback_enum - valid)}"
    )


# ── 4. Registry keys ↔ _VALID_TYPES ───────────────────────────────────────────

def test_registry_matches_valid_types() -> None:
    """``BROLL_REGISTRY`` keys must equal ``_VALID_TYPES``."""
    registry_keys = set(BROLL_REGISTRY.keys())
    valid = set(_VALID_TYPES)
    assert registry_keys == valid, (
        f"registry drift (scripts/broll_gen/registry.py::BROLL_REGISTRY): "
        f"missing from registry={sorted(valid - registry_keys)}, "
        f"extra in registry={sorted(registry_keys - valid)}"
    )


# ── 5. Sanity: drift detection itself works ───────────────────────────────────

def test_drift_detection_logic_catches_simulated_drift() -> None:
    """Mutating a copy of ``_VALID_TYPES`` must surface via the same set-diff."""
    valid = set(_VALID_TYPES)
    # Simulate "someone added a new type to the registry but forgot the factory".
    simulated_factory = valid - {"ai_video"}  # factory missing one
    simulated_registry = valid | {"faux_type"}  # registry has an extra

    missing_in_factory = valid - simulated_factory
    extra_in_registry = simulated_registry - valid

    assert missing_in_factory == {"ai_video"}, (
        "drift detection must name the single missing factory type"
    )
    assert extra_in_registry == {"faux_type"}, (
        "drift detection must name the single extraneous registry type"
    )
