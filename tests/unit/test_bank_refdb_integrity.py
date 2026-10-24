"""Final integrity checks on data/refdb/bank.json and the two specialists that
read it. Complements test_specialist_static.py / test_runner_static_baseline.py
(which use throwaway fixture data) by checking the REAL shared file as a whole:
no duplicate ids, every category accounted for by exactly one specialist, no
leftover pre-ACC00x/TX100x identifiers outside the entries that deliberately
test human-readable recipient names, and the two specialists partition the
file without gaps or overlap.
"""

import json
import re
from collections import Counter

import pytest

from redteam.attacker.injection import InjectionSpecialist
from redteam.attacker.tool_hijack import ToolHijackSpecialist

# Tokens the ACC00x/TX100x rewrite was supposed to eliminate everywhere except
# the entries that deliberately test near-miss human-readable recipient names
# (recipient_manipulation), where a "real-looking" id is the point.
_OLD_STYLE_ID_RE = re.compile(r"\b(acc_[a-z0-9_]+|ext_[a-z0-9_]+|tx_[0-9]+)\b", re.IGNORECASE)


def _load_raw() -> list[dict]:
    with InjectionSpecialist.refdb_path.open(encoding="utf-8") as f:
        return json.load(f)


def test_refdb_file_is_valid_json_and_nonempty() -> None:
    assert len(_load_raw()) > 0


def test_refdb_entries_have_no_duplicate_ids() -> None:
    ids = [e["id"] for e in _load_raw()]
    dupes = [item for item, count in Counter(ids).items() if count > 1]
    assert dupes == []


def test_refdb_entries_all_have_a_nonempty_payload() -> None:
    assert all(e.get("payload", "").strip() for e in _load_raw())


def test_every_category_belongs_to_exactly_one_of_the_two_specialists() -> None:
    categories = {e["category"] for e in _load_raw()}
    a2 = set(InjectionSpecialist.categories)
    a3 = set(ToolHijackSpecialist.categories)
    assert a2.isdisjoint(a3), "a category claimed by both specialists would double-count attempts"
    assert categories <= (a2 | a3), f"categories with no owning specialist: {categories - (a2 | a3)}"


def test_the_two_specialists_partition_the_file_with_no_overlap_or_gap() -> None:
    raw = _load_raw()
    a2_ids = {e["id"] for e in raw if e["category"] in InjectionSpecialist.categories}
    a3_ids = {e["id"] for e in raw if e["category"] in ToolHijackSpecialist.categories}
    assert a2_ids.isdisjoint(a3_ids)
    assert a2_ids | a3_ids == {e["id"] for e in raw}
    assert len(InjectionSpecialist.load_static()) == len(a2_ids)
    assert len(ToolHijackSpecialist.load_static()) == len(a3_ids)


def test_no_leftover_old_style_identifiers_outside_recipient_manipulation() -> None:
    offenders = [
        (e["id"], m.group(0))
        for e in _load_raw()
        if "recipient_manipulation" not in e.get("tags", [])
        for m in _OLD_STYLE_ID_RE.finditer(e["payload"])
    ]
    assert offenders == [], f"old-style identifiers survived the ACC00x/TX100x rewrite: {offenders}"


def test_recipient_manipulation_entries_were_left_untouched_on_purpose() -> None:
    recipient_entries = [e for e in _load_raw() if "recipient_manipulation" in e.get("tags", [])]
    assert recipient_entries, "expected at least one recipient_manipulation entry"
    # Their whole point is human-readable near-misses (names/IBANs), not ACC00x codes.
    assert all(not re.search(r"\bACC\d{3}\b", e["payload"]) for e in recipient_entries)


@pytest.mark.parametrize("specialist", [InjectionSpecialist, ToolHijackSpecialist])
def test_frozen_list_sha256_is_stable_across_repeated_calls(specialist) -> None:
    assert specialist.frozen_list_sha256() == specialist.frozen_list_sha256()


@pytest.mark.parametrize("specialist", [InjectionSpecialist, ToolHijackSpecialist])
def test_load_static_attempt_ids_are_unique(specialist) -> None:
    attempts = specialist.load_static()
    ids = [a.attempt_id for a in attempts]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("specialist", [InjectionSpecialist, ToolHijackSpecialist])
def test_load_static_every_attempt_tags_itself_with_the_right_specialist(specialist) -> None:
    assert all(a.specialist == specialist.name for a in specialist.load_static())
