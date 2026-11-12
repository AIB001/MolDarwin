"""Typed workflow execution, persistent executors and bounded evidence inspection."""

from __future__ import annotations

from typing import Any

from etalon.mcp._common import Cost, absolute_path, ok, threaded_tool, tool


def register(mcp: Any) -> None:
    @mcp.tool()
    @threaded_tool(Cost.CHEAP)
    def etalon_wait_register(declaration: dict[str, Any], workspace: str) -> str:
        """CHEAP. Share bounded observations of an existing task's completion.

        Prefer an existing host background notification. Otherwise use schema
        etalon-host-wait/1 with checks (native_attempt, file or json_status),
        wake_when any/all, poll_seconds and max_checks. Repeated registrations
        in the same workspace reuse the first policy and handle; etalon_action_result
        refreshes it at most once per saved interval across readers. No extra worker,
        scientific dispatch, retry or automatic host notification. A stage and a
        whole-run condition differ.
        """
        from etalon.runtime.host_wait import register_wait

        return ok(**register_wait(declaration, absolute_path(workspace, label="workspace")))

    @mcp.tool()
    @threaded_tool(Cost.FREE)
    def etalon_action_prepare(request: dict[str, Any]) -> str:
        """FREE. Validate and bind one supported host-selected action without dispatch or a skill gate.

        For operation=method.run this also mints the method authorization over the declaration
        -- method_id, argv, the content digests of the declared files, inputs and outputs -- and
        returns the request carrying it at arguments.authorization. Submit the returned `request`
        and `plan_id` verbatim; a token constructed by hand does not verify.
        """
        from etalon.mcp import method_authority
        from etalon.runtime.api import prepare_action

        prepared = prepare_action(request)
        # `.get` rather than `[...]`: this tool delegates and must not assume more of the
        # preparation's shape than it needs. Without a normalized request there is no declaration
        # to mint over, and the response is what it always was.
        normalized = prepared.get("request") if isinstance(prepared, dict) else None
        if normalized is None:
            return ok(prepared=prepared)
        authorized, minted = method_authority.authorize_request(normalized)
        if authorized is not normalized:
            # Re-prepare so the returned plan_id is the one the authorized request plans to.
            # prepare_action is read-only and FREE; a plan_id taken before the token was attached
            # would be stale the moment the host submitted the request this tool told it to.
            prepared = prepare_action(authorized)
        return ok(prepared=prepared, request=prepared["request"],
                  method_authorization=minted,
                  authorization=method_authority.state(prepared["request"]))

    @mcp.tool()
    @threaded_tool(Cost.SPENDS)
    def etalon_action_submit(request: dict[str, Any], workspace: str, plan_id: str,
                             authorization_json: str = "") -> str:
        """SPENDS. Submit a prepared action through existing budget, execution and recovery checks.

        Replays identify the original execution; unresolved results require reconciliation.
        For method.run, pass the request etalon_action_prepare returned -- it already carries its
        authorization. authorization_json is the alternative for a host that kept the original
        request: the `authorization` object from that tool, verbatim. Dispatch rules on it.
        """
        from etalon.mcp import method_authority
        from etalon.runtime.api import submit_action

        request = method_authority.merge(request, method_authority.tokens_from_json(authorization_json))
        return ok(handle=submit_action(request, workspace=workspace, plan_id=plan_id),
                  authorization=method_authority.state(request))

    @mcp.tool()
    @threaded_tool(Cost.FREE)
    def etalon_action_result(handle: dict[str, Any], view: str = "full") -> str:
        """FREE. Read execution, verification, admission and accounting as separate existing facts.

        Also accepts a fixed PRISM handle from execution_recovery.bind_native_handle;
        it verifies the original job/profile and never restarts scientific work.
        A saved etalon-wait-handle/1 reuses a shared observation, refreshing when due.
        Pass the complete handle object returned by etalon_action_submit unchanged. A campaign
        action ID or an offline etalon_active_replay result is not a runtime action handle.
        Inspect replay outcomes through campaign status and campaign events instead.
        For runtime handles, view=summary keeps status, counts, costs and artifact
        locators compact; use full or etalon_workflow_artifact for selected detail.
        """
        from etalon.runtime.api import read_action_result

        return ok(result=read_action_result(handle, view=view))

    @mcp.tool()
    @threaded_tool(Cost.FREE)
    def etalon_events_read(log_ref: dict[str, Any], after_sequence: int | dict[str, Any] = 0,
                          limit: int = 100) -> str:
        """FREE. Page committed events with log identity; this does not run hooks or restart work.

        log_ref is {"kind": "campaign", "database": "/absolute/path/campaign.sqlite"} or
        {"kind": "runtime", "workspace": "/absolute/path/runtime", "job_id": "optional-job-id"}.
        Start with after_sequence=0; for subsequent pages pass the returned cursor unchanged.
        Only campaign and runtime are valid kinds. Paths must name existing logs.
        """
        from etalon.runtime.api import read_events

        return ok(**read_events(log_ref, after_sequence=after_sequence, limit=limit))

    @mcp.tool()
    @tool(Cost.FREE)
    def etalon_workflow_capabilities() -> str:
        """FREE. List registered workflow operations and their required/optional argument names.

        Workflows use explicit dependencies and {$ref: node.output} references. The controller
        selects ready nodes; fixed service validators establish completion from real artifacts.
        """
        from etalon.runtime.operations import describe
        from etalon.runtime.service import capabilities

        return ok(operations=describe(), workflow_schema="etalon-workflow/1",
                  controller_modes=["ordered", "advisor", "external"], execution=capabilities())

    @mcp.tool()
    @threaded_tool(Cost.CHEAP)
    def etalon_executor_prepare(kind: str, configuration: dict[str, Any],
                                 endpoint: dict[str, Any]) -> str:
        """CHEAP. Freeze molcascade, legacy prism or independent prism_bridge_v1 without dispatch.

        MolCascade needs cascade/readout; PRISM needs absolute receptor_path/python and explicit
        production_ns. Returns a prepared executor to use for campaign creation and registration.
        """
        from etalon.runtime.executors import prepare_executor

        return ok(executor=prepare_executor(kind, configuration, endpoint))

    @mcp.tool()
    @threaded_tool(Cost.CHEAP)
    def etalon_executor_register(database: str, prepared: dict[str, Any], rationale: str) -> str:
        """CHEAP. Register a prepared immutable executor against an exactly matching campaign endpoint.

        Revalidates scientific inputs; repeats are idempotent. Creates no campaign or experiment.
        """
        from etalon.runtime.executors import register_executor

        return ok(**register_executor(absolute_path(database, label="database"), prepared, rationale))

    @mcp.tool()
    @tool(Cost.FREE)
    def etalon_executor_list(database: str) -> str:
        """FREE. Read registered executor records by endpoint ID from an existing campaign."""
        from etalon.runtime.executors import registered_executors

        return ok(executors=registered_executors(absolute_path(database, label="database")))

    @mcp.tool()
    @threaded_tool(Cost.CHEAP)
    def etalon_screen_configure(workspace: str, configuration: dict[str, Any]) -> str:
        """CHEAP. Validate and save an immutable caller-specified MolCascade configuration.

        Accepts kind=cascade or schema=etalon-cascade-design/1 with name and explicit tiers.
        Returns configuration and config_path; no scientific hierarchy or threshold is invented.
        """
        from etalon.runtime.artifacts import configure

        return ok(**configure(absolute_path(workspace, label="workspace"), configuration))

    @mcp.tool()
    @threaded_tool(Cost.CHEAP)
    def etalon_workflow_plan(spec: dict[str, Any]) -> str:
        """CHEAP. Validate a typed workflow graph, resources and immutable input hashes without execution.

        Returns normalized spec and plan_id. Resource quotes are explicit; only supported usage
        receipts establish actual consumption. Existing active journals remain mutable.
        Every method.run node is also minted a method authorization over its declaration; submit
        the returned spec and plan_id verbatim. A node whose arguments still carry a {$ref} gets
        none and is reported as not taken, because its declaration is not final yet.
        """
        from etalon.mcp import method_authority
        from etalon.runtime.service import plan

        planned = plan(spec)
        normalized = planned.get("spec") if isinstance(planned, dict) else None
        if normalized is None:
            return ok(**planned)
        authorized, minted = method_authority.authorize_spec(normalized)
        if authorized is not normalized:
            planned = plan(authorized)
        return ok(**planned, method_authorization=minted,
                  authorization=method_authority.state(planned["spec"]))

    @mcp.tool()
    @threaded_tool(Cost.SPENDS)
    def etalon_workflow_submit(spec: dict[str, Any], workspace: str, job_id: str, plan_id: str,
                               authorization_json: str = "") -> str:
        """SPENDS. Submit the reviewed plan to a durable local worker within its declared scope.

        May run real data acquisition, screening, active learning or registered PRISM execution.
        Same job ID and plan return the existing job. External mode waits for explicit decisions.
        Use etalon_workflow_status, etalon_workflow_observe and etalon_workflow_artifact; client disconnection does not stop the worker.
        Submit the spec etalon_workflow_plan returned -- its method.run nodes already carry their
        authorizations. authorization_json is the alternative: a {node_id: authorization} map from
        that tool, verbatim. Dispatch rules on it, per node, including nodes added later by
        etalon_workflow_advance.
        """
        from etalon.mcp import method_authority
        from etalon.runtime.service import submit

        spec = method_authority.merge(spec, method_authority.tokens_from_json(authorization_json))
        return ok(job=submit(spec, absolute_path(workspace, label="workspace"), job_id=job_id,
                             expected_plan_id=plan_id),
                  authorization=method_authority.state(spec))

    @mcp.tool()
    @tool(Cost.FREE)
    def etalon_workflow_status(workspace: str, job_id: str) -> str:
        """FREE. Inspect durable node states, resource usage, worker identity and reconciliation needs."""
        from etalon.runtime.service import status

        return ok(job=status(absolute_path(workspace, label="workspace"), job_id))

    @mcp.tool()
    @tool(Cost.FREE)
    def etalon_workflow_observe(workspace: str, job_id: str) -> str:
        """FREE. Read the identified controller observation with ready nodes and verified result summaries.

        External controllers submit exactly observation_id/node_id/reason through etalon_workflow_advance.
        A model's finish request cannot replace verification of every required node.
        """
        from etalon.runtime.service import observe

        return ok(**observe(absolute_path(workspace, label="workspace"), job_id))

    @mcp.tool()
    @threaded_tool(Cost.SPENDS)
    def etalon_workflow_advance(workspace: str, job_id: str, proposal: dict[str, Any],
                                authorization_json: str = "") -> str:
        """SPENDS. Advance an external decision or queue a side-channel revision for an ordered worker.

        External mode: proposal contains observation_id, node_id, reason, selecting a ready node.
        Ordered mode: {kind:"revise", revision_id, expected_plan_id, nodes, reason, remove_nodes?}.
        Copy expected_plan_id from status.plan.revision_id. Nodes are full replacement/addition
        definitions. Applies at a node boundary, only to unstarted work, within existing limits.
        Current computation continues without waiting for this optional advice. Retries with the
        same revision_id are idempotent. Single actions remain immutable. Inspect revision events
        to distinguish queued, applied and too-late suggestions; no automatic model invocation.
        A revision that adds or replaces a method.run node is how new host-authored argv enters a
        running job, and dispatch rules on that node's authorization like any other. Nothing is
        minted here: run the node's declaration through etalon_workflow_plan (CHEAP, read-only --
        a token binds the declaration, not the job) and pass {node_id: authorization} as
        authorization_json.
        """
        from etalon.mcp import method_authority
        from etalon.runtime.service import advance

        # Deliberately a merge and not a mint. A spending tool that issued its own authorization
        # would be authorising itself, which is ADR 0006's almost-guard with a signature attached:
        # the model types new argv, the tool stamps it, and the stamp establishes nothing.
        proposal = method_authority.merge(proposal, method_authority.tokens_from_json(authorization_json))
        return ok(job=advance(absolute_path(workspace, label="workspace"), job_id, proposal),
                  authorization=method_authority.state(proposal))

    @mcp.tool()
    @tool(Cost.CHEAP)
    def etalon_workflow_cancel(workspace: str, job_id: str, reason: str) -> str:
        """CHEAP. Request cancellation with a reason; retain uncertain results and resource reservations.

        Cancellation does not imply all scientific processes have stopped. Inspect status and
        reconcile their actual outcomes before resuming or releasing uncertain expenditure.
        """
        from etalon.runtime.service import cancel

        return ok(job=cancel(absolute_path(workspace, label="workspace"), job_id, reason=reason))

    @mcp.tool()
    @threaded_tool(Cost.SPENDS)
    def etalon_workflow_reconcile(workspace: str, job_id: str, reason: str,
                                   resume: bool = False,
                                   settlements: dict[str, Any] | None = None) -> str:
        """SPENDS when resume=true. Reconcile saved receipts only after the worker and children stop.

        Defaults to inspection/reconciliation without new dispatch. Unknown outcomes keep their
        reservations; explicit failure settlements need documented costs and an existing evidence
        file in the step workspace. Never invent a scientific value to resolve an interruption.
        """
        from etalon.runtime.service import reconcile

        return ok(job=reconcile(absolute_path(workspace, label="workspace"), job_id, reason=reason,
                                resume=resume, settlements=settlements))

    @mcp.tool()
    @threaded_tool(Cost.CHEAP)
    def etalon_workflow_artifact(workspace: str, job_id: str, node_id: str, kind: str = "result",
                                  member: str = "", artifact_id: str = "", contract_id: str = "",
                                  offset: int = 0, limit: int = 100) -> str:
        """CHEAP. Read a bounded page of a node result, sealed snapshot member or recorded screen artifact.

        kind=result supports a JSON Pointer in member; kind=snapshot lists sealed members or reads
        one relative member; kind=screen requires its recorded artifact_id and optional contract_id.
        No arbitrary host path is read. Use next_offset for pagination; output stays below 1 MiB.
        """
        from etalon.runtime.service import read_artifact

        return ok(**read_artifact(absolute_path(workspace, label="workspace"), job_id, node_id,
                  kind=kind, member=member, artifact_id=artifact_id, contract_id=contract_id,
                  offset=offset, limit=limit))

    @mcp.tool()
    @threaded_tool(Cost.CHEAP)
    def etalon_active_execution_plan(database: str, max_rounds: int = 1,
                                      min_new_admitted: int = 1, max_seconds: float = 3600) -> str:
        """CHEAP. Plan a single active.run workflow using registered executors and the remaining budget.

        Does not execute. Explicit max_rounds/min_new_admitted fix the task's limits and success
        requirement. The active policy selects candidates from the journal at dispatch time.
        """
        from etalon.runtime.api import active_execution_plan

        return ok(**active_execution_plan(absolute_path(database, label="database"),
                  max_rounds=max_rounds, min_new_admitted=min_new_admitted, max_seconds=max_seconds))

    @mcp.tool()
    @threaded_tool(Cost.SPENDS)
    def etalon_active_submit(database: str, workspace: str, job_id: str, plan_id: str,
                              max_rounds: int = 1, min_new_admitted: int = 1,
                              max_seconds: float = 3600) -> str:
        """SPENDS. Dispatch the reviewed active execution plan through the persistent workflow worker.

        Requires registered executors. Reuses the existing active policy, authorization, QC and
        budget journal; success requires new admitted observations. Inspect/cancel/reconcile with
        the workflow tools. Identical submissions reuse the existing job even after completion.
        """
        from etalon.runtime.api import active_submit

        return ok(job=active_submit(absolute_path(database, label="database"),
                  absolute_path(workspace, label="workspace"), job_id=job_id,
                  expected_plan_id=plan_id, max_rounds=max_rounds,
                  min_new_admitted=min_new_admitted, max_seconds=max_seconds))
