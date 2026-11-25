"""The agent: a screen that is allowed to learn from simulation, under stated conditions.

Two regimes, one ledger. :class:`~moldarwin.campaign.loop.Campaign` is for the expensive-stage-limited
one -- few measurements, each costing GPU-hours, learn between them. :class:`~moldarwin.campaign.sweep.Sweep`
is for the throughput-limited one -- a million cheap measurements, where nothing is worth authorising
individually and the irreversible act is a miscalibrated gate rather than a wasted hour. They share
the ledger, the screen adapter and the infrastructure pinning, and share no selection policy, because
a sweep selects nothing: every molecule in the pool is screened.
"""

from moldarwin.campaign.calibrate import Calibration, PanelMember, Separation, TierVerdict, calibrate
from moldarwin.campaign.drivers import MolCatProcessScreening, MolCatScreening, RevisionChanged
from moldarwin.campaign.expensive import PrismStage
from moldarwin.campaign.generation import (
    ChunkResult,
    Generator,
    Ingest,
    Pocket,
    PrismGeneration,
)
from moldarwin.campaign.ledger import Entry, Ledger
from moldarwin.campaign.loop import Acquirer, Campaign, ExpensiveStage, Proposer, RoundOutcome
from moldarwin.campaign.pipeline import DEFAULT_FUNNEL, Pipeline, Plan
from moldarwin.campaign.propose import (
    Acquisition,
    Panel,
    ParameterChange,
    as_loop_acquirer,
    as_loop_proposer,
)
from moldarwin.campaign.supervisor import Supervisor, TickReport
from moldarwin.campaign.sweep import (
    DEFAULT_BATCH_SIZE,
    AdmitReport,
    Batch,
    Recovery,
    Sweep,
    SweepError,
)

__all__ = [
    "Acquirer",
    "Acquisition",
    "AdmitReport",
    "Batch",
    "Calibration",
    "Campaign",
    "ChunkResult",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_FUNNEL",
    "Entry",
    "ExpensiveStage",
    "Generator",
    "Ingest",
    "Ledger",
    "MolCatProcessScreening",
    "MolCatScreening",
    "Panel",
    "PanelMember",
    "ParameterChange",
    "Pipeline",
    "Plan",
    "Pocket",
    "PrismGeneration",
    "PrismStage",
    "Proposer",
    "Recovery",
    "RevisionChanged",
    "RoundOutcome",
    "Separation",
    "Supervisor",
    "Sweep",
    "SweepError",
    "TickReport",
    "TierVerdict",
    "as_loop_acquirer",
    "as_loop_proposer",
    "calibrate",
]
