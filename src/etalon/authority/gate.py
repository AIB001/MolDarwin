"""Permission to apply a gate configuration at scale, bound to the panel that tested it.

``authority/grant.py`` guards the expensive stage: a GPU-hour may not be spent on a molecule whose
geometry nobody ruled on. That guard has a precondition nobody stated -- it assumes there *is* an
expensive stage. Remove it, and every object in that module becomes inert: a screening-only campaign
has no build to authorise, so ``check_handoff``, ``authorize`` and ``require`` sit on a path nothing
takes. Measured: one 1,056,280-molecule campaign ran to completion calling none of them.

The risk did not go away. It moved.

===============  ==========================================  =====================================
                 with an expensive stage                     screening only
===============  ==========================================  =====================================
irreversible     a GPU-hour on a molecule that is a drawing  **a miscalibrated gate deleting the
act                                                          interesting chemistry, silently, a
                                                             million times**
guarded by       ``authority.grant``                         nothing, before this module
cost of error    one molecule's compute                      an empty shortlist and no way to see
                                                             why
===============  ==========================================  =====================================

That second column is not a hypothetical. MolCascade's shipped docking thresholds reject all eight
molecules of the SND1 panel, including both co-crystal ligands, and a campaign that applied them
unexamined would have produced nothing while every log line read SUCCEEDED.

So this module is ``grant.py``'s shape applied to the other regime. A configuration may not be
applied at scale until a panel has shown it does not delete known actives, and the token is bound to
a digest of the calibration *and* to the compiled ``revision_id``, so that calibrating one funnel and
screening with another is caught the way building a different row is caught.

What the guard cannot do is make itself unavoidable the way :func:`~etalon.authority.grant.require`
is. A build is one function call and can be made to demand a token; applying a gate is MolCascade
running normally, and ETALON does not own that entry point. :func:`require_gate` is therefore called
by :class:`~etalon.campaign.sweep.Sweep`, which *is* the entry point for a screening campaign at
scale -- and a campaign driven around the sweep instead of through it is a campaign whose operator
chose to skip the check, which is a different thing from a check that was never offered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Mapping

from etalon.authority.grant import NotAuthorized
from etalon.authority.subject import Signed, digest_of, require_signed, sign

if TYPE_CHECKING:  # pragma: no cover -- import cycle: calibrate reads screen, screen needs no authority
    from etalon.campaign.calibrate import Calibration

#: How long a gate authorization is good for.
#:
#: Longer than a spend token's 24 hours, and the reason is what each one describes. A spend token
#: describes a molecule's geometry as it was minutes ago; a gate authorization describes a
#: configuration, which does not drift on its own. What *can* invalidate it is a new panel member, a
#: changed engine or a rebuilt model -- and two of those three are caught by digest rather than by
#: time. Seven days is the timescale of a campaign: it comfortably covers a long run (this one took
#: 44 hours) and forces a fresh panel for the next one, which is where new evidence usually arrives.
DEFAULT_GATE_LIFETIME_HOURS = 168.0


def calibration_digest(calibration: Calibration) -> str:
    """A digest over the calibration's verdict, stable under key order.

    Taken over :meth:`~etalon.campaign.calibrate.Calibration.as_dict` rather than over the object, so
    that the thing signed is the thing a reader of the record sees. The per-molecule score table is
    excluded from that dict already -- it is evidence for arguing with the verdict, not part of it,
    and including it would make the digest change when a panel member's pose was re-docked to the
    same conclusion.
    """

    return digest_of(calibration.as_dict())


def _provenance_digest(provenance: Mapping[str, Any] | None) -> str:
    """Digest of the infrastructure record, or empty when none was supplied.

    Empty is reported by :attr:`GateAuthorization.unchecked` rather than treated as clean. A
    calibration whose engine version nobody recorded is a calibration that cannot be shown to
    describe the engine now running, and "we did not look" must not read as "it is the same".
    """

    if not provenance:
        return ""
    return digest_of(dict(provenance))


@dataclass(frozen=True, slots=True)
class GateAuthorization(Signed):
    """Permission to screen at scale with one compiled funnel.

    Constructed only by :func:`authorize_gate`. Every field is in the signature, so editing one
    invalidates the token rather than producing a token for different circumstances.

    Signing, expiry and serialisation come from :class:`etalon.authority.subject.Signed`. What stays
    here is the field layout and :meth:`covers`, whose subject is a single compiled ``revision_id``
    where a spend token's is an identifier plus a content digest -- the difference that kept the two
    classes from collapsing into one.
    """

    #: The compiled funnel this permits. MolCascade's revision id, not a config path.
    revision_id: str
    #: Digest of the calibration verdict that permitted it.
    calibration_sha256: str
    #: Digest of the vendored-package provenance the panel ran on, or empty.
    infrastructure_sha256: str
    panel_size: int
    actives: int
    recall: float
    #: Engines whose score ordered the panel correctly. Usually empty on a protein-protein interface,
    #: and carried here so that a reader of a shortlist does not have to find the calibration to
    #: learn whether the ranking column means anything.
    rankable_engines: tuple[str, ...]
    #: What the panel could not establish. A clean authorization over unevaluated checks is clean as
    #: far as anybody looked.
    unchecked: tuple[str, ...]
    issued_at: str
    expires_at: str
    signature: str

    def _signed_fields(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "calibration_sha256": self.calibration_sha256,
            "infrastructure_sha256": self.infrastructure_sha256,
            "panel_size": self.panel_size,
            "actives": self.actives,
            "recall": self.recall,
            "rankable_engines": self.rankable_engines,
            "unchecked": self.unchecked,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def covers(self, revision_id: str) -> bool:
        """Whether this token permits screening with *this* compiled funnel.

        The revision comparison is the point, and it is the same argument
        :meth:`~etalon.authority.grant.SpendAuthorization.covers` makes about rows. A campaign that
        calibrates one cascade and screens with another has applied thresholds nobody tested, and a
        config file with the same name is not evidence that its compiled funnel is the same one --
        MolCascade compiles to a revision id precisely so that it need not be.
        """

        return bool(revision_id) and revision_id == self.revision_id


def authorize_gate(
    calibration: Calibration,
    *,
    provenance: Mapping[str, Any] | None = None,
    lifetime_hours: float = DEFAULT_GATE_LIFETIME_HOURS,
) -> GateAuthorization:
    """Mint a token for a calibration that survived its panel, or refuse.

    Args:
        calibration: The verdict. Refused unless
            :attr:`~etalon.campaign.calibrate.Calibration.admissible`.
        provenance: ``Screen.provenance()`` or the ``infrastructure`` block of a recall report.
            Supplying it turns the engine-identity question from unevaluable into a digest
            comparison; omitting it is recorded in :attr:`GateAuthorization.unchecked`.
        lifetime_hours: See :data:`DEFAULT_GATE_LIFETIME_HOURS`.

    Raises:
        NotAuthorized: When the calibration is inadmissible. The message carries the panel's own
            refusals, because "the gate is not authorised" without them is unactionable.
    """

    if lifetime_hours <= 0:
        raise ValueError("a gate authorization needs a positive lifetime")
    if not calibration.admissible:
        raise NotAuthorized(
            "this gate configuration may not be applied at scale: "
            + "; ".join(calibration.refusals() or ("the panel produced no readable verdict",))
        )
    measured = calibration.recall
    assert measured is not None  # admissible implies a readable recall

    unchecked: list[str] = []
    infrastructure = _provenance_digest(provenance)
    if not infrastructure:
        unchecked.append("ENGINE_IDENTITY_UNRECORDED")
    if not calibration.rankable:
        # Not a refusal. A filter that cannot rank is still a usable filter; a campaign that reports
        # its scores as potency is the failure, and this is the flag that makes that visible.
        unchecked.append("SCORE_NOT_SHOWN_TO_RANK")

    issued = datetime.now(UTC)
    fields: dict[str, Any] = {
        "revision_id": calibration.revision_id,
        "calibration_sha256": calibration_digest(calibration),
        "infrastructure_sha256": infrastructure,
        "panel_size": calibration.panel_size,
        "actives": calibration.actives,
        "recall": float(measured),
        "rankable_engines": tuple(calibration.rankable),
        "unchecked": tuple(unchecked),
        "issued_at": issued.isoformat(),
        "expires_at": (issued + timedelta(hours=float(lifetime_hours))).isoformat(),
    }
    return GateAuthorization(**fields, signature=sign(fields))


def require_gate(token: GateAuthorization | None, revision_id: str) -> GateAuthorization:
    """Refuse to screen at scale without a token for this exact funnel.

    Three refusals, and the third is the one worth having: a token that is present, valid and about a
    different revision. That is ``faults``' WRONG_SUBJECT applied to a permission -- calibrating one
    funnel and screening with another. The skeleton is
    :func:`etalon.authority.subject.require_signed`; the messages stay here because they have to
    name this regime's minting route, and a refusal a host cannot act on is a wall.
    """

    return require_signed(
        token,
        covers=lambda issued: issued.covers(revision_id),
        missing=(
            f"no gate authorization for revision {revision_id[:12]}. Screen a known-active panel "
            "through this cascade, call campaign.calibrate.calibrate, then authorize_gate. A gate "
            "nobody tested on known binders is an untested claim applied to every molecule."
        ),
        stale="gate authorization is expired or its signature does not verify; re-run the panel",
        mismatch=(
            f"gate authorization is for revision {token.revision_id[:12] if token else ''}, but "
            f"the compiled funnel is {revision_id[:12]}. The configuration changed after it was "
            "calibrated."
        ),
    )


def unauthorized_gate(calibration: Calibration) -> dict[str, Any]:
    """Why this configuration cannot be applied, as a record rather than an exception.

    For the caller that wants to report the refusal and continue -- a planning tool, a dry run --
    rather than the one that was about to screen a million molecules.
    """

    return {
        "revision_id": calibration.revision_id,
        "admissible": calibration.admissible,
        "recall": calibration.recall,
        "required_recall": calibration.required_recall,
        "deleted_actives": list(calibration.deleted_actives),
        "refusals": list(calibration.refusals()),
        "rankable_engines": list(calibration.rankable),
    }


__all__ = [
    "DEFAULT_GATE_LIFETIME_HOURS",
    "GateAuthorization",
    "authorize_gate",
    "calibration_digest",
    "require_gate",
    "unauthorized_gate",
]
