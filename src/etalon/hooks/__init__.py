"""In-session hooks for the failures that are visible and recoverable while the session is open.

ETALON's hardened code and these hooks divide along one criterion, and the criterion is the
repository's own. ``.claude/skills/etalon-step-corpus/SKILL.md`` says of two fields it asks a host
to fill: *"Where a rule does not reach, leave the field empty; an inferred value here is
indistinguishable from a measured one later, which is the failure this project has a vocabulary to
avoid."*

So: **harden in code where a mistake becomes indistinguishable from a correct record later**
(``authority/grant.py``'s refusal to accept a verdict; ``mcp/coverage.py``'s refusal to let an
absent observation read as clean; ``mcp/screen_gate.py``'s refusal of an uncalibrated threshold at
scale). **Leave free, as a hook that interrupts rather than refuses, where a mistake is visible and
recoverable in the same session.** A corollary follows and is honoured throughout this package:
hardened code concerns only provenance and propagation and never constrains method choice, and a
hook never constrains anything at all.

Four hooks, each motivated by a measurement rather than by a principle. The numbers are in each
module's docstring because a threshold chosen against a measurement and a threshold somebody liked
are indistinguishable once the measurement is out of sight -- which is hard constraint 5 applied to
this package's own conventions.

:mod:`etalon.hooks.rule_replay`
    Replay the declared decision rule against the artifact about to be submitted. Two submissions
    were already mathematically unable to pass at submission time and nobody noticed.

:mod:`etalon.hooks.budget_floor`
    At ``ready``, put the granted allowance beside the consumed one, partitioned by reason. The
    agent used 2.0-2.9 of 8 structure-oracle calls and 2.4-6.0 of 15 property-oracle calls, and
    ``active/budget.py`` is three don't-overspend functions with no floor.

:mod:`etalon.hooks.tool_error_loop`
    On the second occurrence of one tool error, inject the fact that ends the loop. Of 6617 tool
    errors in an independent benchmark, models responded to 32.9% and changed a parameter in 6.6%.

:mod:`etalon.hooks.regime_drift`
    Surface a session that has been in ``diagnostic`` for many steps while its conclusions
    accumulate language presuming reliance. ``research/journal.py``'s two-line early return stands
    in front of the strongest predeclaration machinery in the repository, and
    ``research/composition.py`` defaults every evaluation to the lane that skips it.

**What a hook may do.** Interrupt: return text for the host to read, with every number it reports
carrying the basis it was taken from. Exactly one hook may block, in exactly one case -- a declared
outcome that contradicts a replayed numeric rule -- and it says so in its own docstring. A hook
never executes research, never writes a scientific record, never grants a permission and never
retries anything. Those are the same limits ``research_hooks.py`` already states, for the same
reason: a receipt is a host delivery trace and not a scientific journal.
"""

from etalon.hooks.session import (
    HOOK_SCHEMA,
    Interruption,
    host_output,
    quiet,
    session_state,
)

__all__ = [
    "HOOK_SCHEMA",
    "Interruption",
    "host_output",
    "quiet",
    "session_state",
]
