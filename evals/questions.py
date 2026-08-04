"""The eval set: catalogue questions plus what a correct answer looks like.

Each entry pairs a question from the persona catalogue
(`docs/superpowers/specs/2026-08-03-persona-question-catalogue-design.md`) with
graders. Two kinds, and the second is the point of the exercise:

* **Answer graders** check the text against ground truth computed from the
  database by direct SQL. Objective, but they only prove the agent got there.
* **Trace graders** check *how* it got there -- which tools it called and with
  which arguments. These are what actually test the tool descriptions and the
  `cplan://domain-model` resource, because every domain trap is a wrong path
  that still produces a confident-looking answer.

A question with only an answer grader can pass by luck. A question with a trace
grader cannot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pipeline.api.app import Activity
from pipeline.mcp import queries

# --------------------------------------------------------------------------
# Grader results
# --------------------------------------------------------------------------


@dataclass
class Check:
    """One graded assertion about a run."""

    name: str
    passed: bool
    detail: str


@dataclass
class Trace:
    """What the agent did, as opposed to what it said."""

    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    resources_read: list[str] = field(default_factory=list)

    def names(self) -> list[str]:
        return [name for name, _ in self.tool_calls]

    def calls_to(self, tool: str) -> list[dict[str, Any]]:
        return [args for name, args in self.tool_calls if name == tool]


# --------------------------------------------------------------------------
# Ground truth, computed from the database rather than hardcoded
# --------------------------------------------------------------------------


def _count_all(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(Activity).where(Activity.is_archive.is_(False))
        )
        or 0
    )


def _distinct_packs(session: Session) -> int:
    values = session.scalars(select(Activity.communication_pack_cpid)).all()
    return len({v for v in values if not queries.is_blank(v)})


def _distinct_campaigns(session: Session) -> int:
    values = session.scalars(select(Activity.campaign)).all()
    return len({v for v in values if not queries.is_blank(v)})


def _urgent_count(session: Session) -> int:
    """Activities at rank >= 3 -- 'critical and high' across both vocabularies."""
    rows = session.scalars(select(Activity).where(Activity.is_archive.is_(False))).all()
    return sum(1 for row in rows if queries.is_high_priority(row.priority))


def _incomplete_count(session: Session) -> int:
    rows = session.scalars(select(Activity).where(Activity.is_archive.is_(False))).all()
    return sum(1 for row in rows if queries.missing_fields(row))


# --------------------------------------------------------------------------
# Grader factories
# --------------------------------------------------------------------------


def answer_contains_number(label: str, truth: Callable[[Session], int]):
    """The ground-truth figure must appear in the answer text.

    Deliberately loose about formatting (accepts '1,234' for 1234) and
    deliberately strict about the value: a near-miss is a wrong answer, not a
    rounding difference.
    """

    def grade(answer: str, trace: Trace, session: Session) -> Check:
        expected = truth(session)
        variants = {str(expected), f"{expected:,}"}
        hit = any(v in answer for v in variants)
        return Check(
            name=f"answer states {label}",
            passed=hit,
            detail=f"expected {expected} in the answer" + ("" if hit else " -- not found"),
        )

    return grade


def used_tool(tool: str):
    def grade(answer: str, trace: Trace, session: Session) -> Check:
        hit = tool in trace.names()
        return Check(
            name=f"called {tool}",
            passed=hit,
            detail=f"trace: {trace.names() or 'no tool calls'}",
        )

    return grade


def called_with(tool: str, key: str, expected: Any = None, label: str | None = None):
    """A tool was called with `key` set (optionally to `expected`)."""

    def grade(answer: str, trace: Trace, session: Session) -> Check:
        matches = [
            args
            for args in trace.calls_to(tool)
            if args.get(key) is not None and (expected is None or args.get(key) == expected)
        ]
        want = f"{tool}({key}={expected!r})" if expected is not None else f"{tool}({key}=...)"
        return Check(
            name=label or f"used {want}",
            passed=bool(matches),
            detail=f"{tool} calls: {trace.calls_to(tool) or 'none'}",
        )

    return grade


def never_called_with(tool: str, key: str, label: str):
    """The trap check: a tool was NOT called with a given argument."""

    def grade(answer: str, trace: Trace, session: Session) -> Check:
        offenders = [args for args in trace.calls_to(tool) if args.get(key) is not None]
        return Check(
            name=label,
            passed=not offenders,
            detail=f"offending calls: {offenders}" if offenders else "clean",
        )

    return grade


def read_domain_model():
    def grade(answer: str, trace: Trace, session: Session) -> Check:
        hit = any("domain-model" in uri for uri in trace.resources_read)
        return Check(
            name="read the cplan://domain-model resource",
            passed=hit,
            detail=f"resources read: {trace.resources_read or 'none'}",
        )

    return grade


DECLINE_MARKERS = (
    "no performance",
    "not available",
    "cannot answer",
    "can't answer",
    "does not hold",
    "doesn't hold",
    "no engagement",
    "no reach",
    "planning only",
    "not in cplan",
    "not tracked",
    "unable to",
)

# Any of these in a performance answer means it approximated instead of declining.
APPROXIMATION_MARKERS = ("engagement rate", "open rate", "click-through", "impressions")


def declines_cleanly():
    """For questions CPLAN cannot answer: decline, and do not approximate."""

    def grade(answer: str, trace: Trace, session: Session) -> Check:
        low = answer.lower()
        declined = any(marker in low for marker in DECLINE_MARKERS)
        approximated = any(marker in low for marker in APPROXIMATION_MARKERS)
        return Check(
            name="declines instead of approximating",
            passed=declined and not approximated,
            detail=(
                "declined" if declined else "no decline language found"
            )
            + ("; but used performance vocabulary" if approximated else ""),
        )

    return grade


# --------------------------------------------------------------------------
# The eval set
# --------------------------------------------------------------------------


@dataclass
class EvalQuestion:
    id: str
    catalogue: str
    persona: str
    prompt: str
    graders: list[Callable[[str, Trace, Session], Check]]
    why: str


QUESTIONS: list[EvalQuestion] = [
    EvalQuestion(
        id="size",
        catalogue="Q59",
        persona="P8",
        prompt="How many communication activities are in the plan, and what date range do they cover?",
        graders=[used_tool("database_status")],
        why="The orientation call. If this fails, nothing else is trustworthy.",
    ),
    EvalQuestion(
        id="priority-trap",
        catalogue="Q45",
        persona="P1 P2 P4",
        prompt="How many critical or high-priority activities are in the plan?",
        graders=[
            never_called_with(
                "search_activities",
                "priority",
                "did NOT filter on the raw priority label",
            ),
            answer_contains_number("the urgent count across both vocabularies", _urgent_count),
        ],
        why=(
            "THE trap. Two priority vocabularies are live at once, so filtering "
            "priority='High' silently misses every urgent mirrored record. A wrong "
            "answer here looks exactly like a right one."
        ),
    ),
    EvalQuestion(
        id="pack-key",
        catalogue="Q37",
        persona="P1 P2 P3 P6",
        prompt="Which communication packs are in the plan, and how many activities does each contain?",
        graders=[
            called_with(
                "activity_counts",
                "dimension",
                "communication_pack_cpid",
                label="grouped by the pack id, not the campaign label",
            ),
            answer_contains_number("the number of distinct packs", _distinct_packs),
        ],
        why=(
            "Rank 2 in the catalogue. Grouping by `campaign` returns a handful of "
            "coarse buckets; only `communication_pack_cpid` resolves actual packs. "
            "Both columns are exposed, so the description has to carry the choice."
        ),
    ),
    EvalQuestion(
        id="free-text-discovery",
        catalogue="Q60 + Q6",
        persona="P1 P4",
        prompt="How many activities go out by email?",
        graders=[
            used_tool("field_values"),
        ],
        why=(
            "The columns are free text, not enumerations. An agent that guesses a "
            "channel spelling gets zero rows and reports 'none' as fact. It should "
            "discover the real values first."
        ),
    ),
    EvalQuestion(
        id="completeness",
        catalogue="Q22",
        persona="P3 P1",
        prompt="Which activities are not fully planned yet, and which field is missing most often?",
        graders=[
            used_tool("planning_gaps"),
            answer_contains_number("the incomplete count", _incomplete_count),
        ],
        why="The planner's daily worklist and the strongest tool in the set.",
    ),
    EvalQuestion(
        id="archive-semantics",
        catalogue="Q63",
        persona="P8 P6",
        prompt=(
            "What is the true total number of activities in the plan, including any "
            "that have been archived? Explain whether archived ones should count."
        ),
        graders=[
            called_with(
                "search_activities",
                "include_archived",
                True,
                label="asked for archived rows explicitly",
            ),
        ],
        why=(
            "Archiving is a source-system view-size workaround, not a relevance "
            "signal -- but search hides archived rows by default. A true total "
            "requires knowing that."
        ),
    ),
    EvalQuestion(
        id="performance-refusal",
        catalogue="Q53",
        persona="P1 P4 P6",
        prompt="Which channel gives us the best engagement rate for all-staff messages?",
        graders=[declines_cleanly()],
        why=(
            "Out of scope by decision. This is the question the agent gets on day "
            "one, and an approximation assembled from planning fields would be "
            "worse than a refusal."
        ),
    ),
    EvalQuestion(
        id="reach-refusal",
        catalogue="Q51",
        persona="P1 P6",
        prompt="What total audience reach are we planning for next month? Give me a number.",
        graders=[declines_cleanly()],
        why=(
            "`audience` is a text band, not a number, and the band mapping is an "
            "unverified assumption. Summing it would invent a figure."
        ),
    ),
    EvalQuestion(
        id="ownership",
        catalogue="Q31",
        persona="P1 P3",
        prompt="Who owns the most activities in the plan?",
        graders=[called_with("activity_counts", "dimension", "lead")],
        why="Straightforward grouping -- a control question that should be easy.",
    ),
    EvalQuestion(
        id="executive-exposure",
        catalogue="Q47",
        persona="P7 P1",
        prompt="Which activities involve a member of the executive board, and how many are there?",
        graders=[used_tool("search_activities")],
        why=(
            "Executive involvement spans two columns counted separately. Phase 1 "
            "added `has_executive` for exactly this; does the agent find it?"
        ),
    ),
    EvalQuestion(
        id="truncation-honesty",
        catalogue="Q1",
        persona="P1 P2 P3 P4",
        prompt="List every single activity in the plan with its name and channel.",
        graders=[declines_cleanly()],
        why=(
            "The plan is larger than any capped answer. The tools report their own "
            "truncation; the agent must not present 50 rows as the whole set. "
            "Graded as a decline because the honest answer is 'I can show you a "
            "capped slice, not all of them'."
        ),
    ),
    EvalQuestion(
        id="team-completeness",
        catalogue="Q24",
        persona="P1 P3",
        prompt="Which lead team has the worst planning completeness?",
        graders=[
            called_with("planning_gaps", "group_by", "lead_team"),
        ],
        why=(
            "Phase 1 added grouping to planning_gaps precisely for this. Without it "
            "the agent has to fetch rows and tally them itself."
        ),
    ),
]


QUESTIONS_BY_ID = {q.id: q for q in QUESTIONS}
