"""A gate that cannot be walked past, because the expensive stage takes its output as an argument.

ADR 0006 records a bug and names its class. The MCP tools took ``waived`` as a comma-separated list
of fault codes and honoured it without constructing a ``Waiver``, so every guard in
``judgment/waiver.py`` -- unknown code, short reason, unnamed grantor, model-shaped grantor, a fault
whose consequence only qualifies a claim -- ran on a path nobody used. A model could release
``F_COORDINATES_ARE_A_DEPICTION``, the cause that tool's own ``next_step`` calls unfixable by a
waiver, by typing its name. The title of the ADR is the general statement: *a guard on the path
nobody takes is not a guard.*

That instance is fixed. The class is not, and it is larger than the instance.

Count the tools ETALON's MCP server exposes by what they spend: seven free, one cheap, one that a
model may never complete. **None of them spends.** A model running a campaign reaches
``etalon_check_handoff``, reads a refusal, and then calls PRISM's own server to build the system --
because that is where building lives. Nothing connects the two. The refusal is a suggestion that
arrives before an action it has no relationship with, and the whole governance argument in the
skill document -- "everything cheap refuses, and everything expensive is guarded by something
cheap" -- rests on the model choosing to be guarded.

A skill document is a prompt. The measured failure modes of these systems include implementation
drift under execution pressure and memory degradation over long horizons, which is a precise
description of a model that read the workflow in round one and is improvising in round nine.

So the guard stops being a document and becomes a *type*. :func:`authorize` is the only way to
construct a :class:`SpendAuthorization`, it runs the deterministic preflight itself, and it issues
nothing for a record that blocks. ``PrismStage`` and anything else implementing the campaign's
expensive-stage protocol take a mapping of authorizations and refuse a row that has none. The path
that spends without checking is not guarded against; it does not exist, because the function that
spends cannot be called without the object that checking produces.

**What this defends against, precisely.** Not a hostile operator: this runs in one Python process,
and anyone who can call the stage can import this module. What it defends against is every way a
correct intention becomes a wrong spend --

* the check never called, because the model forgot, reordered, or resumed mid-campaign;
* the check called on one set of records and the build run on another, which is the same
  ``WRONG_SUBJECT`` failure the taxonomy is about, applied to the authorization rather than to the
  molecule. An authorization is bound to a digest of the exact row, so a token minted for one
  molecule cannot spend on a second, and a row edited after the check no longer matches its token;
* a waiver that was granted for an earlier round still releasing a fault weeks later, which is what
  :attr:`SpendAuthorization.expires_at` is for;
* the receptor changing between the check and the build.

The signature is a keyed digest over those fields. It makes a token non-constructible *by accident*
-- no dictionary literal produces one -- and it makes tampering visible. It is not a claim that a
determined caller in the same process cannot mint one, and this docstring is the place that is said
rather than a README that implies otherwise.

**What moved out.** Signing, expiry, serialisation and the shape of the three refusals now live in
:mod:`etalon.authority.subject`, which this module and :mod:`etalon.authority.gate` were two copies
of and :mod:`etalon.authority.method` is the third instance of. The subject -- a parent id *and* a
content digest -- stayed here, because it is the thing the three disagree about. Not one byte any
token signs changed, which ``tests/test_method_authority.py`` pins against the signatures recorded
from a ``git archive HEAD`` checkout rather than against itself.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from etalon.authority.subject import (
    NotAuthorized,
    Signed,
    campaign_secret,
    digest_of,
    require_signed,
    sign,
)

#: Kept as a name in this module because it is the import path the rest of the tree uses, and an
#: import path is part of a module's contract. The definition moved to
#: :mod:`etalon.authority.subject` when the third instance needed it.
_campaign_secret = campaign_secret

#: How long an authorization is good for. A build starts within minutes of its check in any
#: campaign that is working; a token still valid a week later is one that outlived the state it
#: describes. Short enough to catch a resumed run that skipped re-checking, long enough that a
#: queue wait does not invalidate a legitimate spend.
DEFAULT_LIFETIME_HOURS = 24.0


def record_digest(row: Mapping[str, Any]) -> str:
    """A digest over the handoff row, stable under key order and nothing else.

    ``sort_keys`` so that two serialisations of one row agree, and ``default=str`` so a row
    carrying a Path or a date digests rather than raising -- the alternative being an
    authorization that cannot be minted for a perfectly good record.
    """

    return digest_of(dict(row))


def _file_digest(path: Path | None) -> str:
    if path is None:
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class SpendAuthorization(Signed):
    """Permission to spend GPU-time on one molecule, bound to the thing that was checked.

    Constructed only by :func:`authorize`. Every field is in the signature, so changing one
    invalidates the token rather than producing a token for different circumstances.

    Signing, expiry and serialisation come from :class:`etalon.authority.subject.Signed`; the field
    layout and :meth:`covers` stay here, because the subject is the one thing the three
    authorizations in this package genuinely disagree about.
    """

    parent_id: str
    #: Digest of the exact row preflight ruled on. The build's row is digested again and compared.
    record_sha256: str
    #: Digest of the receptor file, or empty when none was supplied -- in which case the receptor
    #: check was unevaluable and :attr:`unchecked` says so.
    receptor_sha256: str
    issued_at: str
    expires_at: str
    #: Fault codes that fired and were released by a granted waiver to get here. Carried into the
    #: token so a reader of a spend does not have to find the round's waiver set separately.
    proceeded_under_waiver: tuple[str, ...]
    #: Codes that could not be evaluated. An authorization over unevaluable checks is clean as far
    #: as anybody looked, which is not the same as clean, and the token says which.
    unchecked: tuple[str, ...]
    signature: str

    def _signed_fields(self) -> dict[str, Any]:
        return {
            "parent_id": self.parent_id,
            "record_sha256": self.record_sha256,
            "receptor_sha256": self.receptor_sha256,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "proceeded_under_waiver": self.proceeded_under_waiver,
            "unchecked": self.unchecked,
        }

    def covers(self, row: Mapping[str, Any]) -> bool:
        """Whether this token authorises spending on *this* row, not merely on its name.

        The digest comparison is the point. A campaign that checks one set of rows and builds from
        another has produced numbers about molecules nobody ruled on, and a parent id matching is
        not evidence the row is the one that was checked -- ``boundary/simulate.py`` makes the same
        argument about a directory named for a molecule not being evidence it holds that molecule.
        """

        return (
            str(row.get("parent_id", "")) == self.parent_id
            and record_digest(row) == self.record_sha256
        )


def _sign(**fields: Any) -> SpendAuthorization:
    return SpendAuthorization(**fields, signature=sign(fields))


@dataclass(frozen=True, slots=True)
class Authorized:
    """What :func:`authorize` produced: the tokens, and every refusal with its reason."""

    grants: Mapping[str, SpendAuthorization]
    #: ``parent_id -> [fault codes]`` for records that may not be spent on.
    refused: Mapping[str, tuple[str, ...]]
    notes: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.grants)

    def as_dict(self) -> dict[str, Any]:
        return {
            "authorized": {k: v.as_dict() for k, v in sorted(self.grants.items())},
            "refused": {k: list(v) for k, v in sorted(self.refused.items())},
            "authorized_count": len(self.grants),
            "refused_count": len(self.refused),
            "notes": list(self.notes),
        }


def authorize(
    rows: Sequence[Mapping[str, Any]],
    *,
    receptor_path: Path | None = None,
    toolchain_active: bool | None = None,
    waivers: Any = None,
    lifetime_hours: float = DEFAULT_LIFETIME_HOURS,
    now: datetime | None = None,
) -> Authorized:
    """Run the preflight and mint a token for each record that survives it.

    This is the only constructor of :class:`SpendAuthorization` that signs, and it does not take a
    verdict from the caller -- it calls :func:`etalon.faults.preflight.check_record` itself. A
    function that accepted "this one passed" as an argument would be a guard on the path nobody
    takes with extra steps.

    Args:
        waivers: A :class:`~etalon.judgment.waiver.WaiverSet`. Expiry is applied through
            ``codes()``, so a waiver that has run out releases nothing and its fault blocks again.
    """

    from etalon.faults.preflight import blocking, check_record, unchecked, waived_blocking

    moment = now or datetime.now(UTC)
    released = waivers.codes() if waivers is not None else frozenset()
    receptor_sha = _file_digest(receptor_path) if receptor_path else ""

    grants: dict[str, SpendAuthorization] = {}
    refused: dict[str, tuple[str, ...]] = {}
    notes: list[str] = []
    waived_any = False

    for row in rows:
        identifier = str(row.get("parent_id", ""))
        if not identifier:
            notes.append(
                "A record carries no parent_id and cannot be authorised: a token is bound to an "
                "identifier and a digest, and an unnamed record has one of the two."
            )
            continue
        seen = check_record(
            row, receptor_path=receptor_path, toolchain_active=toolchain_active
        )
        blocked = tuple(entry.code for entry in blocking(seen, waived=released))
        if blocked:
            refused[identifier] = blocked
            continue
        accepted = tuple(entry.code for entry in waived_blocking(seen, released))
        waived_any = waived_any or bool(accepted)
        grants[identifier] = _sign(
            parent_id=identifier,
            record_sha256=record_digest(row),
            receptor_sha256=receptor_sha,
            issued_at=moment.isoformat(timespec="seconds"),
            expires_at=(moment + timedelta(hours=lifetime_hours)).isoformat(
                timespec="seconds"
            ),
            proceeded_under_waiver=accepted,
            unchecked=tuple(entry.code for entry in unchecked(seen)),
        )

    if refused:
        notes.append(
            f"{len(refused)} of {len(rows)} record(s) were refused and no token was minted for "
            "them. The expensive stage cannot be called on a record without one, so this is not a "
            "warning that a later step may honour -- the spend is unreachable."
        )
    if waived_any:
        notes.append(
            "Some tokens were minted over a fault that fired and was waived. The cause is not "
            "cleared: it is recorded in the token, it rides into the measurement's provenance, "
            "and it stays a standing candidate if that round's numbers later disagree with "
            "something."
        )
    if receptor_path is None:
        notes.append(
            "No receptor was supplied, so F_RECEPTOR_NOT_THE_ONE_SCORED could not be evaluated "
            "for any record and every token says so in `unchecked`. A token over an unevaluable "
            "check authorises a spend; it does not assert the check passed."
        )
    return Authorized(grants=grants, refused=refused, notes=tuple(notes))


def require(
    row: Mapping[str, Any],
    grants: Mapping[str, SpendAuthorization],
    *,
    when: datetime | None = None,
    receptor_path: Path | None = None,
) -> SpendAuthorization:
    """Return the token that authorises spending on this row, or refuse with the remedy.

    Called at the top of every expensive stage. The three refusals are distinct on purpose: a
    missing token, an expired or tampered one, and one that belongs to a different version of the
    row are different mistakes with different fixes, and a single "not authorised" would send a
    reader looking in the wrong place for all three. They are taken by
    :func:`etalon.authority.subject.require_signed`, which is that skeleton extracted; the messages
    stay here because only this module knows which function mints the token and what it is minted
    on, and a refusal that does not say so is a wall.

    The receptor check below is a fourth refusal and deliberately not part of the shared skeleton:
    it is about a file on disk now rather than about the token, and no other instance has one.
    """

    identifier = str(row.get("parent_id", ""))
    token = require_signed(
        grants.get(identifier),
        covers=lambda issued: issued.covers(row),
        when=when,
        missing=(
            f"no spend authorization for {identifier!r}. The expensive stage takes the output of "
            "etalon.authority.authorize, which runs the preflight and issues nothing for a record "
            "that blocks -- so a missing token means either the check refused this record or it "
            "was never run on it. Run authorize() over the handoff rows and pass what it returns. "
            "See ADR 0006: a guard on the path nobody takes is not a guard, which is why this one "
            "is an argument rather than a recommendation."
        ),
        stale=(
            f"the authorization for {identifier!r} does not verify or has expired. A token "
            "outliving its preflight describes a state nobody has checked recently; re-run "
            "authorize(), which costs nothing. If it was minted in another process, set "
            "ETALON_AUTHORITY_KEY in both."
        ),
        mismatch=(
            f"the authorization for {identifier!r} was minted for a different version of this "
            "record -- the id matches and the content digest does not. Something edited the row "
            "between the check and the spend, so what was ruled on is not what would be built. "
            "This is the taxonomy's WRONG_SUBJECT applied to the authorization itself. Re-run "
            "authorize() on the rows you are actually going to build."
        ),
    )
    if receptor_path is not None and (
        not token.receptor_sha256 or _file_digest(receptor_path) != token.receptor_sha256
    ):
        raise NotAuthorized(
            "the actual receptor was not checked or changed after authorization; "
            "re-run authorize() with the receptor file the stage will use"
        )
    return token


def unauthorized(
    rows: Sequence[Mapping[str, Any]], grants: Mapping[str, SpendAuthorization]
) -> tuple[str, ...]:
    """Which of these rows cannot be spent on, without raising -- for a caller that reports first."""

    out = []
    for row in rows:
        try:
            require(row, grants)
        except NotAuthorized:
            out.append(str(row.get("parent_id", "")))
    return tuple(out)


__all__ = [
    "DEFAULT_LIFETIME_HOURS",
    "Authorized",
    "NotAuthorized",
    "SpendAuthorization",
    "authorize",
    "record_digest",
    "require",
    "unauthorized",
]
