"""A field ETALON does not compute cannot be written into a record.

This file replaces a mistake worth recording. The hazard it holds was first addressed with a
regular expression that hunted fill-instructions across 28 skill files -- prose policing
prose, which is the mechanism this same round measured as ineffective
(`FIXED_TERMINOLOGY_STATUS.md` §6.4). That probe matched nothing twice while the hazard
stood: once because the real instruction put verb and term four sentences apart, once
because a paragraph-wide negation check was cancelled by an unrelated "cannot" earlier in
the paragraph. Tuning the pattern a third time would have been the wrong move; the
instrument was wrong.

Re-asked at the right layer -- *why can a field that does not exist be written at all?* --
the answer was measured before anything was built (2026-11-10, throwaway campaign, Evidence
`measured_here`):

* `Artifact(bindings={"soundness": "sound", "progress": "advanced"})` was written to the
  journal and read back intact.
* `MethodEvaluation(..., soundness="sound")` already raised `TypeError`, because a typed
  record with fixed fields was never exposed.

So the hole was exactly the free-form slot that is also where ETALON's own annotations live,
and the refusal belongs there. `test_a_withdrawn_name_in_bindings_is_refused_at_the_write`
is that measurement turned into a regression test.
"""
from __future__ import annotations

import pytest

from etalon.research.reserved_bindings import (
    IN_USE,
    WITHDRAWN,
    ReservedBindingError,
    validate_bindings,
)


@pytest.fixture
def journal(tmp_path):
    from etalon.active.schema import CampaignSpec, Endpoint
    from etalon.active.store import CampaignStore
    from etalon.research.journal import ResearchJournal

    store = CampaignStore(tmp_path / "campaign.sqlite")
    store.configure(CampaignSpec("reserved", 0, "wall_second", "reserved-fixture"),
                    [Endpoint("reserved", "fixture", "unmeasured", "count", "fixture/1", 0,
                              queryable=False)])
    return ResearchJournal(store)


def _artifact(tmp_path, **over):
    from etalon.boundary.prism_v1 import file_identity
    from etalon.research.schema import Artifact

    path = tmp_path / "evidence.txt"
    path.write_text("reserved-bindings fixture")
    fields = dict(source_kind="fixture", role="diagnostic", bindings={})
    fields.update(over)
    return Artifact(str(path), **file_identity(path), **fields)


# -- the measured hole, closed -------------------------------------------------------------


@pytest.mark.parametrize("term", sorted(WITHDRAWN))
def test_a_withdrawn_name_in_bindings_is_refused_at_the_write(tmp_path, term):
    """The regression test for the hole as it was measured, one term at a time."""

    with pytest.raises(ReservedBindingError) as refused:
        _artifact(tmp_path, bindings={term: "a value the host decided"})
    assert term in str(refused.value)


def test_the_hole_as_measured_is_closed(tmp_path, journal):
    """The exact call that was written and read back intact on 2026-11-10."""

    with pytest.raises(ReservedBindingError):
        journal.record(_artifact(tmp_path, bindings={"soundness": "sound",
                                                     "progress": "advanced"}))


def test_the_refusal_says_what_to_do_instead(tmp_path):
    """A refusal a host cannot act on is a wall. These name where the fact already lives.

    The host is good at design judgement and bad at knowing an unstated rule, so the message
    carries the rule: `soundness` is in the ruling, `progress` is a comparison against a
    retained baseline, and either may be recorded under a name of the host's own.
    """

    messages = {}
    for term in WITHDRAWN:
        with pytest.raises(ReservedBindingError) as refused:
            _artifact(tmp_path, bindings={term: "x"})
        messages[term] = str(refused.value)

    assert "Ruling" in messages["soundness"] and "Consequence" in messages["soundness"]
    assert "retained baseline" in messages["progress"]
    for text in messages.values():
        assert "FIXED_TERMINOLOGY_STATUS.md §6" in text, "the decision must be findable"
        assert "name of your own" in text, "a refusal must leave a legal route"


def test_a_typed_record_was_never_exposed_and_still_is_not():
    """The other half of the measurement, kept so the asymmetry stays visible.

    `MethodEvaluation` has fixed fields, so it refused this before anything was built. That
    is why the repair went to `bindings` and not to every record type: the typed records were
    never the hole, and hardening them again would be a mechanism with no subjects.
    """

    from etalon.research.schema import MethodEvaluation

    with pytest.raises(TypeError):
        MethodEvaluation(subjects=("a",), comparators=("b",), protocol_ref="p",
                         task_split_ref="t", initial_conditions_ref="i", result_refs=("r",),
                         accounting_refs=(), assessment_role="diagnostic", conclusion="c",
                         scope="s", soundness="sound")


# -- what must keep working ----------------------------------------------------------------


def test_bindings_stay_free_form_for_every_name_etalon_has_not_claimed(tmp_path, journal):
    """The refusal must not turn `bindings` into a closed schema.

    `bindings` carries exact evidence refs, a task id, a pose label, a purpose -- whatever
    its writer needs. Closing it would break the design, so what is refused is only the
    names ETALON claimed. A key that merely *contains* a withdrawn word is the caller's own.
    """

    artifact = _artifact(tmp_path, bindings={
        "kind": "r4b_retained_baseline_freeze", "task_id": "t-1", "pose_label": "p1",
        "progress_note": "two of eight candidates examined",
        "host_soundness_opinion": "looked fine",
    })
    journal.record(artifact)
    assert journal.get(artifact.id)["bindings"]["progress_note"].startswith("two of eight")


def test_a_withdrawn_word_as_a_value_is_untouched(tmp_path, journal):
    """`examples/research_closeout.py` writes `kind: as_of_progress_not_live_heartbeat`.

    Matching values rather than keys would have refused a legitimate record in the repository
    today, which is the kind of false refusal the hardening criterion's "small set" corollary
    exists to prevent.
    """

    artifact = _artifact(tmp_path, bindings={"kind": "as_of_progress_not_live_heartbeat"})
    journal.record(artifact)
    assert journal.get(artifact.id)["bindings"]["kind"].endswith("heartbeat")


def test_the_attribution_etalon_writes_itself_passes_its_own_reserved_shape(tmp_path, journal):
    """`produced_by` is reserved and in use, so the same gate validates ETALON's own write."""

    from etalon.research.capability_attribution import (
        MCP_TOOL, KEY, running_capability, with_attribution)

    with running_capability("etalon_method_criterion"):
        bindings = with_attribution({"kind": "fixture"})
    artifact = _artifact(tmp_path, bindings=bindings)
    journal.record(artifact)
    assert journal.get(artifact.id)["bindings"][KEY] == {
        "capability": "etalon_method_criterion", "basis": MCP_TOOL}


@pytest.mark.parametrize("malformed", [
    {"capability": "x"},                      # no basis
    {"capability": "", "basis": "declared"},  # empty name
    {"capability": "x", "basis": "guessed"},  # basis outside BASES
    {"capability": "x", "basis": "declared", "extra": 1},
    "etalon_method_criterion",                # not a block at all
])
def test_a_malformed_reserved_block_is_refused_rather_than_stored(tmp_path, malformed):
    """A reserved name with the wrong shape reads afterwards as ETALON's own output.

    This is the second class the registry holds, and it is a different harm from a withdrawn
    name: nothing is missing, something is *wearing* a field ETALON does write.
    """

    from etalon.research.capability_attribution import KEY

    with pytest.raises(ReservedBindingError, match="malformed"):
        _artifact(tmp_path, bindings={KEY: malformed})


def test_every_reserved_name_in_use_is_one_etalon_actually_writes():
    """A reserved list that outgrows what is written becomes a vocabulary monopoly.

    So each `IN_USE` entry must name a key something in `src/etalon` actually produces, which
    keeps the claimed set tied to the implemented one rather than to intentions.
    """

    from etalon.research import capability_attribution

    assert set(IN_USE) == {capability_attribution.KEY}
    validator, description = IN_USE[capability_attribution.KEY]
    assert validator(capability_attribution.attribution("x", basis="declared"))
    assert validator(capability_attribution.attribution(None))
    assert description.strip()


def test_validate_bindings_leaves_a_non_mapping_to_its_owner(tmp_path):
    """One job. Two validators disagreeing would make the error depend on import order."""

    for value in (None, [], "soundness", 7):
        validate_bindings(value, record="probe")
