import hashlib
import json
from pathlib import Path

import pytest

from redteam.attacker.injection import InjectionSpecialist
from redteam.attacker.specialist import Specialist
from redteam.attacker.tool_hijack import ToolHijackSpecialist


class _FixtureSpecialist(Specialist):
    """A throwaway Specialist subclass, so these tests don't depend on the
    real refdb file's content (which will keep growing/changing) or touch
    InjectionSpecialist/ToolHijackSpecialist's own refdb_path."""

    name = "fixture"
    categories = ("cat_a", "cat_b")


def _write_refdb(path: Path, items: list[dict]) -> None:
    path.write_text(json.dumps(items), encoding="utf-8")


def test_load_static_filters_by_category(tmp_path: Path) -> None:
    path = tmp_path / "refdb.json"
    _write_refdb(
        path,
        [
            {"category": "cat_a", "payload": "a", "technique_tags": ["x"]},
            {"category": "cat_b", "payload": "b", "tags": ["y"]},
            {"category": "other_specialists_category", "payload": "skip-me"},
        ],
    )
    _FixtureSpecialist.refdb_path = path
    attempts = _FixtureSpecialist.load_static()
    assert [a.payload for a in attempts] == ["a", "b"]
    assert {a.attack_category for a in attempts} == {"cat_a", "cat_b"}
    assert all(a.specialist == "fixture" for a in attempts)


def test_load_static_accepts_technique_tags_tags_or_strategy(tmp_path: Path) -> None:
    path = tmp_path / "refdb.json"
    _write_refdb(
        path,
        [
            {"category": "cat_a", "payload": "a", "technique_tags": ["from_technique_tags"]},
            {"category": "cat_a", "payload": "b", "tags": ["from_tags"]},
            {"category": "cat_a", "payload": "c", "strategy": "from_strategy"},
            {"category": "cat_a", "payload": "d"},
        ],
    )
    _FixtureSpecialist.refdb_path = path
    tags = {a.payload: a.technique_tags for a in _FixtureSpecialist.load_static()}
    assert tags["a"] == ("from_technique_tags",)
    assert tags["b"] == ("from_tags",)
    assert tags["c"] == ("from_strategy",)
    assert tags["d"] == ()


def test_frozen_list_sha256_matches_the_exact_file_bytes(tmp_path: Path) -> None:
    path = tmp_path / "refdb.json"
    _write_refdb(path, [{"category": "cat_a", "payload": "a"}])
    _FixtureSpecialist.refdb_path = path
    assert _FixtureSpecialist.frozen_list_sha256() == hashlib.sha256(path.read_bytes()).hexdigest()


def test_load_static_with_hash_agrees_with_the_two_separate_calls(tmp_path: Path) -> None:
    path = tmp_path / "refdb.json"
    _write_refdb(path, [{"category": "cat_a", "payload": "a"}])
    _FixtureSpecialist.refdb_path = path
    attempts, digest = _FixtureSpecialist.load_static_with_hash()
    assert [a.payload for a in attempts] == ["a"]
    assert digest == _FixtureSpecialist.frozen_list_sha256()


def test_load_static_without_refdb_path_raises() -> None:
    class _NoPath(Specialist):
        name = "no-path"
        categories = ("cat_a",)

    with pytest.raises(ValueError, match="no refdb_path"):
        _NoPath.load_static()


# ---------------------------------------------------------------- smoke tests
# These do touch the real InjectionSpecialist/ToolHijackSpecialist and the real
# data/refdb/bank.json, to guard against a future refdb edit accidentally
# dropping a category or un-sharing the file between the two specialists.


def test_injection_and_tool_hijack_specialists_share_one_refdb_file() -> None:
    assert InjectionSpecialist.refdb_path == ToolHijackSpecialist.refdb_path
    assert InjectionSpecialist.frozen_list_sha256() == ToolHijackSpecialist.frozen_list_sha256()


def test_injection_specialist_only_loads_its_own_categories() -> None:
    attempts = InjectionSpecialist.load_static()
    assert attempts
    assert {a.attack_category for a in attempts} <= set(InjectionSpecialist.categories)


def test_tool_hijack_specialist_only_loads_its_own_categories() -> None:
    attempts = ToolHijackSpecialist.load_static()
    assert attempts
    assert {a.attack_category for a in attempts} <= set(ToolHijackSpecialist.categories)
