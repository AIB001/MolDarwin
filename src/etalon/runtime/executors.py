"""Persist typed scientific dispatchers; registration never runs an experiment."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from etalon.active.cascade import CascadeExecutor, CascadeRecipe, Readout, _file_hash
from etalon.active.schema import Endpoint, Evaluation, canonical, digest, finite
from etalon.active.store import CampaignStore, StateError
from etalon.runtime.schema import absolute, fields, text

SCHEMA = "etalon-executor/1"
_PREFIX = "runtime:executor:"


def _endpoint(value: dict, protocol: str, fixed: dict[str, Any]) -> Endpoint:
    if not isinstance(value, dict):
        raise ValueError("endpoint must be a mapping")
    supplied = dict(value)
    for key, expected in {"protocol": protocol, **fixed}.items():
        if key in supplied and (type(supplied[key]) is not type(expected) or supplied[key] != expected):
            raise ValueError(f"executor requires endpoint {key}={expected!r}")
        supplied[key] = expected
    return Endpoint(**supplied)


def _recipe(configuration: dict) -> CascadeRecipe:
    return CascadeRecipe.freeze(configuration["cascade"], Readout(**configuration["readout"]),
                                files=tuple(configuration["files"]),
                                aggregation=configuration.get("aggregation"))


def _declared_aggregation(configuration: dict) -> dict:
    """``{"aggregation": ...}`` where a policy is declared, and ``{}`` where none is.

    Folded into the protocol digest by the caller, so that changing how draws are aggregated is a
    new protocol id refused under the old one rather than a reinterpretation of its records. Absent
    where undeclared, because digesting an explicit default would move every protocol id that
    already exists -- see ``CascadeRecipe.protocol_id`` for the same decision and its reason.
    """
    from etalon.active.aggregation import AggregationPolicy

    policy = AggregationPolicy.declare(configuration.get("aggregation"))
    return {} if policy.is_default else {"aggregation": policy.as_dict()}


def aggregation_provenance(record: dict, endpoint: Endpoint, *, candidate_id: str,
                           actions: list[dict], observations: list[dict]) -> dict:
    """The stage-1 coverage block, to travel beside the value it is about.

    Declared draws, authorised draws, combiner, and the dispersion figure or ``not_taken``, for
    this one candidate at this one endpoint. Nothing is refused by this block and no ``Ruling``
    moves; what it establishes is that the declaration and the authorised count are separately
    visible in the record, so a one-draw value and a several-draw consensus stop reading alike.

    The action being dispatched is itself an authorised draw, so a running action counts here --
    unlike a post-hoc read, where only a completed action has produced one.
    """
    from etalon.active.aggregation import AggregationPolicy, authorised_draws, coverage

    configuration = record.get("configuration") or {}
    policy = AggregationPolicy.declare(configuration.get("aggregation"))
    seeds = configuration.get("seeds")
    distinct = (seeds if isinstance(seeds, list) and len(set(seeds)) == len(seeds) else None)
    counted = authorised_draws(actions, candidate_id=candidate_id, endpoint_id=endpoint.id,
                               seeds=distinct, counted_statuses=("completed", "running"))
    values = [float(row["result"]["value"]) for row in observations
              if row.get("admitted") and isinstance(row.get("result"), dict)
              and row["result"].get("endpoint_id") == endpoint.id
              and row["result"].get("candidate_id") == candidate_id
              and isinstance(row["result"].get("value"), (int, float))
              and not isinstance(row["result"].get("value"), bool)]
    return coverage(policy, counted, values=values)


def _aggregation_block(record: dict, endpoint: Endpoint, candidate_id: str) -> Evaluation | None:
    """Refuse to dispatch an action whose protocol declares draws this endpoint cannot authorise.

    The general form of the refusal below for ``prism_mmpbsa_replicated``, keyed on the declared
    aggregation policy rather than on an executor kind. That refusal was correct and it was one
    executor's special case: every other kind reaches a branch that runs a single trajectory, so a
    protocol declaring five independent draws would quietly run one and report the result under a
    protocol id claiming five. Both shipped dispatchable kinds have ``max_replicates = 1``.

    Returns a blocked :class:`Evaluation` at zero cost, exactly as the executor preflight refusal
    does -- nothing is started, so nothing is charged. ``None`` means there is nothing to refuse,
    which is the case for every protocol that declares no policy.
    """
    from etalon.active.aggregation import AggregationPolicy, dispatch_refusal

    configuration = record.get("configuration") or {}
    policy = AggregationPolicy.declare(configuration.get("aggregation"))
    seeds = configuration.get("seeds")
    refusal = dispatch_refusal(
        policy, max_replicates=endpoint.max_replicates,
        declared_seeds=None if not isinstance(seeds, list) else len(set(seeds)))
    if refusal is None:
        return None
    return Evaluation(candidate_id, endpoint.id, None, endpoint.units, 0.0, status="blocked",
        provenance={"phase": "executor_dispatch", "executor_id": record.get("executor_id"),
                    "error": "UNSUPPORTED: " + refusal,
                    "declared_aggregation": policy.as_dict(),
                    "cost_basis": "not dispatched"})


def prepare_executor(kind: str, configuration: dict, endpoint: dict) -> dict:
    """Validate a registered implementation and freeze its scientific inputs, without dispatch."""
    if kind == "molcascade":
        fields(configuration, {"cascade", "readout"}, {"files", "aggregation"})
        fields(configuration["readout"], {"stage_id", "contract_id", "value_column"}, {"filters"})
        for key in ("stage_id", "contract_id", "value_column"):
            text(configuration["readout"][key], key)
        if not isinstance(configuration["readout"].get("filters", {}), dict):
            raise ValueError("readout filters must be a mapping")
        files = configuration.get("files", [])
        if not isinstance(files, list):
            raise ValueError("executor files must be a list of absolute paths")
        paths = [str(absolute(path)) for path in files]
        recipe = CascadeRecipe.freeze(configuration["cascade"], Readout(**configuration["readout"]),
                                      files=tuple(paths),
                                      aggregation=configuration.get("aggregation"))
        normalized = {"cascade": json.loads(recipe.configuration),
                      "readout": json.loads(recipe.readout_json),
                      "files": [path for path, _ in recipe.input_files]}
        # Omitted where undeclared, so an executor registered before the policy existed keeps its
        # exact identity; the recipe's own digest treats an undeclared policy the same way.
        if recipe.aggregation_json:
            normalized["aggregation"] = json.loads(recipe.aggregation_json)
        inputs = dict(recipe.input_files)
        contract = _endpoint(endpoint, recipe.protocol_id,
                             {"requires_handoff": False, "queryable": True, "max_replicates": 1})
    elif kind == "prism":
        from etalon.boundary.infra import load

        fields(configuration, {"receptor_path", "python", "production_ns"},
               {"timeout_per_molecule", "aggregation"})
        receptor, interpreter = absolute(configuration["receptor_path"]), absolute(configuration["python"])
        duration, timeout = configuration["production_ns"], configuration.get("timeout_per_molecule", 86_400)
        for name, value in (("production_ns", duration), ("timeout_per_molecule", timeout)):
            finite(value, name, minimum=0)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        normalized = {"receptor_path": str(receptor), "python": str(interpreter),
                      "production_ns": float(duration), "timeout_per_molecule": float(timeout),
                      **_declared_aggregation(configuration)}
        inputs = {str(path): _file_hash(path) for path in sorted({receptor, interpreter})}
        infra = load("prism")
        protocol = "prism-mmpbsa/1:" + digest({"configuration": normalized, "inputs": inputs,
            "infrastructure": {"source_commit": infra.source_commit, "tree_sha256": infra.tree_sha256,
                               "version": infra.version}})
        contract = _endpoint(endpoint, protocol, {"quantity": "mmpbsa", "units": "kcal/mol",
            "direction": "minimize", "requires_handoff": True, "queryable": True, "max_replicates": 1})
    elif kind == "prism_mmpbsa_replicated":
        normalized, inputs, protocol = _replicated_mmpbsa_configuration(configuration)
        contract = _endpoint(endpoint, protocol, {"quantity": "mmpbsa", "units": "kcal/mol",
            "direction": "minimize", "requires_handoff": True, "queryable": True,
            "max_replicates": len(normalized["seeds"])})
    elif kind == "prism_bridge_v1":
        normalized, inputs = _bridge_configuration(configuration)
        template = normalized["request_template"]
        contract = _endpoint({"max_replicates": len(normalized["seeds"]), **endpoint}, template["protocol_id"], {
            "id": template["endpoint_id"], "quantity": "mean_residue_contacts", "units": "count",
            "direction": "maximize", "requires_handoff": True, "queryable": True})
    else:
        raise ValueError("executor kind must be molcascade, prism, prism_mmpbsa_replicated "
                         "or prism_bridge_v1")
    body = {"schema": SCHEMA, "kind": kind, "configuration": normalized,
            "endpoint": contract.as_dict(), "inputs": inputs}
    return {**body, "executor_id": digest(body)}


def _replicated_mmpbsa_configuration(configuration: dict) -> tuple[dict, dict, str]:
    """Freeze an independent-replica MM-PBSA protocol, including who computes the energy.

    Three things separate this from ``kind="prism"``, and each was a gap rather than a
    preference:

    **Replicas are seeded and the seeds are recorded.** ``Simulate.seed`` covers the build --
    ion placement -- and not the velocity generation, and the production mdp carried
    ``gen_seed = -1``. So replicas did differ, randomly, and no record said how: the spread
    across three trajectories could not be told apart from one trajectory read three times.
    A seed per replica is the evidence for the word "independent", so it is required here and
    ``max_replicates`` is exactly how many were declared.

    **The energy's author is explicit.** ``gmx_MMPBSA`` writes
    ``FINAL_RESULTS_MMPBSA.dat``; nothing in this project ran it, and
    ``read_binding_energy`` reads whichever file is present. That is why
    ``STALE_MMPBSA_RESULT`` exists in the fault taxonomy -- a previous system's energy left
    in the directory reads as this build's affinity. ``mmpbsa_command`` is therefore
    optional and absent by default: without it this executor only *reads*, exactly as
    before, and with it the command becomes part of the protocol identity so a campaign
    cannot half-change how its affinities were produced.

    **Nothing here dispatches.** Registration freezes inputs; see the dispatcher, which
    refuses this kind rather than letting it fall through to the single-run legacy stage.
    """

    fields(configuration, {"receptor_path", "python", "production_ns", "seeds"},
           {"timeout_per_molecule", "mmpbsa_command", "mmpbsa_subdir", "aggregation"})
    receptor, interpreter = absolute(configuration["receptor_path"]), absolute(configuration["python"])
    duration = configuration["production_ns"]
    timeout = configuration.get("timeout_per_molecule", 86_400)
    for name, value in (("production_ns", duration), ("timeout_per_molecule", timeout)):
        finite(value, name, minimum=0)
        if value <= 0:
            raise ValueError(f"{name} must be positive")

    seeds = configuration["seeds"]
    if (not isinstance(seeds, list) or not seeds
            or any(type(seed) is not int or not 0 <= seed <= 2147483647 for seed in seeds)):
        raise ValueError("seeds must be a nonempty list of integers in [0, 2147483647]")
    if len(set(seeds)) != len(seeds):
        # Two replicas under one seed are one trajectory computed twice. Admitting that as a
        # spread would report a reproducibility this protocol never measured.
        raise ValueError("replica seeds must be distinct; a repeated seed is a retry, not a replica")

    command = configuration.get("mmpbsa_command")
    if command is not None:
        if (not isinstance(command, list) or not command
                or any(not isinstance(part, str) or not part.strip() for part in command)):
            raise ValueError("mmpbsa_command must be a nonempty list of nonempty strings")
        # Resolved here so the protocol identity names the executable that will actually run,
        # not a bare word whose meaning depends on PATH at dispatch time.
        absolute(command[0])
    subdir = configuration.get("mmpbsa_subdir", "GMX_PROLIG_MMPBSA")
    text(subdir, "mmpbsa_subdir")
    if Path(subdir).is_absolute() or ".." in Path(subdir).parts:
        raise ValueError("mmpbsa_subdir must be a relative path inside the run directory")

    normalized = {"receptor_path": str(receptor), "python": str(interpreter),
                  "production_ns": float(duration), "timeout_per_molecule": float(timeout),
                  "seeds": list(seeds), "mmpbsa_subdir": subdir,
                  "mmpbsa_command": list(command) if command is not None else None,
                  **_declared_aggregation(configuration)}
    inputs = {str(path): _file_hash(path) for path in sorted({receptor, interpreter})}
    if command is not None:
        inputs[str(absolute(command[0]))] = _file_hash(absolute(command[0]))

    from etalon.boundary.infra import load

    infra = load("prism")
    protocol = "prism-mmpbsa-replicated/1:" + digest({
        "configuration": normalized, "inputs": inputs,
        "energy_author": "etalon" if command is not None else "operator",
        "infrastructure": {"source_commit": infra.source_commit, "tree_sha256": infra.tree_sha256,
                           "version": infra.version}})
    return normalized, inputs, protocol


def _bridge_configuration(configuration: dict) -> tuple[dict, dict]:
    from pathlib import PurePosixPath
    from etalon.boundary.prism_v1 import CLITransport, validate_request

    fields(configuration, {"request_template", "transport", "job_root", "receptor_path", "seeds"},
           {"poll_seconds", "wait_seconds", "aggregation"})
    if configuration.get("aggregation") is not None:
        # Refused rather than accepted and ignored. This kind takes its ``protocol_id`` from the
        # request template validated in ``boundary/prism_v1``, so a policy declared here would not
        # be part of the protocol's identity: it could be changed under an existing id, which is
        # the one property folding the policy into the digest exists to provide. A declaration that
        # the identity does not carry is worse than no declaration, because it moves the claim from
        # the number to the declaration.
        raise ValueError(
            "prism_bridge_v1 takes its protocol identity from the request template, so an "
            "aggregation policy declared on the executor would not be part of it; declare it on "
            "the template's protocol instead"
        )
    fields(configuration["transport"], {"python", "cwd", "request_root"}, {"host", "timeout"})
    transport = CLITransport(**configuration["transport"])
    validate_request(configuration["request_template"])
    seeds = configuration["seeds"]
    if (not isinstance(seeds, list) or not seeds or len(set(seeds)) != len(seeds)
            or any(type(s) is not int or not 0 <= s <= 2147483647 for s in seeds)):
        raise ValueError("bridge seeds must be distinct supported integers")
    normalized = json.loads(canonical(configuration))
    normalized["receptor_path"] = str(absolute(configuration["receptor_path"]))
    for key, default in (("poll_seconds", 2), ("wait_seconds", 3600)):
        value = configuration.get(key, default)
        finite(value, key, minimum=.001)
        normalized[key] = float(value)
    if transport.host:
        if not PurePosixPath(configuration["job_root"]).is_absolute():
            raise ValueError("SSH job_root must be an absolute POSIX path")
    else:
        absolute(configuration["job_root"])
    receptor_hash = _file_hash(Path(normalized["receptor_path"]))
    if receptor_hash != configuration["request_template"]["inputs"]["protein"]["sha256"]:
        raise ValueError("local authorization receptor differs from target-host protein")
    for artifact in configuration["request_template"]["inputs"].values():
        transport.verify(artifact)
    return normalized, {"receptor_sha256": receptor_hash, "producer": transport.fingerprint()}


def _bridge(store: CampaignStore, configuration: dict):
    from etalon.active.prism import PrismV1Executor
    from etalon.boundary.prism_v1 import CLITransport

    return PrismV1Executor(store, CLITransport(**configuration["transport"]),
                           **{k: v for k, v in configuration.items() if k != "transport"})


def _identity(prepared: dict) -> None:
    fields(prepared, {"schema", "kind", "configuration", "endpoint", "inputs", "executor_id"})
    if prepared["schema"] != SCHEMA or prepared["executor_id"] != digest(
            {key: value for key, value in prepared.items() if key != "executor_id"}):
        raise ValueError("executor record differs from its prepared identity")


def _verify(prepared: dict) -> None:
    _identity(prepared)
    fresh = prepare_executor(prepared["kind"], prepared["configuration"], prepared["endpoint"])
    if canonical(fresh) != canonical(prepared):
        raise ValueError("executor inputs, infrastructure or configuration changed since preparation")


def _store(database: str | Path, *, read_only: bool = False) -> CampaignStore:
    path = absolute(database)
    if not path.is_file():
        raise FileNotFoundError(f"configure a campaign before registering executors: {path}")
    return CampaignStore(path, read_only=read_only)


class _TransactionStore:
    """Let ProtocolRegistry share the surrounding registration transaction."""

    def __init__(self, db: Any) -> None:
        self.db = db

    @contextmanager
    def connection(self, *, write: bool = False):
        if not write:
            raise StateError("executor registration expects the registry's write transaction")
        yield self.db

    _event = staticmethod(CampaignStore._event)


def register_executor(database: str | Path, prepared: dict, rationale: str) -> dict:
    """Bind an immutable dispatcher to an existing endpoint in one journal transaction."""
    from etalon.active.protocols import ProtocolRegistry

    text(rationale, "executor registration rationale")
    _verify(prepared)
    record = json.loads(canonical(prepared))
    store = _store(database)
    endpoint = Endpoint(**record["endpoint"])
    with store.connection(write=True) as db:
        spec, endpoints = store._configuration(db)
        if endpoint.id not in endpoints or endpoints[endpoint.id] != endpoint:
            raise ValueError("executor endpoint must exactly match its registered campaign endpoint")
        key = _PREFIX + endpoint.id
        previous = db.execute("SELECT body FROM metadata WHERE key=?", (key,)).fetchone()
        added = previous is None
        if previous is not None:
            if previous[0] != canonical(record):
                raise StateError("registered executor is immutable; use a new endpoint id")
        else:
            if (db.execute("SELECT 1 FROM actions WHERE status IN ('reserved','running')").fetchone()
                    or db.execute("SELECT 1 FROM rounds WHERE status='running'").fetchone()):
                raise StateError("resolve pending actions and rounds before registering an executor")
            if record["kind"] == "prism_bridge_v1":
                if spec.cost_unit != "wall_second":
                    raise ValueError("prism_bridge_v1 requires campaign cost_unit=wall_second")
                for existing in db.execute("SELECT body FROM metadata WHERE key LIKE ?", (_PREFIX + "%",)):
                    if json.loads(existing[0])["kind"] == "prism_bridge_v1":
                        raise StateError("bounded bridge supports one fixed template per campaign")
            if record["kind"] == "molcascade":
                ProtocolRegistry(_TransactionStore(db)).bind_seed(endpoint.id, _recipe(record["configuration"]),
                                                                 rationale=rationale)
            db.execute("INSERT INTO metadata VALUES (?,?)", (key, canonical(record)))
            store._event(db, "runtime_executor_registered", {"endpoint_id": endpoint.id,
                "executor_id": record["executor_id"], "kind": record["kind"], "rationale": rationale})
    return {"database": str(store.path), "registered": added, "endpoint_id": endpoint.id,
            "executor_id": record["executor_id"], "executor": record}


def registered_executors(database: str | Path) -> dict:
    """Read registered records by endpoint ID, without creating a journal or running tools."""
    store = _store(database, read_only=True)
    with store.connection() as db:
        rows = db.execute("SELECT key,body FROM metadata WHERE key LIKE ? ORDER BY key", (_PREFIX + "%",)).fetchall()
    result = {}
    for row in rows:
        record = json.loads(row["body"])
        _identity(record)
        identifier = row["key"][len(_PREFIX):]
        if record["endpoint"]["id"] != identifier:
            raise StateError("executor registry key and endpoint identity disagree")
        result[identifier] = record
    return result


def build_executor(database: str | Path, workspace: str | Path,
                   checkpoint: Callable[[], None] | None = None,
                   process_observer: Callable[[int], None] | None = None,
                   endpoint_ids: tuple[str, ...] | None = None) -> tuple[Callable, Path | None]:
    """Reconstruct only registered dispatchers, preserving all endpoint admission guards."""
    root = absolute(workspace)
    for callback in (checkpoint, process_observer):
        if callback is not None and not callable(callback):
            raise ValueError("executor callbacks must be callable")
    store = _store(database, read_only=True)
    _, endpoints = store.configuration()
    registered = registered_executors(database)
    if endpoint_ids is not None:
        if not endpoint_ids or any(key not in endpoints for key in endpoint_ids):
            raise ValueError("selected executor endpoints must already exist")
        endpoints = {key: endpoints[key] for key in endpoint_ids}
        registered = {key: value for key, value in registered.items() if key in endpoints}
    missing = {key for key, endpoint in endpoints.items() if endpoint.queryable} - registered.keys()
    if missing:
        raise ValueError(f"queryable endpoints have no registered executor: {sorted(missing)}")
    recipes, receptors = {}, set()
    for key, record in registered.items():
        if key not in endpoints or record["endpoint"] != endpoints[key].as_dict():
            raise StateError("registered executor differs from the campaign endpoint")
        _verify(record)
        if record["kind"] == "molcascade":
            recipes[key] = _recipe(record["configuration"])
        else:
            receptors.add(record["configuration"]["receptor_path"])
    if len(receptors) > 1:
        raise ValueError("one active campaign requires a consistent PRISM receptor path")
    cascade = CascadeExecutor(root, recipes)
    receptor_path = Path(next(iter(receptors))) if receptors else None

    def dispatch(action, candidate, endpoint, grant):
        if checkpoint is not None:
            checkpoint()
        record = registered.get(endpoint.id)
        if (record is None or record["endpoint"] != endpoint.as_dict()
                or action.endpoint_id != endpoint.id or action.candidate_id != candidate.id):
            raise ValueError("action is not bound to this registered executor")
        if record["kind"] == "prism_bridge_v1":
            for observation in store.observations():
                if observation["action_id"] == action.id:
                    return Evaluation.from_dict(observation["result"])
        try:
            _verify(record)
        except Exception as error:
            if record["kind"] != "prism_bridge_v1" and not isinstance(error, (OSError, ValueError)):
                raise
            if record["kind"] == "prism_bridge_v1":
                from etalon.active.runner import ExecutionPending

                with store.connection() as db:
                    previous = db.execute("SELECT 1 FROM metadata WHERE key=?",
                                          ("prism-v1:request:" + action.id,)).fetchone()
                if previous:
                    raise ExecutionPending("existing bridge action cannot be reclassified after environment drift") from error
            return Evaluation(candidate.id, endpoint.id, None, endpoint.units, 0.0, status="blocked",
                provenance={"phase": "executor_preflight", "executor_id": record["executor_id"],
                            "error": str(error), "cost_basis": "not dispatched"})
        # Before any kind branch, so that no kind can reach a single-run path while its protocol id
        # claims an aggregation over independent draws. One draw and a ten-draw consensus are
        # indistinguishable in a record that stores neither the policy nor the spread.
        blocked = _aggregation_block(record, endpoint, candidate.id)
        if blocked is not None:
            return blocked
        if record["kind"] == "molcascade":
            result = cascade(action, candidate, endpoint, grant)
        elif record["kind"] == "prism_bridge_v1":
            from etalon.active.runner import ExecutionPending

            writable = CampaignStore(store.path)
            observations = {o["action_id"]: o for o in writable.observations()}
            if action.id in observations:
                return Evaluation.from_dict(observations[action.id]["result"])
            template = record["configuration"]["request_template"]
            if (candidate.id != template["candidate_id"] or candidate.smiles != "c1ccccc1"
                    or action.replicate >= len(record["configuration"]["seeds"])):
                return Evaluation(candidate.id, endpoint.id, None, endpoint.units, 0, status="blocked",
                                  provenance={"error": "UNSUPPORTED: fixed bounded benzene template",
                                              "executor_id": record["executor_id"]})
            try:
                bridge = _bridge(writable, record["configuration"])
                # Record the original authorization for read-only result reconciliation.
                with writable.connection(write=True) as db:
                    db.execute("INSERT OR IGNORE INTO metadata VALUES (?,?)",
                               ("runtime:bridge-authorization:" + action.id, canonical(grant.as_dict() if grant else None)))
                result = bridge(action, candidate, endpoint, grant)
            except ExecutionPending:
                raise
        elif record["kind"] == "prism_mmpbsa_replicated":
            # Refused explicitly, because the alternative is worse than an error. Every kind
            # that is not molcascade or the bridge falls into the legacy branch below, which
            # builds a single PrismStage: a three-replica endpoint would quietly run as one
            # unseeded trajectory per action and report the result under a protocol id that
            # claims recorded seeds and a known energy author. Registration is complete and
            # the frozen inputs stay valid; only dispatch is unwired.
            return Evaluation(candidate.id, endpoint.id, None, endpoint.units, 0.0, status="blocked",
                provenance={"phase": "executor_dispatch", "executor_id": record["executor_id"],
                            "error": "UNSUPPORTED: prism_mmpbsa_replicated is registered but not "
                                     "yet dispatchable; independent-replica MD and gmx_MMPBSA "
                                     "execution are not wired. No trajectory was started.",
                            "cost_basis": "not dispatched"})
        else:
            from etalon.active.adapters import StageExecutor
            from etalon.boundary.simulate import Simulate, discover
            from etalon.campaign.expensive import PrismStage

            config = record["configuration"]

            def factory(authorized_action):
                environment = discover(config["python"])
                simulation = Simulate(root / authorized_action.id, environment,
                                      process_observer=process_observer)
                return PrismStage(simulation, Path(config["receptor_path"]),
                    production_ns=config["production_ns"], timeout_per_molecule=config["timeout_per_molecule"])

            result = StageExecutor({endpoint.id: factory})(action, candidate, endpoint, grant)
        # Stage 1 of STOCHASTIC_MEASUREMENT.md: the policy and its coverage beside the value, so a
        # reader of the record can tell a declared draw count from an authorised one. Reporting
        # only -- the refusal happened above, before anything ran.
        return replace(result, provenance={**result.provenance, "aggregation":
            aggregation_provenance(record, endpoint, candidate_id=candidate.id,
                                   actions=store.actions(), observations=store.observations())})

    return dispatch, receptor_path


def recover_bridge_action(database: str | Path, action) -> Evaluation | None:
    """Reconcile an acknowledged bridge action without spending or resubmitting anything."""
    from etalon.faults.preflight import check_record

    store = _store(database)
    record = registered_executors(database).get(action.endpoint_id)
    if not record or record["kind"] != "prism_bridge_v1":
        return None
    _verify(record)
    with store.connection() as db:
        authorization = db.execute("SELECT body FROM metadata WHERE key=?",
                                   ("runtime:bridge-authorization:" + action.id,)).fetchone()
    if authorization is None:
        return None
    result = _bridge(store, record["configuration"]).read_existing(action)
    if result is None:
        return None
    candidate = store.candidates()[action.candidate_id]
    checks = check_record(candidate.handoff, receptor_path=Path(record["configuration"]["receptor_path"]))
    return replace(result, checks=checks + result.checks, provenance={**result.provenance,
                   "authorization": json.loads(authorization[0]), "endpoint_protocol": record["endpoint"]["protocol"]})
