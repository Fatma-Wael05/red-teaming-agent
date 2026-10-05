"""Append-only JSONL storage for frozen records, plus run-manifest I/O."""

from pathlib import Path

from pydantic import BaseModel

from redteam.shared.schemas import RunManifest


def run_dir(data_root: Path, run_id: str) -> Path:
    """Folder holding manifest.json, trials.jsonl and llm_calls.jsonl for a run."""
    return data_root / "runs" / run_id


def append_jsonl(path: Path, record: BaseModel) -> None:
    """Append one record as a single line. Existing lines are never touched."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(record.model_dump_json() + "\n")


def read_jsonl[M: BaseModel](path: Path, model: type[M]) -> list[M]:
    """Read and validate every line. A corrupted line raises instead of being skipped."""
    with path.open(encoding="utf-8") as f:
        return [model.model_validate_json(line) for line in f if line.strip()]


def write_manifest(path: Path, manifest: RunManifest) -> None:
    """Write via a temp file, so a crash can't leave a half-written manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(manifest.model_dump_json(indent=2), encoding="utf-8", newline="\n")
    tmp.replace(path)


def read_manifest(path: Path) -> RunManifest:
    return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))
