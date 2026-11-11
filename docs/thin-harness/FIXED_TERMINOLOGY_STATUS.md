# Proposed addition to `CLAUDE.md`: implementation status per fixed term

Status: proposal, 2026-11-09. **Not merged.** `CLAUDE.md` is uncommitted work owned by the
repo owner, so this file holds the proposed change for them to merge or refuse rather than
editing it. §4 is the block to paste; §1–§3 are the evidence for it and stay here.

Scope: this document records status and names hazards. **It does not decide whether
`soundness` and `progress` should be implemented or withdrawn.** That decision belongs to
the repo owner, is listed first among the things a previous review could not determine
(`etalon-architecture-review.md:612-616`), and nothing here presumes an answer.

> **Superseded on 2026-11-10 by §6.** The repo owner decided, and the decision is
> withdrawal. §1–§5 are kept as the pre-decision record, in this repository's accretive
> style: they are the evidence the decision was made on, and §4's proposed table is now
> history rather than a proposal. Read §6 first. Where §1–§5 say the question is open, §6
> is what closed it.

---

## 1. Why a fixed-terminology list needs a status column

`CLAUDE.md:3-8` fixes five vocabularies and forbids paraphrasing them. A reader obeying
that instruction learns which words to use and nothing about whether the words name
anything. Two of the five name nothing, and the list as written cannot say so.

The cost is specific. A term that exists only as an instruction to fill a field is a
**declared hazard**, not a vocabulary: the host supplies a value from its own reading, and
the skill that asks for it names the consequence in its own closing clause
(`.claude/skills/etalon-step-corpus/SKILL.md:30-35`):

> Where a rule does not reach, leave the field empty; an inferred value here is
> indistinguishable from a measured one later, which is the failure this project has a
> vocabulary to avoid.

A status column turns that from something a reader may discover into something the
conventions state. It is layer 2 of `HARDENING_CRITERION.md` §2 applied to the
conventions themselves.

## 2. What was verified, and how

All searches run 2026-11-09 from the repository root over `*.py`, `*.md` and `*.json`,
excluding `asset/` (hard constraint 6) and excluding the two documents written in this
round. Evidence: `measured_here`. Each row below names the search that produced it so it
can be rerun.

### 2.1 `soundness` and `progress` are implemented nowhere

Case-insensitive `soundness` outside `asset/` returns **two** lines, in full:

```
CLAUDE.md:6:- `soundness` ∈ `sound` | `unsound_recoverable` | `unsound_terminal`
.claude/skills/etalon-step-corpus/SKILL.md:30:Soundness and progress are separate fields. A step can be unsound and repaired
```

`unsound_recoverable` and `unsound_terminal` return one line each: `CLAUDE.md:6`.
`no_progress` returns one line outside `asset/`: `CLAUDE.md:7`. The only `asset/` hit is
`asset/prism/prism/fep/analysis/cli.py:324`, a `--no-progress` command-line flag unrelated
to the enum. `unsound` over `src/`, `tests/` and `.claude/` (other than the prose above)
returns nothing.

So: **`soundness` and `progress` are defined in `CLAUDE.md` lines 6-7 and implemented
nowhere in the repository outside `asset/`.** No field, no enum, no validator, no schema,
no test. Their only operational existence is the prose instruction at
`.claude/skills/etalon-step-corpus/SKILL.md:30-35` telling the host to fill them. This
reproduces the architecture review's finding (`etalon-architecture-review.md:126-135`)
from an independent search.

Two of the five fixed vocabularies are therefore enforced at exactly the level
`docs/adr/0006` found insufficient (`README.md:446`).

### 2.2 The `regressed` collision

`learn/acquire.py:10` and `learn/__init__.py:12` use `regressed` for statistical regression
toward the conditional mean — *"it regressed an unseen chemotype to the panel mean"* — a
claim about a surrogate's behaviour on held-out chemotypes. `progress = regressed` would be
a claim that a research step moved backwards. Two different assertions, one token, and the
existing one is load-bearing in a module docstring that explains an ADR-backed design
choice. Whoever implements the vocabulary should expect the collision
(`etalon-architecture-review.md:148-151`).

### 2.3 Three further collisions, not previously recorded

Found while verifying §2.1; each is a token the conventions fix and the source already
spends on something else.

- **`precision`.** `CLAUDE.md:8` requires saying `precision` when the claim is about
  repeatability. In `src/etalon` the word means Bayesian precision, i.e. inverse variance
  (`active/protocol_score.py:202,248,254`), and floating-point precision
  (`active/knowledge.py:23,74`). Seven occurrences, none about repeatability.
- **`validity`.** `CLAUDE.md:8` requires saying `validity` when the claim is about
  agreement with a measured quantity. In `src/etalon` it overwhelmingly means structural or
  physical validity of a pose (`research/pose_selection.py:49`, `research/pose_verifier.py:38`,
  `research/pose_pool.py:137`), and `research/result_semantics.py:170` explicitly disclaims
  the other reading: *"This is not a scientific validity or adoption assessment."* Fifty
  occurrences.
- **`diagnostic` / `independent_validation`.** Two fields share these tokens and are about
  different subjects. `Artifact.role` ∈ {`diagnostic`, `independent_validation`,
  `sealed_holdout`} (`research/schema.py:31,47-48`) is about **bytes**. `MethodEvaluation.assessment_role`
  ∈ {`diagnostic`, `independent_validation`} (`research/schema.py:285,297`) is about a
  **claim**. They are related — `journal.py:252-254` requires the artifact roles when the
  assessment role is `independent_validation` — but they are not the same field, and
  `sealed_holdout` has no counterpart on the claim side. `ASSESSMENT_REGIMES.md` depends on
  the distinction, so it is recorded here rather than left to be rediscovered.

- **`progress` and `advanced`, the bare terms.** §2.1's searches were run on `soundness`,
  `unsound_*` and `no_progress` and never on the bare vocabulary terms, so the weakest
  collision (`regressed`, §2.2) was recorded while the strongest were missed. `progress`
  is a dataclass field at `boundary/screen.py:178` (`progress: dict[str, Any]`), a method
  at `boundary/screen.py:677` and `research/handoff.py:216`, a keyword at
  `boundary/screen.py:670`, `research/handoff.py:219` and `mcp/sweep.py:536`, a dict key
  at `screening.py:132`, and **a CLI subcommand literally named `progress`** at
  `research/cli.py:62,242` — ten sites, about how far a screen or a backup has got.
  `advanced`, one of `progress`'s three values, is already a returned string at
  `research/entry.py:114`, meaning the checkpoint moved on. So two of that vocabulary's
  three values are occupied before it is implemented. The §4 status stays `prose only`:
  none of these is the three-value vocabulary arriving. Whether one of them *is* that
  vocabulary arriving is the owner's reading, not this document's.
- **`validity`, three further sites in files §2.3 did not name.** `active/policy.py:82,84`
  uses `validity` for a Laplace-smoothed admitted rate — a **third** meaning, neither
  pose validity nor agreement with a measured quantity — and `economics/stage.py:100` has
  `VALIDITY = "validity"`, an `Answers` enum member carrying the pose reading. With
  `precision` at seven sites and `validity` at fifty-three across three meanings, the
  `CLAUDE.md:8` convention that a claim must say which of the two it is collides with the
  source wherever it would be written down.

A fourth is already recorded elsewhere and is cited rather than restated: `research_trace`
has an `admission` phase whose states (`accepted` / `rejected` / `partial` / `awaiting`)
are a different vocabulary from `Admission`, and mapping one onto the other would conflate
two terms the conventions keep fixed (`ADMISSION_PROPAGATION.md` §0.4).

### 2.4 The terms that are implemented

- **`admission`** is implemented and load-bearing. `Admission` is a `StrEnum` at
  `learn/admissible.py:72` with values `admitted`, `admitted_under_waiver`, `withheld`;
  `Admission` appears at 29 sites in `src/etalon`.
- **`relied_on` / `used`** are implemented and load-bearing, **but only in the derived
  view**. `graph_memory.EDGES` is `{"flow", "depends_on", "derived_from", "supports",
  "refutes", "tests", "supersedes", "skipped_because"}` (`research/graph_memory.py:25-26`)
  and contains neither token. They exist as `premise_class` values computed by
  `learn/admission_view.py::_classify` (`:84-110`) and consumed by propagation. So the
  distinction is real, is enforced, and is **not recorded at emission** — which is why
  `.claude/skills/etalon-recomputability-audit/SKILL.md:31-36` treats classifying old edges
  as the expensive class of a rule change.
- **Evidence provenance** (`measured_here` / `measured_in_an_asset` / `literature` /
  `convention`) is implemented as `Evidence(StrEnum)` at `faults/taxonomy.py:66`, used at
  34 sites in `src/etalon`.
- **`completion` and `verification`** are implemented as structure under other field names,
  which is a weaker status than `admission` and stronger than prose. Completion is carried
  by `Evaluation.status` ∈ {`ok`, `failed`, `invalid`, `blocked`}
  (`active/schema.py:140`) and by `"scientific_status": "not_inferred_from_exit_code"`
  (`runtime/native.py:416`). Verification is carried by the fault layer's
  `fired` / `evaluable` observations and the `blocking` / `unchecked` lists of a `Ruling`,
  and declaratively by `evaluation_contract.STATUSES` = `{criteria_passed, criteria_failed,
  insufficient, incomparable}` (`research/evaluation_contract.py:23`). **That mapping is
  this document's reading of field semantics, evidence class `convention`, not a
  measurement** — neither word is an identifier *of this concept* in `src/etalon`.
  An earlier revision of this line claimed the stronger thing, that neither word is an
  identifier at all. That is true of `completion` (zero code-token sites) and **false of
  `verification`**, which has 76: a record field at `boundary/native_result.py:71` and
  `boundary/runtime_profile.py:416,454`, `host_install.py:105` (`verification =
  adapter.verify(root)`, host-installation verification), and further sites in
  `data/design.py` and `generate/route.py`. The status is unaffected, because an occupied
  word is not an implementation of the fixed concept — that distinction is what this
  column exists for — but the occupation is a hazard of the same kind §2.3 records, and
  the absolute claim was itself a document asserting what the code contradicts.

## 3. The reason a status column is enough

`HARDENING_CRITERION.md` §2 question 2: the mistake here — a reader taking `soundness` for
a vocabulary the system computes — is distinguishable from the truth by anyone who runs the
search in §2.1, and invisible to anyone who does not. That is layer 2. Writing the status
down discharges it. Implementing or deleting the two terms is a different and larger
decision, and marking them as hazards does not pre-empt it in either direction.

Per hard constraint 7, a term whose status could not be determined would be reported as
not taken. None were: every row in §4 has a search behind it.

## 4. The block to merge

Proposed as a new subsection of `CLAUDE.md`'s 固定术语 section, after line 8. Terms are
listed in the order `CLAUDE.md:4-8` gives them. The statuses are:
`implemented` (an enum or validated field exists and is consumed),
`implemented as structure` (the fact is carried, under another field name),
`derived only` (computed in an export view, not recorded at emission),
`prose only` (**a declared hazard, not a vocabulary**).

```markdown
### 固定术语的实现状态(2026-11-09 核查,不含 `asset/`)

| 术语 | 定义处 | 实现状态 | 实现位置 / 危险 |
| --- | --- | --- | --- |
| `completion` | CLAUDE.md:4 | implemented as structure | `active/schema.py:140` 的 `Evaluation.status`;`runtime/native.py:416`。术语不是本概念的标识符(`completion` 零处;`verification` 另有 76 处他义,见 §2.4);字段对应关系是约定(convention),不是实测 |
| `verification` | CLAUDE.md:4 | implemented as structure | `Ruling` 的 `blocking`/`unchecked`;`research/evaluation_contract.py:23` 的 `STATUSES`。同上,术语不是本概念的标识符;`verification` 被 host 安装验证等占用 76 处,见 §2.4 |
| `admission` | CLAUDE.md:4 | implemented | `learn/admissible.py:72` 的 `Admission`;`src/etalon` 内 29 处 |
| `relied_on` / `used` | CLAUDE.md:5 | derived only | `learn/admission_view.py:84-110` 的 `premise_class`。**`graph_memory.EDGES`(`:25-26`)不含这两个词** —— 该区分在发射时不被记录,只在导出视图里计算 |
| `soundness` ∈ `sound` \| `unsound_recoverable` \| `unsound_terminal` | CLAUDE.md:6 | **prose only — 已声明的危险** | 仓库内(不含 `asset/`)只有 CLAUDE.md:6 的定义本身,以及 `.claude/skills/etalon-step-corpus/SKILL.md:30-35` 要求宿主填写的一段文字。无字段、无枚举、无校验、无 schema、无测试 |
| `progress` ∈ `advanced` \| `no_progress` \| `regressed` | CLAUDE.md:7 | **prose only — 已声明的危险** | 同上。另有命名冲突:`learn/acquire.py:10` 与 `learn/__init__.py:12` 的 `regressed` 指向条件均值的统计回归,不是本枚举值 |
| Evidence 来源 `measured_here` / `measured_in_an_asset` / `literature` / `convention` | CLAUDE.md:15 | implemented | `faults/taxonomy.py:66` 的 `Evidence`;`src/etalon` 内 34 处 |
| `precision`(重复性)/ `validity`(与实测相关) | CLAUDE.md:8 | 报告用语,无字段 | 两词在 `src/etalon` 已被占用:`precision` 指贝叶斯精度与浮点精度(`active/protocol_score.py:202`、`active/knowledge.py:23`);`validity` 指姿势的结构/物理有效性(`research/pose_verifier.py:38`),且 `research/result_semantics.py:170` 明确否认另一读法 |

**prose only 的含义:**一个只以"请宿主填写"存在的术语是一个已声明的危险,不是一个词汇表 ——
按 `etalon-step-corpus/SKILL.md:30-35` 自己的说法,此处填入的推断值"later 与实测值不可区分"。
是否实现或删除 `soundness` 与 `progress` 是负责人的决定,本表不作此决定,只记录状态并点名危险。

另外两处术语占用,实现前应预期:`Artifact.role`(关于字节,含 `sealed_holdout`,
`research/schema.py:31,47-48`)与 `MethodEvaluation.assessment_role`(关于主张,
`:285,297`)共用 `diagnostic` / `independent_validation` 两个词但不是同一字段;
`research_trace` 的 `admission` 阶段状态是另一套词汇(见 `ADMISSION_PROPAGATION.md` §0.4)。
```

## 5. What this proposal leaves to the repo owner

1. Whether `soundness` and `progress` become derived fields, or are withdrawn from the
   fixed vocabulary. If the second, the step-corpus skill's text should say the fields are
   host judgements, so a later reader cannot mistake one for a derived value
   (`etalon-architecture-review.md:612-616`). Either way the status column above stays
   correct until the decision lands.
2. Whether to merge this block into `CLAUDE.md` at all, or keep it as a separate
   conventions appendix. The block is written to be pasted; nothing depends on where it
   lands.
3. Whether the `precision` / `validity` occupations in §2.3 are worth renaming. They are
   recorded as a hazard, not proposed as a change — renaming load-bearing identifiers to
   free up words for a reporting convention is a cost this document is not arguing for.

---

## 6. The decision, 2026-11-10: withdrawal, and no derived replacement

`soundness` and `progress` are withdrawn from `CLAUDE.md`'s fixed terminology, together
with the clause mandating the tokens `precision` and `validity`. The discipline behind that
clause is kept in a form the source does not contradict: say whether a claim is about
repeatability or about agreement with a measured quantity, without fixing which word
carries it.

### 6.1 Why withdrawal rather than implementation

A term that exists only as an instruction to fill a field is not a vocabulary. It is a
**manufactured indistinguishability**: the host supplies a value from its own reading, and
`.claude/skills/etalon-step-corpus/SKILL.md` said in its own closing clause that such a
value is indistinguishable from a measured one later. The repository was asking, in
writing, for the failure `admission` exists to prevent. Of the three available moves —
implement, withdraw, leave as is — *leave as is* was the only one that violated the first
principle directly, so the choice was never between three.

Implementation was refused on evidence, not on cost. The cost was real (§2.3: `progress` is
occupied at ten sites including a dataclass field at `boundary/screen.py:178` and a CLI
subcommand at `research/cli.py:62`; `advanced` is already a returned string at
`research/entry.py:114`; `regressed` is load-bearing in `learn/acquire.py:10`), but the
decisive argument is that **the fact the field would carry is already carried, and carried
better.** Both halves were checked against the code rather than assumed:

- `soundness`. `Ruling` (`learn/admissible.py:109`) separates `blocking` (fired, unwaived,
  about the wrong subject), `waived`, `bounded` (about the right thing, off by the band),
  `unverifiable` (no claim about the run can be checked) and `unchecked` (could not be
  evaluated), alongside `admission` ∈ {`admitted`, `admitted_under_waiver`, `withheld`}.
  Each fault carries a `Consequence` ∈ {`WRONG_SUBJECT`, `WRONG_SIZE`, `UNVERIFIABLE`}.
  A three-value summary over that is **lossy re-presentation**, and the argument against it
  is already written in this repository, in `Consequence`'s own docstring: *"The band and
  the consequence are different questions, and one field cannot answer both."* A summary
  invites a reader to use the summary and lose the partition.
- `progress`. The token's three values do not describe one subject. `advanced` at
  `research/entry.py:114` means a checkpoint moved on — entry freshness, not research
  progress — and `regressed` in `learn/acquire.py:10` means a surrogate regressed an unseen
  chemotype toward the panel mean. The baseline machinery
  (`research/retained_baseline.py`, `research/baseline_feedback.py`) computes against a
  retained baseline, which is a comparison between two evaluations and not a verdict on a
  step. There is no single quantity for a derived `progress` to be derived from.

So an earlier sketch of this decision — withdraw the vocabulary status and re-deliver both
as ETALON-derived response fields — is **not** what landed. Withdrawing was right; the
re-delivery would have added a fourth field answering a question two existing ones answer
more precisely. Recorded here because the sketch is the plausible wrong move and a later
reader will reach for it.

### 6.2 What is genuinely missing, and why it is not done here

The one fact neither `Ruling` nor `Consequence` carries as data is whether a particular
fault is **repairable or terminal**. Today it lives in each fault's `remedy`, as prose, and
deliberately so: *"Deliberately not 'fix it automatically': several of these are decisions
with scientific content"* (`faults/taxonomy.py`).

The right shape for it is the inversion this round named: **each fault declares its own
recoverability**, rather than a summary field enumerating which codes are terminal. That is
the template `assessment_role` used — required, with no default.

It is not done in this change because the fault catalogue is **Zone C**: it defines what
counts as a result. A Zone-C edit is the owner's deliberate act, not something folded into a
terminology cleanup, and doing it here would make this change exactly the kind of quiet
boundary crossing the zoning exists to surface.

### 6.3 Status after the decision

The §4 table's rows for these three terms are superseded. `CLAUDE.md` no longer fixes them,
so they no longer need a status column; what they need is a check that the withdrawal held.

The status that replaced `prose only` is **`refused at a write`**, and it is a stronger
claim than `prose only` was. Before, these names were fixed by the conventions, implemented
nowhere, and therefore writable by any host that read the instruction. Now each exists in
source in exactly one place, whose only purpose is to refuse it.

| 术语 | 2026-11-10 后的状态 | 持有该状态的检查 |
| --- | --- | --- |
| `soundness` | **refused at a write** — 不是固定术语,不是字段;写入 `bindings` 时被拒绝 | `test_reserved_bindings.py`;文档一致性 `test_normative_consistency.py` J4 |
| `progress` | **refused at a write** — 同上。`progress` 作为 CLI 子命令、screen 字段等既有用法不受影响,被拒的只是记录字段名 | 同上 |
| `precision` / `validity` | **withdrawn as a token mandate** — 纪律保留,强制用词取消。**没有**进拒绝注册表:本来就没有任何东西会计算它,所以没有字段可拒,这是一条报告约定的变更,正是文档可以承担的那类事 | `test_normative_consistency.py` J4 |

The remaining rows of §4 are unaffected: `completion` and `verification` stay
`implemented as structure`, `admission` stays `implemented`, `relied_on` / `used` stay
`derived only`, Evidence provenance stays `implemented` — and as of this round it is
required on an evaluation contract's threshold too
(`research/evaluation_contract.py`, one `PROVENANCE` definition shared with
`research/decision_rule.py`).

### 6.4 Where the withdrawal is enforced, and the wrong answer that came first

Withdrawal is checkable in a way implementation is not, and the check is deliberately not
"the word is absent from the repository". The words stay: `progress` is a CLI subcommand at
`research/cli.py:62`, a dataclass field at `boundary/screen.py:178` and a backup callback at
`research/handoff.py:216`; `validity` is a pose property; this document discusses all of
them. A check over every occurrence would fail on correct code and would be asserting a
vocabulary monopoly nobody decided.

**The first attempt got the layer wrong, and it is worth recording because the error is the
one this whole round is about.** The hazard was identified as *the instruction to supply a
value* — `.claude/skills/etalon-step-corpus/SKILL.md` telling the host to fill both fields
"from rules over the fault codes" — and the check written for it was a regular expression
hunting imperatives across 28 skill files. That is **prose policing prose**, and §6.1's own
argument says why it cannot work: prose-as-discipline is the mechanism this round measured
as ineffective. The probe behaved accordingly. It silently matched nothing twice:

1. first because the real instruction put verb and term four sentences apart — *"Soundness
   and progress are separate fields. … Fill them from rules over the fault codes"* — while
   the pattern required them in one sentence;
2. then because a paragraph-wide negation check was cancelled by *"one field cannot hold
   both"*, three sentences before the directive.

A probe that matches nothing is indistinguishable from a repository with no hazard. Tuning
the pattern a third time would have produced a slightly better prose detector and no
enforcement.

**The question re-asked at the right layer: why can a field that does not exist be written
at all?** Measured before anything was built (2026-11-10, throwaway campaign; Evidence
`measured_here`):

| slot | written? |
| --- | --- |
| `Artifact(bindings={"soundness": "sound", "progress": "advanced"})` | **written and read back intact** |
| `record_json` payload containing `soundness` | written to disk intact |
| `MethodEvaluation(..., soundness="sound")` | already refused — `TypeError` |

So the hole was the free-form slot that is *also* where ETALON's own annotations live:
`capability_attribution.KEY` calls `bindings` *the reserved bindings key*. A key there is
read later as ETALON's, which is exactly what makes a host-supplied value indistinguishable
from a computed one.

`src/etalon/research/reserved_bindings.py` is the enforcement. It refuses, at
`Artifact.__post_init__` and `Experiment.__post_init__`:

- a **withdrawn** name — nothing computes it, so any value is a judgement wearing a field's
  name. The refusal message names where the fact actually lives (`Ruling` and `Consequence`
  for soundness, a retained-baseline comparison for progress) and says a name of the host's
  own is legal, because a refusal a host cannot act on is a wall;
- a **reserved and in use** name carrying the wrong shape — a malformed `produced_by` would
  read afterwards as ETALON's own output. ETALON's own write passes through the same gate.

By the hardening criterion this is the cheap kind of refusal: it fails in the same session,
visibly, and nothing legitimate writes those keys (verified — the only `bindings` hit on
either word in the repository is a *value*, `as_of_progress_not_live_heartbeat` in
`examples/research_closeout.py`, and matching values rather than keys would have refused a
correct record today).

**Deliberate boundary, stated rather than hidden:** the registry does not police a record's
*payload*. A payload is the caller's own document, its schema is the caller's, and `progress`
in one may legitimately mean how far a screen got. Payloads that claim to be ETALON records
carry `schema` and go through typed validation instead — and no ETALON code reads
`payload["soundness"]`, so nothing would present it as ETALON's output. The line is: ETALON
refuses what it would be read as having produced.

So the checks now are:

1. `tests/test_reserved_bindings.py` — the hazard, against a real journal, with the measured
   hole as a regression test and the free-form guarantee held beside it.
2. `tests/test_normative_consistency.py` J4 — document/source agreement only, which is what
   a document-level test can honestly hold: the conventions name the same terms the source
   registry refuses, and neither is the authority alone.

The regex probe was deleted, not demoted. A second prose check kept "for defence in depth"
would be the same mistake with a smaller font.
