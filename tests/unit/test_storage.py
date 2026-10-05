from pathlib import Path

import pytest
from pydantic import ValidationError

from redteam.shared.schemas import (
    AttemptRecord,
    Condition,
    Environment,
    RunManifest,
    Speaker,
    Trial,
    Turn,
)
from redteam.shared.storage import (
    append_jsonl,
    read_jsonl,
    read_manifest,
    run_dir,
    write_manifest,
)


def _trial(n: int = 0, payload: str = "hi") -> Trial:
    attempt = AttemptRecord(
        specialist="injection",
        attack_category="prompt_injection",
        payload=payload,
        round=n,
    )
    return Trial(
        run_id="r1",
        environment=Environment.CLOSED,
        target_profile="banking-v1",
        attempt=attempt,
        turns=(Turn(speaker=Speaker.ATTACKER, content=payload),),
    )


def _manifest() -> RunManifest:
    return RunManifest(
        environment=Environment.CLOSED,
        condition=Condition.ADAPTIVE,
        target_profile="banking-v1",
        provider="groq",
        model="openai/gpt-oss-120b",
    )


def test_run_dir_layout(tmp_path: Path) -> None:
    assert run_dir(tmp_path, "abc") == tmp_path / "runs" / "abc"


def test_append_creates_missing_folders(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "r1" / "trials.jsonl"
    append_jsonl(path, _trial())
    assert path.exists()


def test_append_then_read_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    trials = [_trial(0), _trial(1), _trial(2)]
    for t in trials:
        append_jsonl(path, t)
    assert read_jsonl(path, Trial) == trials


def test_append_never_rewrites_earlier_lines(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    append_jsonl(path, _trial(0))
    first = path.read_text(encoding="utf-8")
    append_jsonl(path, _trial(1))
    assert path.read_text(encoding="utf-8").startswith(first)


def test_one_record_per_line_even_with_newlines_in_text(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    append_jsonl(path, _trial(payload="line one\nline two"))
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    assert read_jsonl(path, Trial)[0].attempt.payload == "line one\nline two"


def test_blank_lines_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    append_jsonl(path, _trial())
    with path.open("a", encoding="utf-8") as f:
        f.write("\n\n")
    assert len(read_jsonl(path, Trial)) == 1


def test_corrupted_line_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    append_jsonl(path, _trial())
    with path.open("a", encoding="utf-8") as f:
        f.write('{"not": "a trial"}\n')
    with pytest.raises(ValidationError):
        read_jsonl(path, Trial)


def test_manifest_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    m = _manifest()
    write_manifest(path, m)
    assert read_manifest(path) == m


def test_manifest_rewrite_replaces_and_leaves_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    m = _manifest()
    write_manifest(path, m)
    done = m.model_copy(update={"total_cost_usd": 0.04})
    write_manifest(path, done)
    assert read_manifest(path).total_cost_usd == 0.04
    assert not (tmp_path / "manifest.json.tmp").exists()
