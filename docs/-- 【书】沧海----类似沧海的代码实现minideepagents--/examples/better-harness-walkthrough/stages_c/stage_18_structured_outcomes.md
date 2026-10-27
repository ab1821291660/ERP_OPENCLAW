# Stage 18 — Structured Outcomes

## 1. Goal

Replace stdout-scraping with a stable, machine-readable outcome
pipeline: parse pytest's JUnit XML into typed `CaseOutcome` objects and
extract LangSmith trace URLs/UUIDs from any log text into `TraceRef`s.

## 2. What changed from previous stage

- New `CaseOutcome` dataclass with `status` (`passed` / `failed` /
  `skipped` / `missing`), `score`, `duration_s`, and an optional
  `failure_message`.
- New `TraceRef` dataclass holding a `url` and/or a `trace_uuid`.
- New `parse_pytest_outcomes(xml_path, expected_case_ids)` — parses
  JUnit XML and emits one `CaseOutcome` per expected case id, marking
  cases pytest never reported on as `missing`.
- New `extract_trace_refs(text)` — regex-walks arbitrary text for
  LangSmith URLs and orphan UUIDs, deduplicates, and returns them in
  document order.
- Demo runs a real pytest invocation against a tiny test file
  containing a passing, a failing, and a skipped case, then parses
  the resulting JUnit XML.

## 3. Run it

```bash
uv run python stages_c/stage_18_structured_outcomes.py
```

## 4. Walkthrough

JUnit parsing follows the shape of pytest's XML output:

```python
def parse_pytest_outcomes(xml_path, expected_case_ids):
    root = ET.fromstring(xml_path.read_text())
    found = {}
    for testcase in root.iter("testcase"):
        case_id = _rebuild_case_id(...)
        if testcase.find("failure") is not None: status = "failed"
        elif testcase.find("skipped") is not None: status = "skipped"
        else: status = "passed"
        found[case_id] = CaseOutcome(case_id, status, ..., duration, msg)
    return [found.get(case_id, CaseOutcome(case_id, status="missing", ...))
            for case_id in expected_case_ids]
```

Trace extraction uses two narrow regexes:

```python
_LANGSMITH_URL = re.compile(r"https?://(?:smith|cloud)\.langchain\.com/[^\s\"')]+")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-...")

def extract_trace_refs(text):
    refs = []
    for match in _LANGSMITH_URL.finditer(text):
        refs.append(TraceRef(url=match.group(0), trace_uuid=...))
    # then any UUIDs not already inside one of those URLs:
    for match in _UUID.finditer(text):
        ...
```

The `expected_case_ids` argument is what makes "missing" a real
status: the parser knows what should have run, so it can flag what
didn't.

## 5. Why this abstraction matters

If the harness reads pass/fail by grepping `-q` stdout (`"1 passed"`),
any change to pytest's text output silently breaks scoring.  JUnit
XML is a stable contract pytest has shipped for years.  Likewise,
trace links surfaced as plain text in logs are easy to lose; pulling
them into a `TraceRef` list and saving as `traces.json` makes them
addressable from a UI or a script.

## 6. Tradeoffs vs simpler approach

You could shell out to pytest with `-q` and parse the summary line.
Works for one test.  Falls down on partial collection (collection
errors, fixture errors, plugin errors) where the summary line lies or
is absent.  JUnit XML covers all of those.

## 7. LangChain mapping

None.  Trace URLs *come from* LangChain/LangSmith but the parsing is
plain `re` + `xml.etree`.

## 8. LangGraph mapping

None.

## 9. Aha insight

Machine-readable output is what makes a runner *programmable* rather
than *scriptable*.  Once outcomes are typed, every downstream layer
(reporter, scorer, accept/discard rule) gets to write against a
schema instead of a substring.

## 10. Common mistake

Letting an unparseable JUnit XML (e.g. zero-byte file from a crashed
pytest invocation) crash the parser instead of yielding "missing"
outcomes for everything that was expected to run.  The harness should
distinguish "test failed" from "we couldn't even score it".

## 11. Simpler alternative & why it breaks later

Returning `(passed, total)` as a tuple from the runner.  Fine until
you want to know *which* case failed, *why*, *how long it took*, and
*what trace URL to follow*.  Each of those is a new field; once you
have four, you might as well have a dataclass.

## 12. Exercise

Add a `CaseOutcome.errored: bool` (separate from `failed`) and update
the parser to set it when the JUnit element is `<error>` instead of
`<failure>`.  Pytest distinguishes them; today our parser collapses
both into `failed`.

## 13. What Tier C adds here

This stage *is* Tier C.  Stage 19 takes the next step: the outer Deep
Agent itself runs in a separate process so its dependency tree is
independent of the inner agent's.
