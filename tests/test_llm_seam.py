"""The one place a model reply becomes text, and text becomes a shape.

Both idioms used to live at the call sites: the reply-flattener seven times
(six inline copies that raised TypeError on content that was neither str nor
list, plus one good version), and the JSON parser as a PRIVATE name in the
research module imported by four siblings - one of them through a
function-local import that existed purely to break a cycle.
"""

from __future__ import annotations

from typing import Any

from trdrbot import llm


class _Reply:
    """Shaped like a LangChain message: the only attribute `text_of` reads."""

    def __init__(self, content: Any) -> None:
        self.content = content


def test_text_of_handles_a_plain_string():
    assert llm.text_of(_Reply("hello")) == "hello"


def test_text_of_keeps_only_the_text_blocks_of_a_thinking_reply():
    """Extended-thinking replies return a `thinking` block carrying an opaque
    signature blob before the actual text. Stringifying the whole list dumped
    that blob into the journal and the console, burying the reasoning in
    base64 and spending the 2000-char summary budget on it."""
    reply = _Reply([
        {"type": "thinking", "thinking": "...", "signature": "AAAAB3NzaC1yc2E="},
        {"type": "text", "text": "the answer"},
    ])

    assert llm.text_of(reply) == "the answer"


def test_text_of_falls_back_instead_of_raising_on_an_unexpected_shape():
    """The six inline copies had no such fallback: content that was neither a
    str nor a list raised TypeError inside whichever subsystem happened to
    receive it. Only the tick's copy - the one that survived - handled it."""
    assert llm.text_of(_Reply(None)) == "None"
    assert llm.text_of(_Reply(42)) == "42"
    assert llm.text_of(object()) == ""


# ------------------------------------------------------------ shape parsing


def test_parse_json_array_unwraps_a_single_keyed_object():
    """The muse's old hand-rolled fixup, now the parser's stated contract.
    Models wrap arrays in a container unprompted; the salvage path resolves
    `{}` before `[]`, so the wrapped form arrived as a dict, the caller's
    list-guard skipped everything, and the run reported "0 candidates" with no
    evidence of why."""
    assert llm.parse_json_array('{"candidates": [{"underlying": "X"}]}') == [
        {"underlying": "X"}
    ]


def test_parse_json_array_will_not_guess_between_two_lists():
    """Two list values means the container is not a wrapper, and picking one
    would be the parser inventing an answer."""
    assert llm.parse_json_array('{"a": [1], "b": [2]}') == []


def test_each_parser_returns_the_empty_shape_its_caller_asked_for():
    """Nothing usable is `[]` for an array and `{}` for an object, never None.
    Every caller was writing `... or []` after the old shared function, and
    the two that forgot re-guessed the shape instead."""
    for junk in ("not json at all", "[", "", "```json\n```"):
        assert llm.parse_json_array(junk) == []
        assert llm.parse_json_object(junk) == {}


def test_a_truncated_array_still_yields_its_complete_elements():
    """Moved with the parser, because the incident is the reason it exists: a
    6,745-char muse reply opened with a perfectly good array and parsed to
    nothing, one LLM call spent for zero candidates (I-19)."""
    truncated = ('[{"underlying":"S","chain":["a","b"]},'
                 '{"underlying":"MU","chain":["c"]},'
                 '{"underlying":"BURL","cha')

    got = llm.parse_json_array(truncated)

    assert [g["underlying"] for g in got] == ["S", "MU"]


def test_section_reads_one_labelled_block():
    """One parser for one LABEL: convention. Discovery had its own inline
    regexes for the same convention, and they hard-required the terminating
    label - a reply that omitted it lost the whole first section silently."""
    text = "FORECASTS_JSON:\n{\"a\": 1}\nOPPORTUNITIES_JSON:\n[]\n"

    assert llm.section(text, "FORECASTS_JSON", ["OPPORTUNITIES_JSON"]) == '{"a": 1}'
    assert llm.section(text, "OPPORTUNITIES_JSON", ["\\Z"]) == "[]"
    assert llm.section(text, "ABSENT_LABEL", ["\\Z"]) == ""


def test_a_missing_terminator_still_yields_the_section():
    """The failure mode of discovery's old inline form."""
    assert llm.section("FORECASTS_JSON:\n{\"a\": 1}\n",
                       "FORECASTS_JSON", ["OPPORTUNITIES_JSON"]) == '{"a": 1}'


# -------------------------------------------------------- role and identity


def test_every_role_the_code_requests_is_declared():
    """`doctor` hardcoded five roles under a comment claiming it probed EVERY
    model in every configured chain; coach_mutate and news_extract were
    covered only incidentally by other chains. ROLES is now the one place a
    role is declared, so the two cannot drift."""
    import pathlib
    import re

    src = pathlib.Path(llm.__file__).parent
    requested = set()
    for path in src.glob("*.py"):
        requested |= set(re.findall(r'role=["\'](\w+)["\']', path.read_text()))

    assert requested <= set(llm.ROLES), f"undeclared role(s): {requested - set(llm.ROLES)}"


def test_the_coach_and_the_prompt_inventory_share_one_fingerprint():
    """Lever state files on disk carry this hash. A second scheme is how two
    identities for one artefact begin."""
    from trdrbot import coach, prompts

    assert coach.fingerprint("some prompt") == prompts.fingerprint("some prompt")


def test_the_inventory_covers_every_authored_prompt():
    """Its own module docstring said eight artefacts; it listed six, omitting
    the mutation prompt and the extraction prompt. A provenance record that
    silently misses an artefact is worse than one that admits the gap."""
    from trdrbot import prompts

    names = {r.name for r in prompts.inventory()}

    assert {"coach.mutate", "news.extract"} <= names
    assert len(names) >= 8
