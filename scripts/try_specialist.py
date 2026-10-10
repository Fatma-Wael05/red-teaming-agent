"""Generate attacks with a specialist and run them against the offline fake target.

Uses the real attacker model (a few hundred tokens of free quota per call) but never the
real target. Attempts are saved to data/attempts/<specialist>.jsonl.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redteam.attacker.injection import InjectionSpecialist  # noqa: E402
from redteam.attacker.specialist import Specialist  # noqa: E402
from redteam.attacker.tool_hijack import ToolHijackSpecialist  # noqa: E402
from redteam.loop.runner import run_round  # noqa: E402
from redteam.shared.llm import LLMClient  # noqa: E402
from redteam.shared.schemas import Environment  # noqa: E402
from redteam.shared.settings import get_settings  # noqa: E402
from redteam.shared.storage import append_jsonl  # noqa: E402
from tests.fakes import FakeJudge, FakeTarget  # noqa: E402

SPECIALISTS: dict[str, type[Specialist]] = {
    "injection": InjectionSpecialist,
    "tool_hijack": ToolHijackSpecialist,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--specialist", choices=sorted(SPECIALISTS), required=True)
    parser.add_argument("--n", type=int, default=5)
    args = parser.parse_args()

    llm = LLMClient(get_settings(), Path("data/smoke/specialist_llm_calls.jsonl"))
    specialist = SPECIALISTS[args.specialist](llm)
    attempts = specialist.generate(args.n, round_num=0)
    print(f"{len(attempts)} valid attempts out of {args.n} requested")

    out = Path("data/attempts") / f"{specialist.name}.jsonl"
    target, judge = FakeTarget(), FakeJudge()
    for attempt in attempts:
        append_jsonl(out, attempt)
        run_round(
            attempt,
            target=target,
            judge=judge,
            run_id="offline",
            environment=Environment.CLOSED,
            target_profile="fake",
            trials_path=Path("data/smoke/offline_trials.jsonl"),
        )
        print(f"- [{attempt.attack_category}] {list(attempt.technique_tags)}: {attempt.payload}")
    print(f"saved attempts to {out}")


if __name__ == "__main__":
    main()
