"""What ``grant.py`` and ``gate.py`` turned out to be two copies of: a permission bound to a subject.

The architecture review (``docs/thin-harness/ARCHITECTURE_REVIEW.md`` §P3) asked for this before it
asked for a third instance, and in that order on purpose: *"``grant.py`` and ``gate.py`` are the same
pattern written twice with no shared base, and a third subject -- a declared method request digest --
is the right third instance."* Writing the pattern a third time would have made the duplication the
design.

**What the two copies actually share**, read rather than assumed:

=========================  ==================================  ==================================
                           ``grant.SpendAuthorization``        ``gate.GateAuthorization``
=========================  ==================================  ==================================
constructed only by        ``authorize``                       ``authorize_gate``
signed body                ``json.dumps(fields, sort_keys)``   ``json.dumps(fields, sort_keys)``
validity                   signature + ``expires_at``          signature + ``expires_at``
records what was not seen  ``unchecked``                       ``unchecked``
refusals at the gate       missing / stale / wrong subject     missing / stale / wrong subject
=========================  ==================================  ==================================

**What they do not share**, which is why this module is a base and not a class the two became:

* the *subject*. A spend token is bound to one row of a handoff -- an identifier **and** a content
  digest, because ``boundary/simulate.py``'s argument applies: a directory named for a molecule is
  not evidence it holds that molecule. A gate token is bound to a compiled ``revision_id``, a single
  opaque string MolCascade produces precisely so that a config filename need not be trusted. One
  compares a mapping, the other compares a string, and collapsing them into "a subject digest" would
  have cost ``SpendAuthorization.covers`` the id/digest distinction its own docstring argues for.
* the *cardinality*. ``authorize`` rules on a sequence of rows and returns an aggregate carrying the
  refusals with their fault codes; ``authorize_gate`` rules on one calibration and raises. That is
  not an inconsistency to be tidied: a campaign authorises a thousand molecules at once and must
  report which ones it refused, while a funnel is one object and a refusal on it stops the campaign.
* the *lifetime*, and both modules argue their own figure from what the token describes.

So what is extracted here is the machinery that was literally identical -- signing, validity,
serialisation, and the shape of the three refusals -- and nothing that was only similar. Both
existing classes keep their own field layout and their own ``covers``; the bytes they sign are
unchanged by the extraction, which is checked rather than asserted
(``tests/test_method_authority.py::test_extraction_does_not_change_the_signed_bytes``).

The third instance is :mod:`etalon.authority.method`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any


class NotAuthorized(PermissionError):
    """Raised when a spend was attempted without, or past, an authorization.

    Defined here rather than in ``grant.py`` so that the three instances share one type, and
    re-exported from ``etalon.authority.grant`` because that is where the rest of the tree imports
    it from and an import path is part of a module's contract.

    It subclasses ``PermissionError`` -> ``OSError``, which is a hazard the MCP boundary has already
    been bitten by once: ``mcp/_common.py``'s ``_refusal`` intercepts it, because without the
    intercept a refusal reaches a model as *"it looks transient ... calling again is reasonable
    once"*. Any subclass added here must be added to that intercept too.
    """


_PROCESS_SECRET: bytes | None = None


def campaign_secret() -> bytes:
    """The key every authorization in this package is signed under.

    Read from ``ETALON_AUTHORITY_KEY`` when set, so that a campaign spanning processes -- a build
    queued now and driven by tomorrow's interpreter -- can verify tokens it did not mint. Otherwise
    generated per process.

    The per-process default is the safe one and the surprising one, so it is stated here: tokens do
    not survive a restart unless the variable is set. That is deliberate. A token surviving a
    restart is a token outliving the preflight it came from, and the remedy -- re-run a check that
    costs nothing -- is cheaper than the failure it prevents.
    """

    supplied = os.environ.get("ETALON_AUTHORITY_KEY", "")
    if supplied:
        return supplied.encode("utf-8")
    global _PROCESS_SECRET
    if _PROCESS_SECRET is None:
        _PROCESS_SECRET = secrets.token_bytes(32)
    return _PROCESS_SECRET


def digest_of(value: Any) -> str:
    """SHA-256 over a canonical JSON rendering, stable under key order and nothing else.

    ``sort_keys`` so that two serialisations of one object agree, and ``default=str`` so a value
    carrying a Path or a date digests rather than raising -- the alternative being an authorization
    that cannot be minted for a perfectly good record.
    """

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def sign(fields: Mapping[str, Any]) -> str:
    """The keyed digest over a token's fields.

    Every field is in the signature, so editing one invalidates the token rather than producing a
    token for different circumstances. It makes a token non-constructible *by accident* -- no
    dictionary literal produces one -- and it makes tampering visible. It is not a claim that a
    determined caller in the same process cannot mint one, and ``grant.py``'s docstring is the place
    that is said rather than a README that implies otherwise.
    """

    body = json.dumps(dict(fields), sort_keys=True, default=str)
    return hmac.new(campaign_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()


def _plain(value: Any) -> Any:
    """Tuples as lists, so ``as_dict`` renders what a reader of the record sees."""

    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


class Signed:
    """Signing, expiry and serialisation for a permission bound to a subject.

    A mixin rather than a base dataclass: all three tokens are ``frozen=True, slots=True``
    dataclasses with entirely different field sets, and a shared dataclass parent would have forced
    a shared field order on them for nothing. ``__slots__ = ()`` keeps the subclasses slotted.

    Subclasses supply :meth:`_signed_fields` -- every field except ``signature``, in the order they
    were signed in -- and a ``covers`` of their own, because what counts as the same subject is the
    one thing the three instances genuinely disagree about.
    """

    __slots__ = ()

    signature: str
    expires_at: str

    def _signed_fields(self) -> dict[str, Any]:  # pragma: no cover -- subclass contract
        raise NotImplementedError

    def _body(self) -> str:
        return json.dumps(self._signed_fields(), sort_keys=True, default=str)

    def valid(self, *, when: datetime | None = None) -> bool:
        """Whether the signature verifies and the token has not expired.

        Not "whether the subject matches": that is :meth:`covers`, and the two are kept apart
        because a stale token and a token about something else are different mistakes with
        different remedies.
        """

        moment = when or datetime.now(UTC)
        signed = hmac.new(campaign_secret(), self._body().encode("utf-8"), hashlib.sha256)
        if not hmac.compare_digest(signed.hexdigest(), self.signature):
            return False
        return moment <= datetime.fromisoformat(self.expires_at)

    def as_dict(self) -> dict[str, Any]:
        return {
            **{key: _plain(value) for key, value in self._signed_fields().items()},
            "signature": self.signature,
        }


def require_signed(
    token: Signed | None,
    *,
    covers: Callable[[Any], bool],
    missing: str,
    stale: str,
    mismatch: str,
    when: datetime | None = None,
    error: type[NotAuthorized] = NotAuthorized,
) -> Any:
    """The three refusals, in the order the remedies differ.

    They are distinct on purpose, and the third is the one worth having: a token that is present,
    valid and about a different subject. That is ``faults``' ``WRONG_SUBJECT`` applied to a
    permission -- checking one thing and spending on another -- and a single "not authorised" would
    send a reader looking in the wrong place for all three.

    Each message is the caller's, not this function's, because a refusal a host cannot act on is a
    wall: the message has to name the tool that mints the token and what it is minted on, and only
    the caller knows that. ``error`` is the caller's for the same reason one step further out:
    ``mcp/_common.py``'s refusal intercept chooses the remedy it shows a model by exception type,
    so an instance that raised the base type would be told to calibrate a screening panel.
    """

    if token is None:
        raise error(missing)
    if not token.valid(when=when):
        raise error(stale)
    if not covers(token):
        raise error(mismatch)
    return token


__all__ = [
    "NotAuthorized",
    "Signed",
    "campaign_secret",
    "digest_of",
    "require_signed",
    "sign",
]
