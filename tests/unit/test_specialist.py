import json
from types import SimpleNamespace
from typing import Any

import pytest

from redteam.attacker.injection import InjectionSpecialist
from redteam.attacker.specialist import Specialist, extract_json_list
from redteam.attacker.tool_hijack import ToolHijackSpecialist


class _FakeLLM:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        role: str,
        messages: list[dict[str, Any]],
        *,
        caller: str | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        self.calls.append({"role": role, "messages": messages, "caller": caller})
        return SimpleNamespace(text=self.replies.pop(0))


def _attack(
    payload: str = "p1",
    category: str = "prompt_injection",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    return {"category": category, "technique_tags": tags or ["pretext"], "payload": payload}


def _reply(*items: Any) -> str:
    return json.dumps(list(items))


def test_generate_returns_validated_attempts() -> None:
    llm = _FakeLLM([_reply(_attack("a"), _attack("b"))])
    attempts = InjectionSpecialist(llm).generate(2, round_num=3)
    assert [a.payload for a in attempts] == ["a", "b"]
    assert {a.specialist for a in attempts} == {"injection"}
    assert {a.round for a in attempts} == {3}
    assert attempts[0].technique_tags == ("pretext",)
    assert attempts[0].attempt_id != attempts[1].attempt_id


def test_fenced_json_is_accepted() -> None:
    llm = _FakeLLM(["Sure!\n```json\n" + _reply(_attack("a")) + "\n```"])
    assert len(InjectionSpecialist(llm).generate(1)) == 1


def test_json_inside_prose_is_accepted() -> None:
    llm = _FakeLLM(["Here you go: " + _reply(_attack("a")) + " Hope that helps."])
    assert len(InjectionSpecialist(llm).generate(1)) == 1


def test_invalid_items_are_skipped() -> None:
    items = [
        _attack("good"),
        _attack("bad category", category="hacking"),
        _attack(""),
        "not a dict",
        {"category": "prompt_injection"},
    ]
    attempts = InjectionSpecialist(_FakeLLM([_reply(*items)]), max_calls=1).generate(5)
    assert [a.payload for a in attempts] == ["good"]


def test_duplicates_are_skipped() -> None:
    reply = _reply(_attack("Hello"), _attack("x"), _attack("X "))
    llm = _FakeLLM([reply])
    attempts = InjectionSpecialist(llm, max_calls=1).generate(5, avoid=["hello"])
    assert [a.payload for a in attempts] == ["x"]


def test_missing_attacks_are_requested_again() -> None:
    llm = _FakeLLM([_reply(_attack("a")), _reply(_attack("b"))])
    attempts = InjectionSpecialist(llm).generate(2)
    assert [a.payload for a in attempts] == ["a", "b"]
    assert len(llm.calls) == 2
    second_prompt = llm.calls[1]["messages"][1]["content"]
    assert "Write 1 different attacks" in second_prompt
    assert "- a" in second_prompt


def test_gives_up_after_max_calls() -> None:
    llm = _FakeLLM(["garbage", "garbage"])
    assert InjectionSpecialist(llm, max_calls=2).generate(3) == []
    assert len(llm.calls) == 2


def test_calls_use_the_attacker_role_and_the_specialist_name() -> None:
    inj = _FakeLLM([_reply(_attack("a"))])
    InjectionSpecialist(inj).generate(1)
    assert inj.calls[0]["role"] == "attacker"
    assert inj.calls[0]["caller"] == "specialist:injection"

    tool = _FakeLLM([_reply(_attack("a", category="tool_hijack"))])
    ToolHijackSpecialist(tool).generate(1)
    assert tool.calls[0]["caller"] == "specialist:tool_hijack"


def test_learnings_and_avoid_reach_the_prompt() -> None:
    llm = _FakeLLM([_reply(_attack("a"))])
    InjectionSpecialist(llm).generate(1, learnings="LEARN-XYZ", avoid=["AVOID-ME"])
    prompt = llm.calls[0]["messages"][1]["content"]
    assert "LEARN-XYZ" in prompt
    assert "AVOID-ME" in prompt


def test_extract_json_list_edge_cases() -> None:
    assert extract_json_list('{"attacks": [{"payload": "x"}]}') == [{"payload": "x"}]
    assert extract_json_list('{"payload": "x"}') == [{"payload": "x"}]
    assert extract_json_list("no json here") == []


@pytest.mark.parametrize("specialist", [InjectionSpecialist, ToolHijackSpecialist])
def test_prompts_never_contain_the_canary(specialist: type[Specialist]) -> None:
    shots = json.dumps([shot.model_dump() for shot in specialist.few_shots])
    assert "OPSCODE" not in (specialist.system_prompt + shots).upper()


@pytest.mark.parametrize("specialist", [InjectionSpecialist, ToolHijackSpecialist])
def test_few_shots_use_allowed_categories(specialist: type[Specialist]) -> None:
    assert all(shot.category in specialist.categories for shot in specialist.few_shots)


def test_tool_hijack_prompt_covers_the_boundary_values() -> None:
    assert "500.01" in ToolHijackSpecialist.system_prompt
    assert "501" in ToolHijackSpecialist.system_prompt
