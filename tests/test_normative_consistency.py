"""Make the normative documents of `docs/thin-harness` executable.

`CLAUDE.md` defines `admission` as "whether a result may serve as the basis of a
scientific conclusion", and the operational corollary is that an inconsistency must never
resolve in the direction that makes a record look better founded than it is. A document
that states behaviour the code must satisfy, with nothing checking that it does, is itself
an unverified claim -- so it fails the rule it exists to serve. This module is layer 3 of
`HARDENING_CRITERION.md` §2 applied to the conventions themselves: three jobs, each
turning a class of document/code drift from something a reader may notice into something
that fails here.

**J1 -- version strings.** `learn/admission_view.VIEW_VERSION` is the version
`ADMISSION_PROPAGATION.md` currently declares, and every older `etalon-admission-view/N`
string in that document sits where the accretive style puts it. The style is deliberate:
§1-§9 are the v1 record, §10 amends them for v2, §11 for v3, and superseded statements are
kept with the heading annotated rather than deleted. These tests accommodate that rather
than flattening it -- an old version string is fine in a section whose heading marks it
superseded, or in the amendment section that declared it.

**J2 -- invariant identifiers.** Every invariant the documents declare is accounted for in
`tests/normative_invariant_registry.py`, and every binding there resolves to a test pytest
collects. See that module for the BOUND / PARTIAL / UNBOUND split and why three states are
needed instead of two.

**J3 -- fixed-terminology status.** For each vocabulary `CLAUDE.md` fixes, the status is
recomputed from the code and compared with what `FIXED_TERMINOLOGY_STATUS.md` records. The
load-bearing distinction is between *the word appears* and *the concept is implemented*: a
word occupied by another meaning (`verification = adapter.verify(root)` is host-install
verification, not "passed its declared checks") is not an implementation. These tests do
not decide anything the repo owner has left open -- in particular nothing here prefers
implementing or withdrawing `soundness` and `progress`; they only make the current state
checkable.

Every number any assertion here states carries its basis, and a quantity that cannot be
obtained is reported as not obtained rather than estimated (`CLAUDE.md` hard constraint 7).
Nothing in this module writes to the repository, and no test here imports or exercises
anything under `asset/` (hard constraint 6).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import normative_invariant_registry as reg

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "etalon"
DESIGN = "docs/thin-harness/ADMISSION_PROPAGATION.md"
REGIMES = "docs/thin-harness/ASSESSMENT_REGIMES.md"
STATUS_DOC = "docs/thin-harness/FIXED_TERMINOLOGY_STATUS.md"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def src_files() -> list[Path]:
    """Every Python module under `src/etalon`. `asset/` is not reachable from here."""

    return sorted(SRC.rglob("*.py"))


def rel_src(path: Path) -> str:
    return str(path.relative_to(SRC))


# ====================================================================== J1


_VERSION = re.compile(r"etalon-admission-view/(\d+)")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SUPERSEDED = re.compile(r"supersede", re.IGNORECASE)
#: The two forms in which a section of the design doc declares *its own* output version.
#: §1: "Output schema `etalon-admission-view/1`, carrying `view_version`".
#: §10/§11: "`view_version` becomes `\"etalon-admission-view/2\"`".
_DECLARES = re.compile(
    r"`view_version`\s+becomes\s+`\"etalon-admission-view/(\d+)\"`"
    r"|Output schema\s+`etalon-admission-view/(\d+)`"
)


def _headings(text: str) -> list[tuple[int, int, str]]:
    """(line_number, level, heading_text) for every markdown heading, in order."""

    out = []
    for lineno, line in enumerate(text.splitlines(), 1):
        m = _HEADING.match(line)
        if m:
            out.append((lineno, len(m.group(1)), m.group(2)))
    return out


def _enclosing(headings: list[tuple[int, int, str]], lineno: int) -> list[tuple[int, int, str]]:
    """The heading chain enclosing `lineno`, outermost first.

    A line inside §10.4 is enclosed by both "## 10. ..." and "### 10.4 ...", so an
    annotation on either heading counts: the accretive style annotates whichever heading
    owns the superseded statement.
    """

    chain: list[tuple[int, int, str]] = []
    for head in headings:
        if head[0] >= lineno:
            break
        while chain and chain[-1][1] >= head[1]:
            chain.pop()
        chain.append(head)
    return chain


def _sections_declaring_versions(text: str) -> dict[int, list[tuple[int, int, str]]]:
    """version number -> the heading chain of the section that declares it."""

    headings = _headings(text)
    out: dict[int, list[tuple[int, int, str]]] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        m = _DECLARES.search(line)
        if m:
            version = int(m.group(1) or m.group(2))
            out.setdefault(version, _enclosing(headings, lineno))
    return out


@pytest.fixture(scope="module")
def design_doc() -> str:
    return read(DESIGN)


@pytest.fixture(scope="module")
def declared_versions(design_doc: str) -> dict[int, list[tuple[int, int, str]]]:
    declared = _sections_declaring_versions(design_doc)
    assert declared, (
        f"{DESIGN} declares no output version at all. A section declares one by writing "
        "either 'Output schema `etalon-admission-view/N`' or '`view_version` becomes "
        '`"etalon-admission-view/N"`\'. Restore one of those forms.'
    )
    return declared


def test_j1_view_version_constant_is_the_version_the_design_doc_declares_current(
        declared_versions: dict[int, list[tuple[int, int, str]]]) -> None:
    """The code's VIEW_VERSION is the highest version the design doc declares.

    "Current" is the highest declared version rather than the last textually, because the
    accretive style appends amendment sections: §1 declares v1, §10 declares v2, §11
    declares v3, and all three stay in the file.
    """

    from etalon.learn.admission_view import VIEW_VERSION

    current = max(declared_versions)
    expected = f"etalon-admission-view/{current}"
    assert VIEW_VERSION == expected, (
        f"src/etalon/learn/admission_view.py declares VIEW_VERSION = {VIEW_VERSION!r}, but "
        f"{DESIGN} declares {expected!r} as its current output version (highest declared: "
        f"v{current}, in section {declared_versions[current][-1][2]!r}).\n"
        "Pick one of two repairs, do not touch both ends to meet in the middle:\n"
        f"  (a) the code moved first -- append a new section to {DESIGN} declaring "
        f"'`view_version` becomes `\"{VIEW_VERSION}\"`', annotate the heading of the "
        "section it supersedes, and leave the older text in place (accretive style);\n"
        "  (b) the doc moved first -- set VIEW_VERSION to the declared value.\n"
        "A version bump is required whenever a `class_basis` string, an output field or a "
        "classification changes, because the output's view_id is a digest of its own "
        "content and compare_views must refuse rather than mix (§10.6, §11)."
    )


def test_j1_older_version_strings_sit_only_where_the_accretive_style_permits(
        design_doc: str, declared_versions: dict[int, list[tuple[int, int, str]]]) -> None:
    """Every superseded `etalon-admission-view/N` is in an annotated or declaring section.

    Two placements are legitimate, and this test accepts both rather than demanding the
    historical sections be rewritten:
      (a) the enclosing heading carries a supersession annotation, e.g.
          "## 1. What the view is (... output schema version superseded by §11)";
      (b) the section is the amendment layer that declared version N in the first place
          (§1 for v1, §10 for v2), so the string is that section's own record.
    """

    current = max(declared_versions)
    headings = _headings(design_doc)
    declaring_heads = {
        version: chain[-1][0] for version, chain in declared_versions.items()
    }
    misplaced: list[str] = []
    for lineno, line in enumerate(design_doc.splitlines(), 1):
        for m in _VERSION.finditer(line):
            version = int(m.group(1))
            if version == current:
                continue
            chain = _enclosing(headings, lineno)
            annotated = any(_SUPERSEDED.search(text) for _, _, text in chain)
            own_section = bool(chain) and chain[-1][0] == declaring_heads.get(version)
            if not (annotated or own_section):
                where = chain[-1][2] if chain else "(before the first heading)"
                misplaced.append(
                    f"{DESIGN}:{lineno}: 'etalon-admission-view/{version}' under heading "
                    f"{where!r}"
                )
    assert not misplaced, (
        "A superseded output-version string sits in a section that neither declares that "
        "version nor is annotated as superseded, so a reader cannot tell it is history:\n  "
        + "\n  ".join(misplaced)
        + f"\n\nCurrent version is v{current}. Two repairs, both of which keep the "
        "accretive style:\n"
        "  (a) annotate that section's heading in place, the way §1 is annotated: "
        '"## 1. What the view is (... output schema version superseded by §11)";\n'
        f"  (b) if the statement is still live, update the string to "
        f"'etalon-admission-view/{current}'.\n"
        "Do not delete the historical text: superseded statements are kept and the "
        "heading is annotated (CLAUDE.md hard constraint 3, `supersedes` semantics)."
    )


def test_j1_the_section_declaring_the_current_version_is_not_itself_marked_superseded(
        declared_versions: dict[int, list[tuple[int, int, str]]]) -> None:
    """The live version cannot be declared inside a section annotated as superseded."""

    current = max(declared_versions)
    chain = declared_versions[current]
    annotated = [text for _, _, text in chain if _SUPERSEDED.search(text)]
    assert not annotated, (
        f"v{current} is the highest version {DESIGN} declares, but it is declared inside a "
        f"section whose heading says it is superseded: {annotated!r}. Either a newer "
        "amendment section was added without declaring its own `view_version` (add the "
        "'`view_version` becomes ...' line to it), or the annotation is wrong."
    )


def test_j1_no_other_module_in_src_pins_a_stale_output_version_string() -> None:
    """Only `admission_view.py` may carry the literal, and only at the current value."""

    from etalon.learn.admission_view import VIEW_VERSION

    offenders: list[str] = []
    for path in src_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in _VERSION.finditer(line):
                if m.group(0) != VIEW_VERSION:
                    offenders.append(f"src/etalon/{rel_src(path)}:{lineno}: {m.group(0)}")
    assert not offenders, (
        "A superseded output-version literal is pinned in source, where it will be "
        f"compared against the live {VIEW_VERSION!r} and silently disagree:\n  "
        + "\n  ".join(offenders)
        + "\nUse `etalon.learn.admission_view.VIEW_VERSION` instead of a literal."
    )


def test_j1_design_doc_status_line_names_the_version_it_declares(
        design_doc: str, declared_versions: dict[int, list[tuple[int, int, str]]]) -> None:
    """The header's "Status: design vN" is the version the body declares.

    The header is the one line a reader checks before trusting the rest, so a stale value
    there makes the whole document look older -- and therefore more settled -- than it is.
    Asserted separately from the constant so the two failures stay distinguishable.
    """

    current = max(declared_versions)
    m = re.search(r"^Status:\s*design\s+v(\d+)", design_doc, re.MULTILINE)
    assert m, (
        f"{DESIGN} has no 'Status: design vN' header line. Restore it: the J1 checks and "
        "every reader use it as the document's own statement of which version is live."
    )
    assert int(m.group(1)) == current, (
        f"{DESIGN} header says 'Status: design v{m.group(1)}' while the body declares "
        f"v{current} as current (section {declared_versions[current][-1][2]!r}, which sets "
        f"`view_version` to 'etalon-admission-view/{current}'). Update the header to "
        f"'Status: design v{current}' and extend its supersession sentence to name the new "
        "amendment section, the way it already names §10."
    )


# ====================================================================== J2


#: The declaration form used throughout `docs/thin-harness`: a bold id at the head of a
#: list item, e.g. "- **I9 - completeness.** ...". A plain mention ("invariant I7", or
#: "I8: the truncated-graph refusal is replaced by I9") is a reference, not a declaration.
_DECLARATION = re.compile(r"^\s*-\s+\*\*(I\d{1,2})\b")
_MENTION = re.compile(r"\b(I\d{1,2})\b")


def _declarations() -> dict[str, list[str]]:
    """invariant id -> where it is declared, scanned over the declaring documents."""

    found: dict[str, list[str]] = {}
    for doc in reg.DECLARING_DOCS:
        for lineno, line in enumerate(read(doc).splitlines(), 1):
            m = _DECLARATION.match(line)
            if m:
                found.setdefault(m.group(1), []).append(f"{doc}:{lineno}")
    return found


@pytest.fixture(scope="module")
def declared() -> dict[str, list[str]]:
    found = _declarations()
    assert found, (
        "No invariant declaration was found in "
        f"{', '.join(reg.DECLARING_DOCS)}. The form this scan recognises is a bold id at "
        'the head of a list item: "- **I9 - completeness.** ...". If the documents now '
        "declare invariants in another form, update `_DECLARATION` here and in the "
        "registry's docstring -- do not leave the scan matching nothing, because an empty "
        "scan makes every other J2 assertion vacuous."
    )
    return found


@pytest.fixture(scope="module")
def collected() -> set[str]:
    """Function-level pytest node ids collected from the files the registry points at.

    Basis: a `pytest --collect-only -q` subprocess over exactly `reg.files()`, run with
    PYTHONPATH=src because `etalon` is not pip-installed in this environment. Parametrised
    ids lose their `[param]` suffix, so the registry can name a parametrised test once.
    """

    env = {**os.environ, "PYTHONPATH": "src" + os.pathsep + os.environ.get("PYTHONPATH", "")}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *reg.files(), "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    ids = set()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if "::" in line and line.startswith("tests/"):
            ids.add(re.sub(r"\[.*\]$", "", line))
    assert ids, (
        "Collecting the registry's test files produced no node ids, so 'is collected' "
        "cannot be checked and is reported as not obtained rather than assumed.\n"
        f"command: {sys.executable} -m pytest {' '.join(reg.files())} --collect-only -q\n"
        f"returncode: {proc.returncode}\nstdout tail:\n{proc.stdout[-2000:]}\n"
        f"stderr tail:\n{proc.stderr[-2000:]}"
    )
    return ids


def test_j2_every_declared_invariant_is_accounted_for_in_the_registry(
        declared: dict[str, list[str]]) -> None:
    """Declared but unregistered is the silent gap this registry exists to prevent."""

    missing = sorted(set(declared) - reg.all_registered(), key=lambda i: int(i[1:]))
    assert not missing, (
        "These invariants are declared in the documents and appear in neither BOUND nor "
        "UNBOUND of tests/normative_invariant_registry.py:\n  "
        + "\n  ".join(f"{i} declared at {', '.join(declared[i])}" for i in missing)
        + "\nAdd each one. If a test already holds it, add it to BOUND with the node ids. "
        "If none does, add it to UNBOUND with one line saying what is missing -- an "
        "unbound invariant is visible data, an unregistered one is not."
    )


def test_j2_registry_has_no_entry_for_an_invariant_the_documents_no_longer_declare(
        declared: dict[str, list[str]]) -> None:
    stale = sorted(reg.all_registered() - set(declared), key=lambda i: int(i[1:]))
    assert not stale, (
        "tests/normative_invariant_registry.py registers invariants that no document "
        f"declares any more: {stale}. Either the declaration was deleted (then drop the "
        "registry entry, and say in the amending section that the invariant was "
        "withdrawn) or it was renumbered (then renumber here too)."
    )


def test_j2_every_invariant_id_mentioned_in_the_declaring_docs_is_registered(
        declared: dict[str, list[str]]) -> None:
    """Catches a new invariant declared in a form the declaration scan does not match.

    A mention is weaker evidence than a declaration, so this does not treat mentions as
    declarations -- it only refuses an id that is talked about and nowhere accounted for.
    """

    unaccounted: dict[str, list[str]] = {}
    for doc in reg.DECLARING_DOCS:
        for lineno, line in enumerate(read(doc).splitlines(), 1):
            for ident in _MENTION.findall(line):
                if ident not in reg.all_registered():
                    unaccounted.setdefault(ident, []).append(f"{doc}:{lineno}")
    assert not unaccounted, (
        "These invariant ids are referred to in the normative documents but are in neither "
        "BOUND nor UNBOUND:\n  "
        + "\n  ".join(f"{i} at {', '.join(where)}" for i, where in sorted(unaccounted.items()))
        + "\nIf one is a new invariant, declare it in the documents' own form "
        '("- **I21 - ...**") and register it. If it is a typo, fix the reference.'
    )


def test_j2_the_three_registry_structures_partition_the_declared_invariants(
        declared: dict[str, list[str]]) -> None:
    """BOUND and UNBOUND are disjoint and together cover everything declared."""

    overlap = sorted(set(reg.BOUND) & set(reg.UNBOUND))
    assert not overlap, (
        f"{overlap} are in both BOUND and UNBOUND. An invariant is either bound to tests "
        "or it is not; if the binding is incomplete rather than absent, it belongs in "
        "BOUND with its unestablished clause named in PARTIAL."
    )
    assert reg.all_registered() == set(declared), (
        "registered ids and declared ids differ; see the two tests above for which way."
    )
    # Reported with its basis so the split is a measured quantity, not an impression.
    assert len(reg.BOUND) + len(reg.UNBOUND) == len(declared), (
        f"bound={len(reg.BOUND)} + unbound={len(reg.UNBOUND)} does not add up to "
        f"declared={len(declared)} (basis: declarations matched by `_DECLARATION` over "
        f"{', '.join(reg.DECLARING_DOCS)})."
    )


def test_j2_every_registry_binding_resolves_to_a_test_that_exists_and_is_collected(
        collected: set[str]) -> None:
    """The half of the registry that rots silently: a test renamed, moved or deleted.

    One assertion covers both directions the brief asks for -- "resolves to a test that
    actually exists and is collected" and "no entry points at a test that no longer
    exists" -- because for a node id those are the same question.
    """

    unresolved: dict[str, list[str]] = {}
    for ident, node_ids in reg.BOUND.items():
        for node_id in node_ids:
            if node_id not in collected:
                unresolved.setdefault(ident, []).append(node_id)
    assert not unresolved, (
        "These registry bindings do not resolve to a collected test:\n  "
        + "\n  ".join(
            f"{i}: " + ", ".join(ids) for i, ids in sorted(unresolved.items(),
                                                           key=lambda kv: int(kv[0][1:])))
        + "\n(basis: `pytest --collect-only -q` over "
        + " ".join(reg.files())
        + ", parametrised suffixes stripped.)\n"
        "If the test was renamed, update the node id here. If it was deleted, the "
        "invariant lost its test: move the entry to UNBOUND with the reason, or bind it to "
        "the test that replaced it. Do not delete the entry -- that would turn a known gap "
        "back into an unverified claim."
    )


def test_j2_every_file_the_registry_names_exists() -> None:
    missing = [f for f in reg.files() if not (ROOT / f).is_file()]
    assert not missing, (
        f"the registry points at test files that do not exist: {missing}"
    )


def test_j2_no_binding_is_empty() -> None:
    empty = sorted(i for i, ids in reg.BOUND.items() if not ids)
    assert not empty, (
        f"{empty} are listed in BOUND with no node ids, which reads as bound while holding "
        "nothing. Move them to UNBOUND with a reason."
    )


def test_j2_partial_entries_name_a_bound_invariant_and_state_the_unestablished_clause() -> None:
    """PARTIAL is only meaningful if it says *which* clause is not established.

    A blank or vague reason would make a partially verified invariant look fully verified,
    which is the direction the first principle forbids.
    """

    not_bound = sorted(set(reg.PARTIAL) - set(reg.BOUND))
    assert not not_bound, (
        f"{not_bound} are in PARTIAL but not in BOUND. PARTIAL qualifies a binding; an "
        "invariant with no binding at all belongs in UNBOUND."
    )
    thin = sorted(i for i, reason in reg.PARTIAL.items() if len(reason.strip()) < 40)
    assert not thin, (
        f"these PARTIAL entries do not state which declared clause is unestablished: "
        f"{thin}. Name the clause, in the declaration's own words, so a reader can see "
        "exactly how much of the invariant the tests carry."
    )


def test_j2_unbound_entries_each_carry_a_reason() -> None:
    thin = sorted(i for i, reason in reg.UNBOUND.items() if len(reason.strip()) < 40)
    assert not thin, (
        f"these UNBOUND entries carry no usable reason: {thin}. One line each, naming what "
        "no fixture does -- an unbound invariant has to be visible data, and 'UNBOUND' on "
        "its own says only that somebody gave up."
    )


# ====================================================================== J3


#: The ASCII tokens `CLAUDE.md`'s 固定术语 block fixes, pinned from lines 4-8 at HEAD
#: 5764928. Pinned rather than derived so that *adding* a term is what fails: a new term
#: with no status row is exactly the case J3 has to catch, and a set recomputed from the
#: file every run could never notice it.
CLAUDE_FIXED_TOKENS = frozenset({
    "admission", "completion", "relied_on", "used", "verification",
})

#: The enum values each withdrawn term brought with it. The *terms* are not listed here --
#: they are read from `research/reserved_bindings.WITHDRAWN`, which is the one definition
#: that has consequences, because it is what refuses the name at a write. This mapping only
#: expands each term into the tokens `CLAUDE.md` used to fix alongside it, so that re-fixing
#: `unsound_recoverable` is caught as well as re-fixing `soundness`.
#:
#: `precision` has no entry in the source registry on purpose: nothing was ever going to
#: compute it, so there is no field to refuse. Its withdrawal is a reporting convention
#: changing, which is exactly the class of thing a document can hold.
WITHDRAWN_ENUM_VALUES = {
    "soundness": ("sound", "unsound_recoverable", "unsound_terminal"),
    "progress": ("advanced", "no_progress", "regressed"),
    "precision": ("validity",),
}


def withdrawn_tokens() -> dict[str, tuple[str, ...]]:
    """term -> every token `CLAUDE.md` fixed for it, with the terms taken from the source.

    Derived rather than pinned so that a term reinstated as a real field has to be removed
    from `reserved_bindings.WITHDRAWN` to get past this file -- which is the same edit that
    stops the write being refused. One definition, one place to change it.
    """

    from etalon.research.reserved_bindings import WITHDRAWN

    terms = sorted(set(WITHDRAWN) | {"precision"})
    return {term: (term, *WITHDRAWN_ENUM_VALUES.get(term, ())) for term in terms}

#: Status vocabulary of `FIXED_TERMINOLOGY_STATUS.md` §4, normalised. The Chinese cell for
#: the precision/validity row is kept verbatim: it is not one of the four English statuses
#: that document defines, and rewriting it here would be paraphrasing a fixed term.
STATUS_IMPLEMENTED = "implemented"
STATUS_AS_STRUCTURE = "implemented as structure"
STATUS_DERIVED_ONLY = "derived only"
STATUS_PROSE_ONLY = "prose only"
#: `STATUS_PROSE_ONLY` has no term today -- `soundness` and `progress` moved to
#: `refused at a write` (FIXED_TERMINOLOGY_STATUS.md §6.3). It stays because it is
#: still the honest status for a *future* fixed term that names nothing, and the
#: guidance in J3's failure message offers it as one of the four.


def _fixed_block_tokens() -> set[str]:
    """ASCII tokens inside `CLAUDE.md`'s 固定术语 section, and only that section.

    Read by section heading rather than by line number. The line range this replaced
    (`splitlines()[3:8]`) was correct at HEAD `5764928` and silently wrong the first time a
    heading moved -- it began reading into the 已撤回的固定术语 section, which names the
    withdrawn terms in order to say they are withdrawn, and would have reported them as
    still fixed. A pinned range over a file that gets edited is the same drift class J3
    exists to catch, one level down.
    """

    tokens: set[str] = set()
    inside = False
    for line in read("CLAUDE.md").splitlines():
        if line.startswith("###"):
            inside = "固定术语" in line and "撤回" not in line
            continue
        if inside and line.strip().startswith("-"):
            tokens |= set(re.findall(r"[A-Za-z][A-Za-z_]{2,}", line))
    return tokens


def _status_rows() -> dict[str, tuple[str, str]]:
    """term key -> (normalised status, the row's location/hazard cell).

    The term key is the first backticked token of the row's first cell, which is unique
    across the table.
    """

    rows: dict[str, tuple[str, str]] = {}
    for line in read(STATUS_DOC).splitlines():
        if not line.startswith("|"):
            continue
        # Split on unescaped pipes only: the soundness and progress rows spell their enum
        # out in the term cell ("`sound` \| `unsound_recoverable`"), and splitting those
        # escaped pipes would drop exactly the two rows J3 most needs to read.
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if len(cells) != 4 or set(cells[0]) <= set("- "):
            continue
        key = re.search(r"`([a-z_]+)`", cells[0])
        if not key or cells[2] in {"实现状态"}:
            continue
        status = cells[2].replace("**", "").strip()
        status = re.split(r"\s+—\s+|\s*——\s*", status)[0].strip()
        rows[key.group(1)] = (status, cells[3])
    return rows


@pytest.fixture(scope="module")
def status_rows() -> dict[str, tuple[str, str]]:
    rows = _status_rows()
    assert rows, (
        f"no status rows parsed out of {STATUS_DOC} §4. The parser expects the four-column "
        "markdown table whose first cell backticks the term. If the table's shape changed, "
        "update `_status_rows` -- an empty parse would make every J3 comparison vacuous."
    )
    return rows


def _code_token_sites(term: str) -> list[tuple[str, int, str]]:
    """Sites in `src/etalon` where `term` is a code token, not an English word.

    A code token is the term as a quoted string literal, a bound name (`x =`, `x +=`), a
    `def`/`class` name, or an annotated name (`x: T`). Prose in a docstring or comment is
    deliberately excluded: this probe is for "the word is spent on something in the code",
    which is the hazard class `FIXED_TERMINOLOGY_STATUS.md` §2.2-§2.3 records. Keyword
    arguments (`f(progress=...)`) also match the bound-name form, so every reported site
    carries its line for the reader to judge.
    """

    patterns = [
        re.compile(r"""['"]%s['"]""" % re.escape(term)),
        re.compile(r"\b%s\s*[-+*/|&]?=(?!=)" % re.escape(term)),
        re.compile(r"\bdef\s+%s\b" % re.escape(term)),
        re.compile(r"\bclass\s+%s\b" % re.escape(term), re.IGNORECASE),
        re.compile(r"\b%s\s*:\s*[A-Za-z\[]" % re.escape(term)),
    ]
    sites: list[tuple[str, int, str]] = []
    for path in src_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(p.search(line) for p in patterns):
                sites.append((rel_src(path), lineno, line.strip()[:110]))
    return sites


def _word_line_count(term: str) -> int:
    """Lines under `src/etalon` containing `term`. The counting basis of the status doc.

    `FIXED_TERMINOLOGY_STATUS.md` states counts without naming the basis; matching lines
    over `src/etalon/**/*.py` reproduces every count it gives (Admission 29, precision 7,
    validity 50), so that is the basis used here and stated wherever a count is asserted.
    """

    pattern = re.compile(r"%s" % re.escape(term))
    return sum(bool(pattern.search(line))
               for path in src_files()
               for line in path.read_text(encoding="utf-8").splitlines())


def _contains(rel: str, needle: str) -> bool:
    path = SRC / rel
    return path.is_file() and needle in path.read_text(encoding="utf-8")


# ---- status derived from the code, one derivation per fixed vocabulary -------


def _derive_admission() -> tuple[str, str]:
    from etalon.learn.admissible import Admission

    values = {m.value for m in Admission}
    count = _word_line_count("admission")
    if values == {"admitted", "admitted_under_waiver", "withheld"} and count > 1:
        return STATUS_IMPLEMENTED, (
            f"learn/admissible.py defines Admission with exactly {sorted(values)} and the "
            f"token occurs on {count} lines of src/etalon (basis: matching lines over "
            "src/etalon/**/*.py)"
        )
    return "not implemented", f"Admission values are {sorted(values)}; token lines={count}"


def _derive_structure(term: str) -> tuple[str, str]:
    """`completion` / `verification`: carried under other field names.

    Derived as *implemented as structure* when no enum or class of the term's own name
    exists while the carriers the status document names do exist. If an enum of the term's
    own name appeared, the status would have to move to `implemented`.
    """

    from etalon.learn.admissible import Ruling
    from etalon.research.evaluation_contract import STATUSES

    own_enum = [s for s in _code_token_sites(term)
                if re.search(r"\bclass\s+%s\b" % term, s[2], re.IGNORECASE)]
    carriers = {
        'Evaluation.status in {"ok","failed","invalid","blocked"} (active/schema.py)':
            _contains("active/schema.py", '{"ok", "failed", "invalid", "blocked"}'),
        "evaluation_contract.STATUSES":
            set(STATUSES) == {"criteria_passed", "criteria_failed", "insufficient",
                              "incomparable"},
        "Ruling carries blocking and unchecked":
            {"blocking", "unchecked"} <= set(getattr(Ruling, "__annotations__", {})),
        'runtime/native.py "scientific_status": "not_inferred_from_exit_code"':
            _contains("runtime/native.py", "not_inferred_from_exit_code"),
    }
    absent = sorted(name for name, ok in carriers.items() if not ok)
    if own_enum:
        return STATUS_IMPLEMENTED, f"a class named {term} now exists: {own_enum}"
    if absent:
        return "carrier missing", f"the structures the status doc names are gone: {absent}"
    return STATUS_AS_STRUCTURE, (
        "no enum or class of that name in src/etalon, and all four carriers the status "
        f"document names are present: {sorted(carriers)}"
    )


def _derive_relied_on() -> tuple[str, str]:
    """`relied_on` / `used`: computed in the export view, absent from the emission edge
    vocabulary and from the record schemas."""

    import etalon.learn.admission_view as av
    from etalon.research.graph_memory import EDGES

    in_edges = sorted({t for t in ("relied_on", "used") if t in EDGES})
    in_view = {"relied_on", "used"} <= set(av._LABEL_VALUES)
    schema_files = [f for f in ("research/schema.py", "active/schema.py")
                    if _contains(f, "relied_on")]
    if in_edges:
        return STATUS_IMPLEMENTED, (
            f"graph_memory.EDGES now contains {in_edges}: the distinction is recorded at "
            "emission"
        )
    if schema_files:
        return "recorded in a schema", f"`relied_on` reached {schema_files}"
    if not in_view:
        return "not derived either", (
            f"admission_view._LABEL_VALUES is {sorted(av._LABEL_VALUES)}"
        )
    return STATUS_DERIVED_ONLY, (
        "graph_memory.EDGES contains neither token (it is "
        f"{sorted(EDGES)}), no record schema carries `relied_on`, and both are "
        "premise_class values computed by learn/admission_view.py::_classify"
    )


#: Tokens of the `soundness` and `progress` vocabularies that no other meaning can
#: plausibly occupy. `sound`, `advanced`, `progress` and `regressed` are ordinary English
#: and are checked as occupations instead (see the hazard tests); these three are not.
#: The record-schema modules. A fixed term that becomes a field here has stopped being a
#: reporting convention, whatever the status document still says.
SCHEMA_MODULES = ("research/schema.py", "active/schema.py")


#: (row key in the status table, expected status, derivation). One row per fixed
#: vocabulary of `CLAUDE.md` lines 4-8.
TERMS = (
    ("completion", STATUS_AS_STRUCTURE, lambda: _derive_structure("completion")),
    ("verification", STATUS_AS_STRUCTURE, lambda: _derive_structure("verification")),
    ("admission", STATUS_IMPLEMENTED, _derive_admission),
    ("relied_on", STATUS_DERIVED_ONLY, _derive_relied_on),
)


def test_j3_every_fixed_term_in_claude_md_has_a_status_row(
        status_rows: dict[str, tuple[str, str]]) -> None:
    """A term added to the fixed vocabulary without a status is the J3 failure case.

    `CLAUDE.md:3-8` forbids paraphrasing five vocabularies. A reader obeying that learns
    which words to use and nothing about whether the words name anything, so every fixed
    term needs a status beside it.
    """

    tokens = _fixed_block_tokens()
    new = sorted(tokens - CLAUDE_FIXED_TOKENS)
    assert not new, (
        f"CLAUDE.md's 固定术语 block now fixes tokens that J3 has never checked: {new}.\n"
        f"Give each a status row in {STATUS_DOC} §4 (one of: {STATUS_IMPLEMENTED!r}, "
        f"{STATUS_AS_STRUCTURE!r}, {STATUS_DERIVED_ONLY!r}, {STATUS_PROSE_ONLY!r}), add a "
        "derivation for it to TERMS here, and add the token to CLAUDE_FIXED_TOKENS. A "
        "fixed term with no status is a word a reader cannot tell from an implemented one."
    )
    gone = sorted(CLAUDE_FIXED_TOKENS - tokens)
    assert not gone, (
        f"these tokens were fixed vocabulary at HEAD 5764928 and are no longer in "
        f"CLAUDE.md's 固定术语 block: {gone}. If a term was withdrawn, say so in "
        f"{STATUS_DOC} and drop it from CLAUDE_FIXED_TOKENS and TERMS -- a silent removal "
        "leaves tests asserting a convention that no longer binds."
    )
    unrowed = [key for key, _, _ in TERMS if key not in status_rows]
    assert not unrowed, (
        f"{STATUS_DOC} §4 has no row for {unrowed}. Every fixed vocabulary needs one."
    )


@pytest.mark.parametrize("key,expected_recorded,derive", TERMS,
                         ids=[t[0] for t in TERMS])
def test_j3_status_derived_from_the_code_matches_the_status_the_document_records(
        key: str, expected_recorded: str, derive, status_rows: dict[str, tuple[str, str]]
) -> None:
    """The status document's claim about each term, recomputed from the code.

    Two failures are possible and they want different repairs, so the message says which:
    the document's row drifted from the code, or this test's pinned expectation drifted
    from the document.
    """

    recorded, hazard_cell = status_rows[key]
    assert recorded == expected_recorded, (
        f"{STATUS_DOC} §4 records status {recorded!r} for `{key}`, but this test was "
        f"written against {expected_recorded!r}. If the row was deliberately changed, "
        "update TERMS here and check the derivation still computes the new status."
    )
    derived, basis = derive()
    assert derived == recorded, (
        f"`{key}`: the document records {recorded!r}; the code says {derived!r}.\n"
        f"basis: {basis}\n"
        f"row's location/hazard cell: {hazard_cell}\n"
        f"Repair: update the {STATUS_DOC} §4 row to the derived status (and its evidence "
        "in §2), or, if the code change was unintended, revert it. Do not change this "
        "test to agree with the code -- the row is the claim under test."
    )


#: Sites `FIXED_TERMINOLOGY_STATUS.md` §2 cites as evidence, with the token each citation
#: rests on. Checked by path and token rather than by line number: asserting the line
#: would fail on any unrelated edit above it, which is a false alarm the first principle
#: gives no reason to pay for. Line numbers in the document stay locators.
CITED_EVIDENCE = (
    ("learn/admissible.py", "class Admission", "the Admission enum (§2.4)"),
    ("learn/admission_view.py", "_classify", "premise_class computation (§2.4)"),
    ("research/graph_memory.py", "EDGES", "the emission edge vocabulary (§2.4)"),
    ("faults/taxonomy.py", "class Evidence", "Evidence provenance enum (§2.4)"),
    ("active/schema.py", '{"ok", "failed", "invalid", "blocked"}', "Evaluation.status (§2.4)"),
    ("runtime/native.py", "not_inferred_from_exit_code", "completion as structure (§2.4)"),
    ("research/evaluation_contract.py", "STATUSES", "verification as structure (§2.4)"),
    ("host_install.py", "verification = adapter.verify(root)",
     "verification occupied by host-installation verification"),
    ("learn/acquire.py", "regressed", "the `regressed` collision (§2.2)"),
    ("learn/__init__.py", "regressed", "the `regressed` collision (§2.2)"),
    ("active/protocol_score.py", "precision", "precision as Bayesian precision (§2.3)"),
    ("active/knowledge.py", "precision", "precision as float precision (§2.3)"),
    ("research/pose_verifier.py", "validity", "validity as pose validity (§2.3)"),
    ("research/pose_selection.py", "validity", "validity as pose validity (§2.3)"),
    ("research/pose_pool.py", "validity", "validity as pose validity (§2.3)"),
    ("research/result_semantics.py", "This is not a scientific validity or adoption assessment.",
     "the explicit disclaimer of the other reading (§2.3)"),
    ("research/schema.py", "sealed_holdout", "Artifact.role about bytes (§2.3)"),
    ("research/schema.py", "assessment_role", "MethodEvaluation.assessment_role about a claim (§2.3)"),
)


def test_j3_every_code_site_the_status_document_cites_still_exists() -> None:
    """A status claim resting on a citation that has moved is no longer a status claim."""

    gone = [f"src/etalon/{rel}: {why} -- {token!r} not found"
            for rel, token, why in CITED_EVIDENCE if not _contains(rel, token)]
    assert not gone, (
        f"{STATUS_DOC} rests on code sites that no longer carry what it cites:\n  "
        + "\n  ".join(gone)
        + f"\nRe-run the §2 searches and update the document, or restore the code. A "
        "status column whose evidence has moved records a claim nobody can check."
    )


def test_j3_the_word_appearing_is_not_the_concept_being_implemented(
        status_rows: dict[str, tuple[str, str]]) -> None:
    """`completion` and `verification`: occupied identifiers are not implementations.

    The status stays `implemented as structure` either way -- that is settled by the
    carriers, and is asserted in the parametrised test above. What this test checks is the
    narrower factual claim the document makes alongside it, that neither word is an
    identifier in `src/etalon`, because that is the claim a future reader would use to
    conclude the word is free.
    """

    # Whether the words are occupied is a fact about the code that no document edit can
    # change, so asserting they are free would make this test permanently red and assert a
    # false requirement. What is checkable, and what the docstring above actually describes,
    # is whether the document still makes the ABSOLUTE claim while an occupation exists.
    ABSOLUTE = ("neither word is an identifier in `src/etalon`", "术语本身不是标识符")
    doc = read(STATUS_DOC)
    unqualified = [claim for claim in ABSOLUTE if claim in doc]
    occupied = {term: _code_token_sites(term) for term in ("completion", "verification")}
    claimed_absent = {term: sites for term, sites in occupied.items() if sites} if unqualified else {}
    assert not claimed_absent, (
        f"{STATUS_DOC} still carries an unqualified claim that the word is not an "
        f"identifier ({unqualified!r}) while the code disagrees. Qualify it to "
        "\"not an identifier *of this concept*\" and record the occupation as a hazard, "
        "the way §2.3 records `precision` and `validity`.\n  "
        + "\n  ".join(
            f"{term}: {len(sites)} code-token sites, e.g. "
            + "; ".join(f"src/etalon/{f}:{n}" for f, n, _ in sites[:3])
            + (f"\n      first: {sites[0][2]}" if sites else "")
            for term, sites in sorted(claimed_absent.items()))
        + "\n(basis: quoted literals, bound names, def/class names and annotated names "
        "over src/etalon/**/*.py; docstring and comment prose excluded.)\n"
        "The status itself is unaffected -- an occupied word is not an implementation of "
        "the fixed concept, which is the whole point of the distinction. What needs "
        "repair is the absolute claim: qualify it to say the word is not an identifier "
        "*of this concept*, and record the occupation as a hazard the way §2.3 records "
        "`precision` and `validity`."
    )


def _unrecorded(terms: tuple[str, ...]) -> dict[str, list[tuple[str, int, str]]]:
    """Code-token sites of `terms` in files the status document does not cite at all."""

    doc = read(STATUS_DOC)
    out: dict[str, list[tuple[str, int, str]]] = {}
    for term in terms:
        for site in _code_token_sites(term):
            if site[0] not in doc:
                out.setdefault(term, []).append(site)
    return out


def _render(unrecorded: dict[str, list[tuple[str, int, str]]]) -> str:
    return "\n  ".join(
        f"{term}:\n    " + "\n    ".join(f"src/etalon/{f}:{n}: {text}" for f, n, text in sites)
        for term, sites in sorted(unrecorded.items()))


def test_j3_no_unrecorded_occupation_of_precision_or_validity() -> None:
    """The precision/validity row's hazard list covers every code token of the two words.

    The row's claim is that the two words are occupied in `src/etalon` and name no field
    of the reporting concept. Keeping that checkable means the occupations it names have
    to be all of them, or a later reader will take an unnamed one for the fixed meaning.
    """

    unrecorded = _unrecorded(("precision", "validity"))
    assert not unrecorded, (
        f"{STATUS_DOC} §2.3 names `precision` in active/protocol_score.py and "
        "active/knowledge.py and `validity` in the pose modules and "
        "research/result_semantics.py. These code-token sites are in files it does not "
        "mention:\n  " + _render(unrecorded)
        + "\n(basis: quoted literals, bound names, def/class names and annotated names "
        "over src/etalon/**/*.py; prose excluded.)\n"
        "Repair: extend §2.3 with each site and what it means there. The §4 status stays "
        "报告用语,无字段 unless one of them turns out to name a record field, which the "
        "parametrised status test checks separately."
    )


# ====================================================================== J4


def test_j4_no_withdrawn_term_is_still_fixed_by_the_conventions() -> None:
    """The withdrawal landed in the file that states the conventions.

    `CLAUDE.md`'s 固定术语 section must no longer fix `soundness`, `progress`, or the
    `precision`/`validity` token mandate. The discipline behind the last one is kept in that
    section in a form the source does not contradict -- say whether a claim is about
    repeatability or about agreement with a measured quantity -- which is why this checks the
    *tokens* and not the sentence.
    """

    fixed = _fixed_block_tokens()
    for term, tokens in sorted(withdrawn_tokens().items()):
        still = sorted(t for t in tokens if t in fixed)
        assert not still, (
            f"`{term}` was withdrawn from the fixed vocabulary on 2026-11-10 "
            f"({STATUS_DOC} §6) and the 固定术语 block fixes {still} again. If that is "
            "deliberate, the withdrawal is being reversed: give the term a status row in "
            f"{STATUS_DOC} §4, a derivation in TERMS, and move it out of "
            "reserved_bindings.WITHDRAWN -- a term that is fixed again with §6 still "
            "saying it "
            "was withdrawn leaves two conventions contradicting each other."
        )


def test_j4_the_conventions_record_the_withdrawal_rather_than_dropping_it_silently() -> None:
    """A silent deletion and a decision read the same way afterwards. Only one is honest."""

    conventions = read("CLAUDE.md")
    assert "已撤回的固定术语" in conventions, (
        "CLAUDE.md no longer records that terms were withdrawn. A reader of a record written "
        "before the withdrawal cannot otherwise tell a term that was removed from one that "
        "was never there, which is the indistinguishability the first principle refuses."
    )
    for term in withdrawn_tokens():
        assert term in conventions, f"the withdrawal note no longer names `{term}`"
    status = read(STATUS_DOC)
    assert "## 6." in status and "withdrawn" in status, (
        f"{STATUS_DOC} §6 is the evidence and the argument behind the note in CLAUDE.md"
    )

def test_j4_the_withdrawn_names_are_refused_at_a_write_not_asked_for_in_prose() -> None:
    """Where the withdrawal is actually enforced, and why it is not enforced here.

    The first attempt at this check was a regular expression hunting imperatives across 28
    skill files -- prose policing prose. It matched nothing twice while the hazard stood, and
    the lesson is not that the pattern needed tuning: the instrument was wrong. The question
    re-asked at the right layer is *why can a field that does not exist be written at all*,
    and `research/reserved_bindings.py` answers it at the write.

    So this document-level test holds only what a document can hold -- that the conventions
    and the source name the same terms -- and the hazard itself is held by
    `tests/test_reserved_bindings.py`, against a real record.
    """

    from etalon.research.reserved_bindings import WITHDRAWN, validate_bindings
    from etalon.research.reserved_bindings import ReservedBindingError

    assert set(WITHDRAWN) == {"soundness", "progress"}, (
        "the source registry's withdrawn set changed; CLAUDE.md's 已撤回的固定术语 note and "
        f"{STATUS_DOC} §6 name these terms and must change with it"
    )
    for term in WITHDRAWN:
        with pytest.raises(ReservedBindingError):
            validate_bindings({term: "whatever"}, record="probe")
        # And the reason travels with the refusal: a host that hits this needs to know what
        # to do instead, not only that it may not.
        assert "FIXED_TERMINOLOGY_STATUS.md §6" in WITHDRAWN[term]


def test_j4_a_withdrawn_name_exists_in_source_only_as_a_name_that_is_refused() -> None:
    """The status that replaced `prose only`, and it is a stronger claim than that one was.

    Before the withdrawal these terms were `prose only`: named in the conventions,
    implemented nowhere, and therefore fillable by any host that read the instruction. They
    are now named in exactly one module, whose only purpose is to refuse them at a write. So
    the check is not "appears nowhere" -- it is "appears only where it is refused", which is
    what distinguishes a withdrawn field from a forgotten one.

    If a later round genuinely implements one, this is the test that has to be edited, and
    editing it means confronting §6.1's argument that `Ruling` and `Consequence` already
    carry the fact more finely.
    """

    from etalon.research.reserved_bindings import WITHDRAWN, ReservedBindingError
    from etalon.research.reserved_bindings import validate_bindings

    # Scoped to the record schemas, and the scope is the honest part. `progress` has ten
    # legitimate code-token sites -- a CLI subcommand at `research/cli.py:62`, a dataclass
    # field at `boundary/screen.py:178`, a backup callback at `research/handoff.py:216` --
    # which §2.3 recorded as collisions and none of which is a record field. A check over
    # every occurrence of the word would fail on correct code and would be asserting a
    # vocabulary monopoly nobody decided. What the withdrawal means is narrower and exact:
    # the name may not be a field of a record, and may not be carried in `bindings`.
    for term in sorted(WITHDRAWN):
        in_schemas = [f"src/etalon/{f}:{n}: {text}"
                      for f, n, text in _code_token_sites(term) if f in SCHEMA_MODULES]
        assert not in_schemas, (
            f"`{term}` is a withdrawn field name ({STATUS_DOC} §6) and now appears in a "
            f"record schema:\n  " + "\n  ".join(in_schemas)
            + "\nEither this is the term arriving as a real field -- in which case remove it "
            "from reserved_bindings.WITHDRAWN, give it a status row, and answer §6.1's "
            "argument that Ruling and Consequence already carry the fact more finely -- or "
            "it is a collision, which belongs in §2.3's list."
        )
        with pytest.raises(ReservedBindingError):
            validate_bindings({term: "a host's judgement"}, record="probe")


def test_j4_the_registry_is_the_only_definition_the_conventions_and_the_tests_read() -> None:
    """One definition, because this vocabulary now has consequences at a write.

    `EXPLAINED_STOPS` is this repository's example of what happens otherwise: a vocabulary
    kept in two places, already stale on one side, miscounting rounds that carried a reason.
    The conventions file, the status document and this test file all name these terms; none
    of them may be the authority.
    """

    from etalon.research.reserved_bindings import WITHDRAWN

    assert set(withdrawn_tokens()) >= set(WITHDRAWN), (
        "withdrawn_tokens() must cover every term the source registry refuses")
    for term in WITHDRAWN:
        assert term in read("CLAUDE.md"), f"the conventions no longer name `{term}`"
        assert term in read(STATUS_DOC), f"{STATUS_DOC} no longer names `{term}`"
