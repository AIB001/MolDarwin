"""Spending is reachable only through the check, because the check's output is the argument.

ADR 0006 says a guard on the path nobody takes is not a guard, and this package was written when
the MCP server exposed nine tools, none of which spent: every refusal it produced was advice
offered beside an action it had no relationship with, and the governance rested on a model choosing
to be governed.

That sentence was in the present tense and is no longer true of the server. Counted from the single
registration path ``mcp.server.tool_catalog`` builds: 87 tools, 45 free, 34 cheap, 7 that spend and
one no model may complete. The figure this docstring reasons *from* had been stale by thirty tools
and two spenders, which is worth more than a tidy-up -- an argument about a census is only as good
as the census, and ``tool_catalog`` is the function that takes it rather than a number anybody
maintains by hand.

The argument below is unaffected and the premise has to be stated as history -- and one thing it
describes is still exactly true of the expensive stage, which is the path this package guards:
nothing on the tool surface accepts a spend token, so ``require`` is reached only from Python.

What *has* changed, and is the one amendment to the sentence above:
:mod:`etalon.mcp.screen_gate` makes ``etalon_screen_submit`` accept a **gate** authorization, so of
the seven SPENDS tools one now takes an authorization object where seven took none. That is a gate
token and not a spend token -- it binds a calibrated funnel rather than a checked row -- and the
count worth watching is stated as what it is: 6 of 7 SPENDS tools accept no authorization object at
all. ``tools/count_unguarded_spends.py`` takes that count from the registration index rather than
from this paragraph, for the reason the paragraph above gives.

This package makes the relationship structural: :func:`authorize` runs the preflight and returns
tokens, the expensive stage requires one per row, and a token is bound to a digest of the exact
record so that checking one thing and building another is caught as well.

:mod:`etalon.authority.gate` is the same construction for the regime with no expensive stage, where
the irreversible act is not a wasted GPU-hour but a miscalibrated threshold applied a million times.
"""

from etalon.authority.gate import (
    DEFAULT_GATE_LIFETIME_HOURS,
    GateAuthorization,
    authorize_gate,
    calibration_digest,
    require_gate,
    unauthorized_gate,
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
    "Authorized",
    "GateAuthorization",
    "NotAuthorized",
    "SpendAuthorization",
    "authorize",
    "authorize_gate",
    "calibration_digest",
    "record_digest",
    "require",
    "require_gate",
    "unauthorized",
    "unauthorized_gate",
]
