"""The gate check ``etalon_screen_submit`` did not have, at the boundary a model actually drives.

``docs/adr/0006`` is written in the past tense and its class was still open here. ``etalon_sweep_emit``
takes ``gate_json``, refuses without it, and reports which of ``require_gate``'s three causes fired.
``etalon_screen_submit`` -- the other SPENDS tool that applies a compiled funnel to a library the
caller supplies -- took ``config_path, workspace, run_id, plan_id, library_path, workers, devices,
allow_copyleft, delivery`` and no authorization object of any kind. ``plan_id`` is
``expected_plan_id``: a change-detection check, which refuses a config that moved since it was
inspected and says nothing about whether the thresholds in it were ever tested on a known binder.

``etalon_sweep_record``'s own docstring already names the hole from the inside:

    ``MolCascadeProcessScreening`` compiles the current config against a fixed reference library
    before every batch and refuses to run one whose funnel is not the campaign's -- a Python driver
    an MCP caller never touches. So an agent screening through ``etalon_screen_submit`` has no
    revision check at all, and believing one is running is worse than knowing there is none.

``authority/gate.py``'s table says what that costs in this regime: not a wasted GPU-hour but *"a
miscalibrated gate deleting the interesting chemistry, silently, a million times"*, whose cost of
error is *"an empty shortlist and no way to see why"*. Measured there: MolCascade's shipped docking
thresholds reject all eight molecules of the SND1 panel including both co-crystal ligands, while
every log line reads SUCCEEDED.

That is why this is hardened code and not an in-session hook. An empty shortlist produced by an
untested threshold is indistinguishable, afterwards, from an empty shortlist produced by a library
with nothing in it; the record keeps no trace of which. A mistake that is invisible in its own
record is the class the criterion assigns to code.

**What this module does not claim.** The architecture review proposes refusing *"when the config
declares gates whose calibration is recorded"*. The second half of that condition is not answerable
from here and is reported as not taken rather than guessed, per hard constraint 7: there is no
calibration store. A ``Calibration`` is derived on demand from a finished panel run plus a roster of
:class:`~etalon.campaign.calibrate.PanelMember` rows that is a caller argument every time and lives
nowhere on disk, so "has this revision been calibrated in this workspace" has no answer to read.
What is answerable, cheaply and by construction, is whether the compiled funnel declares a gate at
all -- and that is the condition this module enforces.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from etalon.authority.gate import GateAuthorization

#: Suffix MolCascade's lowering gives a criterion's threshold stage. A criterion compiles to a stage
#: of its own name and, where it has a threshold, a ``__gate`` beside it --
#: ``campaign/calibrate.py`` reads committed runs by exactly this convention, which is why the
#: detection below is a scan of compiled stage ids rather than a walk of the configuration model.
#:
#: Scanning the compiled pipeline rather than the cascade is deliberate and is the difference
#: between a guard and an almost-guard: a flat pipeline has no ``cascade`` object and therefore no
#: criteria to walk, and a gate declared in one would have been invisible to a configuration-model
#: check while still deleting molecules at scale.
GATE_STAGE_SUFFIX = "__gate"


def declared_gates(plan: Any) -> tuple[tuple[str, ...], str]:
    """Gate stages in a compiled funnel, and the basis on which they were counted.

    Returns the stage ids and a basis string. When the compiled pipeline cannot be read in the
    shape this scan expects, the gates are reported as ``not_taken`` -- and :func:`require`
    then refuses rather than proceeding, because an unreadable funnel is precisely the case in which
    the absence of a gate cannot be established.

    Nothing is executed. ``Screen.plan`` is a compile: ``etalon_screen_plan`` is classified CHEAP
    for that reason.
    """

    internal = getattr(plan, "_internal", None)
    if not isinstance(internal, dict) or "pipeline" not in internal:
        return (), "not_taken: the compiled plan carries no pipeline to scan"
    try:
        raw = internal["pipeline"].model_dump(mode="json")
        stages = raw["stages"]
        ids = tuple(
            str(stage["id"]) for stage in stages if str(stage.get("id", "")).endswith(GATE_STAGE_SUFFIX)
        )
    except Exception as error:  # noqa: BLE001 -- the reason is reported, never swallowed into ()
        return (), f"not_taken: compiled pipeline could not be scanned ({type(error).__name__})"
    return ids, f"measured_here: compiled stage ids ending {GATE_STAGE_SUFFIX!r}, over {len(stages)} stages"


def token_from_json(gate_json: str) -> GateAuthorization | None:
    """Rebuild a :class:`~etalon.authority.gate.GateAuthorization` from the tool argument.

    The same construction ``mcp/sweep.py`` does for ``etalon_sweep_emit``, which had it inline and
    was the only copy. A token whose fields have been edited does not verify -- the signature covers
    every one of them -- so this is a parse rather than a trust decision, and
    :func:`~etalon.authority.gate.require_gate` is what rules on it.
    """

    import json

    from etalon.authority.gate import GateAuthorization

    if not gate_json.strip():
        return None
    payload = json.loads(gate_json)
    if not isinstance(payload, dict):
        raise ValueError(
            "gate_json must be the `gate` object etalon_authorize_gates returned, passed verbatim"
        )
    return GateAuthorization(
        revision_id=str(payload["revision_id"]),
        calibration_sha256=str(payload["calibration_sha256"]),
        infrastructure_sha256=str(payload.get("infrastructure_sha256", "")),
        panel_size=int(payload["panel_size"]),
        actives=int(payload["actives"]),
        recall=float(payload["recall"]),
        rankable_engines=tuple(payload.get("rankable_engines", ())),
        unchecked=tuple(payload.get("unchecked", ())),
        issued_at=str(payload["issued_at"]),
        expires_at=str(payload["expires_at"]),
        signature=str(payload["signature"]),
    )


def require(
    *,
    config_path: Path,
    workspace: Path,
    library_path: Path | None,
    allow_copyleft: bool,
    gate_json: str,
    gate_reference_library: Path | None,
) -> dict[str, Any]:
    """Refuse a gated screen with no authorization for its funnel, or report why none is needed.

    Order matters and is the cheapest-first order the rest of the repository uses: compile, scan for
    gates, and only then ask for a token. A cascade with no threshold in it needs no calibration and
    is not asked for one, because a guard that refuses work it has no argument against is a guard
    hosts route around.

    Returns a ``gate_check`` block for the response.

    Raises:
        NotAuthorized: From :func:`~etalon.authority.gate.require_gate`, with that function's three
            distinct messages, or from here when a gated funnel arrives with no token at all. The
            MCP boundary already classifies ``NotAuthorized`` as non-retryable and attaches the
            gate remedy (``mcp/_common.py``'s refusal intercept), so this deliberately does not
            catch it: none of its causes is fixed by calling again.
        ValueError: When a token is supplied without the reference library its revision must be
            compared against. That is not a refusal about science; it is an argument that cannot do
            what the caller intends, and saying so is better than comparing against a revision that
            can never match.
    """

    from etalon.authority.gate import require_gate
    from etalon.authority.grant import NotAuthorized
    from etalon.boundary.screen import Screen

    screen = Screen(workspace, allow_copyleft=allow_copyleft)
    submitted = screen.plan(config_path, library_path)
    gates, basis = declared_gates(submitted)
    token = token_from_json(gate_json)

    if not gates and basis.startswith("measured_here"):
        return {
            "authorization_required": False,
            "declared_gate_stages": [],
            "declared_gate_basis": basis,
            "submitted_revision_id": submitted.revision_id,
            "calibration_recorded": "not_taken",
            "calibration_recorded_basis": (
                "no calibration store exists: a Calibration is derived on demand from a panel run "
                "plus a panel roster supplied by the caller, so whether this revision was ever "
                "calibrated has no record to read"
            ),
            "token_supplied": token is not None,
            "note": (
                "This funnel compiles to no threshold stage, so there is no gate for a panel to "
                "have tested and none is required. A later edit that adds one changes plan_id, so "
                "it arrives through a new plan rather than through this run."
            ),
        }

    if token is None:
        raise NotAuthorized(
            f"this cascade compiles to {len(gates) or 'an unreadable number of'} gate stage(s) "
            f"({', '.join(gates[:4]) or basis}) and no gate authorization was supplied. A "
            "threshold nobody screened a known-active panel through is an untested claim applied "
            "to every molecule in the library, and MolCascade's shipped docking defaults delete "
            "all eight members of the SND1 panel including both co-crystal ligands while every log "
            "line reads SUCCEEDED. Screen the panel through this cascade, call "
            "etalon_calibrate_gates to read what the gates did to it, then etalon_authorize_gates, "
            "and pass the returned gate object verbatim as gate_json together with "
            "gate_reference_library set to the panel's library."
        )

    if gate_reference_library is None:
        raise ValueError(
            "gate_json was supplied without gate_reference_library, and the comparison cannot be "
            "made without it. A compiled revision covers the library as well as the funnel, so "
            "this batch's own revision can never equal the one the panel produced -- measured, "
            "five batches of one campaign compiled to five revisions from one unchanged config "
            "file. Pass the calibration panel's library as gate_reference_library; it is excluded "
            "from the plan request, so it does not move plan_id."
        )

    reference = screen.plan(config_path, gate_reference_library)
    require_gate(token, reference.revision_id)
    return {
        "authorization_required": True,
        "declared_gate_stages": list(gates),
        "declared_gate_basis": basis,
        "submitted_revision_id": submitted.revision_id,
        "gate_revision_id": reference.revision_id,
        "gate_reference_library": str(gate_reference_library),
        "calibration_recorded": "not_taken",
        "calibration_recorded_basis": (
            "no calibration store exists; the token's calibration_sha256 is the digest of the "
            "verdict that minted it and is the only recorded link to a panel"
        ),
        "calibration_sha256": token.calibration_sha256,
        "panel_size": token.panel_size,
        "actives": token.actives,
        "recall": token.recall,
        "rankable_engines": list(token.rankable_engines),
        "token_unchecked": list(token.unchecked),
        "expires_at": token.expires_at,
        "reading": (
            "A token over an unevaluated check authorises a screen; it does not assert the check "
            "passed. Read token_unchecked: SCORE_NOT_SHOWN_TO_RANK means the shortlist's score "
            "column is a filter and not a ranking, and ENGINE_IDENTITY_UNRECORDED means nobody "
            "recorded which engine the panel ran on."
        ),
    }


__all__ = ["GATE_STAGE_SUFFIX", "declared_gates", "require", "token_from_json"]
