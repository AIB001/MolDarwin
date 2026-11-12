"""Spending is reachable only through the check, because the check's output is the argument.

ADR 0006 says a guard on the path nobody takes is not a guard, and this package was written when
the MCP server exposed nine tools, none of which spent: every refusal it produced was advice
offered beside an action it had no relationship with, and the governance rested on a model choosing
to be governed.

That sentence was in the present tense and is no longer true of the server. Counted from the single
registration path ``mcp.server.tool_catalog`` builds: 89 tools, 47 free, 34 cheap, 7 that spend and
one no model may complete. The figure this docstring reasons *from* has twice been stale -- by
thirty tools and two spenders when it said 57, and by two free tools when it said 87 -- which is
worth more than a tidy-up: an argument about a census is only as good as the census, and
``tool_catalog`` is the function that takes it rather than a number anybody maintains by hand.

The argument below is unaffected and the premise has to be stated as history. Two amendments:

* :mod:`etalon.mcp.screen_gate` makes ``etalon_screen_submit`` accept a **gate** authorization.
* :mod:`etalon.authority.method` makes ``etalon_action_submit``, ``etalon_workflow_submit`` and
  ``etalon_workflow_advance`` accept a **method** authorization, which is the first object on this
  tool surface that a model passes to a spending tool and that the spending path rules on. The
  sentence *"nothing on the tool surface accepts a spend token, so ``require`` is reached only from
  Python"* was true of :func:`require` and still is: the expensive stage's own token has no tool.
  What changed is the class, not that one instance.

The count worth watching is stated as what it is: **3 of 7 SPENDS tools accept no authorization
object at all**, down from 6 of 7. ``tools/count_unguarded_spends.py`` takes that count from the
registration index rather than from this paragraph, for the reason the paragraph above gives -- and
it also states what the count does not establish: a parameter that accepts a token is not evidence
the tool refuses without one. ``screen.run`` and ``active.run`` reached through
``etalon_workflow_submit`` remain unauthorized; only ``method.run`` nodes are ruled on.

This package makes the relationship structural: :func:`authorize` runs the preflight and returns
tokens, the expensive stage requires one per row, and a token is bound to a digest of the exact
record so that checking one thing and building another is caught as well.

Three instances now, over one base:

:mod:`etalon.authority.subject`
    What the three share -- signing, expiry, serialisation, and the shape of the three refusals.
:mod:`etalon.authority.grant`
    A GPU-hour, bound to one handoff row.
:mod:`etalon.authority.gate`
    A threshold applied at scale, bound to one compiled funnel revision -- the regime with no
    expensive stage, where the irreversible act is a miscalibrated gate applied a million times.
:mod:`etalon.authority.method`
    ``method.run``'s host-authored argv, bound to the declaration that was prepared. The only one
    of the three whose subject is not scientific.
"""

from etalon.authority.gate import (
    DEFAULT_GATE_LIFETIME_HOURS,
    GateAuthorization,
    authorize_gate,
    calibration_digest,
    require_gate,
    unauthorized_gate,
)
from etalon.authority.method import (
    DEFAULT_METHOD_LIFETIME_HOURS,
    MethodAuthorization,
    NotAuthorizedMethod,
    authorize_method,
    method_request_subject,
    require_method,
    unauthorized_method,
)
from etalon.authority.grant import (
    DEFAULT_LIFETIME_HOURS,
    Authorized,
    NotAuthorized,
    SpendAuthorization,
    authorize,
    record_digest,
    require,
    unauthorized,
)

__all__ = [
    "DEFAULT_GATE_LIFETIME_HOURS",
    "DEFAULT_LIFETIME_HOURS",
    "DEFAULT_METHOD_LIFETIME_HOURS",
    "Authorized",
    "GateAuthorization",
    "MethodAuthorization",
    "NotAuthorized",
    "NotAuthorizedMethod",
    "SpendAuthorization",
    "authorize",
    "authorize_gate",
    "authorize_method",
    "calibration_digest",
    "method_request_subject",
    "record_digest",
    "require",
    "require_gate",
    "require_method",
    "unauthorized",
    "unauthorized_gate",
    "unauthorized_method",
]
