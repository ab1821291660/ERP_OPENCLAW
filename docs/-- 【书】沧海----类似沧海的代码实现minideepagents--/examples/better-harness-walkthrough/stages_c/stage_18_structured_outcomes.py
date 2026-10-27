"""Stage 18 — Structured Outcomes.

Parse pytest's JUnit XML (``--junitxml=...``) into typed ``CaseOutcome``
objects with status, score, duration, and failure messages.  Walk run
logs for LangSmith trace URLs and UUIDs and emit them as ``TraceRef``s.

Together this turns "the runner produced some text" into "the runner
produced data the harness can reason about".

Run::

    uv run python stages_c/stage_18_structured_outcomes.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# ── Typed outcomes ────────────────────────────────────────────────────────

OutcomeStatus = Literal["passed", "failed", "skipped", "missing"]


@dataclass(frozen=True)
class CaseOutcome:
    """One parsed pytest test result."""

    case_id: str
    status: OutcomeStatus
    score: float
    duration_s: float
    failure_message: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == "passed"


@dataclass(frozen=True)
class TraceRef:
    """A reference to a remote trace (e.g., LangSmith)."""

    url: str | None
    trace_uuid: str | None


# ── JUnit XML parser ──────────────────────────────────────────────────────


def parse_pytest_outcomes(
    xml_path: Path, expected_case_ids: list[str]
) -> list[CaseOutcome]:
    """Parse JUnit XML into ``CaseOutcome``s, one per expected id.

    Cases that pytest didn't report on come back as ``status="missing"``
    so the harness loop can distinguish "case skipped" from "case never
    ran" — a subtle but important difference for accept/discard logic.
    """
    root = ET.fromstring(xml_path.read_text())
    found: dict[str, CaseOutcome] = {}
    for testcase in root.iter("testcase"):
        case_id = _rebuild_case_id(
            file_attr=testcase.attrib.get("file", ""),
            classname_attr=testcase.attrib.get("classname", ""),
            name_attr=testcase.attrib.get("name", ""),
        )
        status: OutcomeStatus = "passed"
        message: str | None = None
        failure = testcase.find("failure")
        if failure is None:
            failure = testcase.find("error")
        if failure is not None:
            status = "failed"
            message = failure.text or failure.attrib.get("message")
        elif testcase.find("skipped") is not None:
            status = "skipped"
        found[case_id] = CaseOutcome(
            case_id=case_id,
            status=status,
            score=1.0 if status == "passed" else 0.0,
            duration_s=float(testcase.attrib.get("time", "0") or "0"),
            failure_message=message,
        )

    return [
        found.get(
            case_id,
            CaseOutcome(
                case_id=case_id,
                status="missing",
                score=0.0,
                duration_s=0.0,
                failure_message="case missing from junit.xml",
            ),
        )
        for case_id in expected_case_ids
    ]


def _rebuild_case_id(
    *, file_attr: str, classname_attr: str, name_attr: str
) -> str:
    """Best-effort reconstruction of a pytest nodeid from JUnit fields.

    Pytest doesn't put a clean nodeid in JUnit XML.  We assemble one from
    the ``file`` attribute when present (it is for ``junit_family =
    xunit2``); otherwise fall back to ``<classname>::<name>``, the
    canonical short form for the default JUnit dialect.
    """
    if file_attr:
        return f"{file_attr}::{name_attr}"
    if classname_attr:
        return f"{classname_attr}::{name_attr}"
    return name_attr


# ── Trace ref extraction ──────────────────────────────────────────────────

_LANGSMITH_URL = re.compile(r"https?://(?:smith|cloud)\.langchain\.com/[^\s\"'\)]+")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def extract_trace_refs(text: str) -> list[TraceRef]:
    """Pull LangSmith URLs (and orphan UUIDs) out of arbitrary log text.

    URLs come first; bare UUIDs not embedded inside any URL we already
    captured come second.  Order is preserved, duplicates are removed.
    """
    refs: list[TraceRef] = []
    seen_urls: set[str] = set()
    for match in _LANGSMITH_URL.finditer(text):
        url = match.group(0)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        uuid_match = _UUID.search(url)
        refs.append(TraceRef(url=url, trace_uuid=uuid_match.group(0) if uuid_match else None))

    captured_uuids = {ref.trace_uuid for ref in refs if ref.trace_uuid}
    captured_urls = [ref.url for ref in refs if ref.url]
    for match in _UUID.finditer(text):
        uuid = match.group(0)
        if uuid in captured_uuids:
            continue
        if any(uuid in url for url in captured_urls):
            continue
        captured_uuids.add(uuid)
        refs.append(TraceRef(url=None, trace_uuid=uuid))
    return refs


# ── Demo ──────────────────────────────────────────────────────────────────

TEST_SOURCE = """\
import pytest


def test_passes():
    assert 2 + 2 == 4


def test_fails():
    assert 2 + 2 == 5, "math is broken"


@pytest.mark.skip(reason="not yet implemented")
def test_skipped():
    pass
"""

SAMPLE_LOG = """\
INFO LangSmith trace: https://smith.langchain.com/o/abc/projects/p/test/r/12345678-1234-5678-1234-567812345678/r
DEBUG run_id=87654321-4321-8765-4321-876587654321 finished
INFO duplicate trace https://smith.langchain.com/o/abc/projects/p/test/r/12345678-1234-5678-1234-567812345678/r ignored
"""


def _run_pytest_to_junit(test_path: Path, junit_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--rootdir",
            str(test_path.parent),
            f"--junitxml={junit_path}",
            str(test_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> None:
    print("Stage 18 — Structured Outcomes\n")

    with tempfile.TemporaryDirectory(prefix="bh_stage18_") as tmpdir:
        tmp = Path(tmpdir)
        test_path = tmp / "test_demo.py"
        test_path.write_text(TEST_SOURCE)
        junit_path = tmp / "junit.xml"

        completed = _run_pytest_to_junit(test_path, junit_path)
        print(f"pytest returncode = {completed.returncode}")
        print(f"junit.xml exists  = {junit_path.exists()}\n")

        # Pytest's default JUnit dialect emits ``classname="<module>"``
        # without a ``file`` attribute.  Our test file is ``test_demo.py``,
        # so the classname is ``test_demo``.  ``test_missing`` is in the
        # expected list but never defined — the parser must surface that
        # as ``status="missing"`` rather than silently dropping it.
        expected_ids = [
            "test_demo::test_passes",
            "test_demo::test_fails",
            "test_demo::test_skipped",
            "test_demo::test_missing",  # demonstrates the "missing" branch
        ]
        outcomes = parse_pytest_outcomes(junit_path, expected_ids)
        print("Parsed outcomes:")
        for outcome in outcomes:
            short = outcome.case_id.rsplit("::", maxsplit=1)[-1]
            print(
                f"  • {short:14s} {outcome.status:8s} "
                f"score={outcome.score} t={outcome.duration_s:.3f}s"
            )
            if outcome.failure_message:
                first_line = outcome.failure_message.splitlines()[0]
                print(f"      ↳ {first_line}")

        print("\nTrace refs from sample log:")
        refs = extract_trace_refs(SAMPLE_LOG)
        for ref in refs:
            print(f"  • url={ref.url}\n    uuid={ref.trace_uuid}")

    print("\n" + "=" * 60)
    print("JUnit XML + log scrape → typed Python the harness can reason")
    print("about: per-case status, score, timing, and trace-link indexing.")


if __name__ == "__main__":
    main()
