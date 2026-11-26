"""Thin access to method provenance in the existing scientific journal."""
from __future__ import annotations

from typing import Any

from moldarwin.mcp._common import Cost, absolute_path, ok, tool


def register(mcp: Any) -> None:
    @mcp.tool()
    @tool(Cost.FREE)
    def moldarwin_resource_feedback(entry: str | dict, resource_id: str,
                                  query: dict | None = None,
                                  branch_id: str | None = None,
                                  resource_version: str | None = None,
                                  offset: int = 0, limit: int = 20,
                                  max_bytes: int = 8192) -> str:
        """FREE. Read conditional method-use feedback from one pinned note.

        Compare cases with query/current version; page with next_read. Costs,
        contrary observations and feedback on older versions remain visible.
        Counts cover returned cases only. No execution or adoption occurs.
        """
        from moldarwin.mcp.evidence import _entry_argument
        from moldarwin.research.resource_selection import read_resource_feedback
        return ok(**read_resource_feedback(_entry_argument(entry), resource_id,
            query=query, branch_id=branch_id, resource_version=resource_version,
            offset=offset, limit=limit, max_bytes=max_bytes))

    @mcp.tool()
    @tool(Cost.CHEAP)
    def moldarwin_method_publish(entry: str, resource_id: str, arguments: dict,
                              summary: str, conditions: dict,
                              branch_id: str | None = None, publication_id: str | None = None,
                              evidence: list[str] | None = None,
                              counterevidence: list[str] | None = None, parts: list[dict] | None = None,
                              family: str | None = None, definitions: dict | None = None,
                              applicable_when: str | None = None,
                              invalid_when: list[str] | None = None,
                              comparison_ref: dict | None = None) -> str:
        """CHEAP. Save a callable method in the existing entry's resource catalog.

        arguments is the existing method.run contract (command argv, files,
        method_id, inputs, optional input_files/outputs/cwd). Pins declared files; preserves
        other resources and contrary evidence. Optional applicable_when, invalid_when, and
        comparison_ref surface reuse boundaries and paired comparison refs on recall.
        No execution or adoption occurs. Programs accept --request/--result.
        """
        from moldarwin.research.saved_methods import publish_method
        return ok(**publish_method(absolute_path(entry, label="entry"), resource_id, arguments,
            summary=summary, conditions=conditions, branch_id=branch_id,
            publication_id=publication_id, evidence=evidence or (), counterevidence=counterevidence or (),
            parts=parts, family=family, definitions=definitions,
            applicable_when=applicable_when, invalid_when=invalid_when,
            comparison_ref=comparison_ref))

    @mcp.tool()
    @tool(Cost.FREE)
    def moldarwin_method_resolve(entry: str | dict, pointer: str, branch_id: str | None = None,
                              invocation: dict | None = None, max_bytes: int = 16384,
                              query: dict | None = None) -> str:
        """FREE. Read one catalog method; optionally return a ready action request.

        invocation={request_id, limits, inputs?, input_files?, executable?, max_seconds?}. Verifies source
        originals, mints a MethodAuthorization onto the prepared request, and uses ordinary action
        preflight; does not run or optimize. Send the returned request to moldarwin_action_submit
        with a workspace (or pass the minted authorization verbatim as authorization_json to
        moldarwin_method_call), then recover its handle. Use catalog content_ref to pin a historical
        version.
        """
        from moldarwin.mcp import method_authority
        from moldarwin.mcp.evidence import _entry_argument
        from moldarwin.research.saved_methods import resolve_saved_method

        resolved = resolve_saved_method(
            _entry_argument(entry), pointer, branch_id=branch_id,
            invocation=invocation, max_bytes=max_bytes, query=query,
            authorize=invocation is not None,
        )
        if "authorized_request" in resolved:
            auth_token = resolved["authorized_request"].get("arguments", {}).get("authorization")
            resolved = {
                **resolved,
                "authorization": method_authority.state(resolved["authorized_request"]),
                **({"authorization_token": auth_token} if isinstance(auth_token, dict) else {}),
            }
        return ok(**resolved)

    @mcp.tool()
    @tool(Cost.SPENDS)
    def moldarwin_method_call(entry: str, pointer: str, invocation: dict, workspace: str,
                           branch_id: str | None = None, query: dict | None = None,
                           authorization_json: str = "") -> str:
        """SPENDS. Call a chosen saved method and remember its handle automatically.

        Optional convenience over resolve/submit. Uses the existing action budget
        and request identity; a repeated request recovers the same execution.
        Pass ``authorization_token`` returned by ``moldarwin_method_resolve`` verbatim as
        ``authorization_json``; dispatch rules on it (and never mints one on the caller's behalf).
        Returns invocation_path for moldarwin_method_collect. No research graph,
        method evaluation or additional model call is required.
        """
        from moldarwin.mcp import method_authority
        from moldarwin.research.saved_methods import call_saved_method

        tokens = method_authority.tokens_from_json(authorization_json)
        if tokens and "action" not in tokens:
            raise ValueError(
                "authorization_json for moldarwin_method_call must be authorization_token "
                "returned by moldarwin_method_resolve (or {\"action\": <token>})"
            )
        token = tokens.get("action") if tokens else None
        return ok(**call_saved_method(
            absolute_path(entry, label="entry"), pointer,
            invocation=invocation, workspace=absolute_path(workspace, label="workspace"),
            branch_id=branch_id, query=query, authorization=token,
        ))

    @mcp.tool()
    @tool(Cost.CHEAP)
    def moldarwin_method_collect(invocation_path: str) -> str:
        """CHEAP. Read an existing method call and save its result/cost references.

        Never submits or repeats computation. Updates only this call's pending
        handle and resource in its original note; preserves the host's judgment.
        An archival problem is reported separately from the execution outcome.
        output_summaries preserves the method's conclusion, compact feedback and
        real failure details even when bulk outputs require a separate read.
        """
        from moldarwin.research.saved_methods import collect_saved_method
        return ok(**collect_saved_method(absolute_path(invocation_path, label="invocation_path")))

    @mcp.tool()
    @tool(Cost.FREE)
    def moldarwin_method_criterion(contract: dict | None = None, contract_ref: dict | None = None,
                                workspace: str | None = None, entry: str | dict | None = None,
                                read_context: dict | None = None) -> str:
        """FREE. Read the acceptance criterion before working: rules, never a verdict.

        Supply contract xor exact contract_ref, and for a ref one workspace/entry/read_context.
        Returns each judged quantity with its measure, operator, threshold, the provenance
        of that threshold, and what the metric punishes -- including that a set-similarity
        bar punishes an extra feature as well as a missing one. Also the status vocabulary
        and that the worst status wins, so a passing cost metric never erases a failing
        quality metric. Read this before the first iteration and recompute each metric
        yourself as you work. Only the contract's own ref is resolved: no input bytes, no
        recorded result and no verdict. Use moldarwin_method_evaluate for a replay against
        verified originals.
        """
        from moldarwin.mcp.evidence import _entry_argument
        from moldarwin.research.contract_spec import specification
        return ok(**specification(
            contract, contract_ref=contract_ref,
            workspace=absolute_path(workspace, label="workspace") if workspace is not None else None,
            entry=_entry_argument(entry), read_context=read_context))

    @mcp.tool()
    @tool(Cost.FREE)
    def moldarwin_method_evaluate(contract: dict | None = None, contract_ref: dict | None = None,
                               workspace: str | None = None, entry: str | dict | None = None,
                               read_context: dict | None = None) -> str:
        """FREE. Replay optional fixed evaluation rules over verified original results.

        Supply contract xor exact contract_ref, and one workspace/entry/read_context.
        Separate regression, retention, funnel and cost. Missing inputs and unequal
        protocol/check coverage cannot pass. No science, adoption, activation or
        memory write occurs; retrospective replay is not independent validation.
        """
        from moldarwin.mcp.evidence import _entry_argument
        from moldarwin.research.evaluation_contract import evaluate_contract
        return ok(**evaluate_contract(
            absolute_path(workspace, label="workspace") if workspace is not None else None,
            contract, contract_ref=contract_ref, entry=_entry_argument(entry),
            read_context=read_context))

    @mcp.tool()
    @tool(Cost.CHEAP)
    def moldarwin_resource_usage_record(database: str, record: dict[str, Any], directory: str,
                                    source_id: str, source_kind: str,
                                    workspace: str | None = None) -> str:
        """CHEAP. Append validated resource-use attribution as an ordinary Artifact.

        The payload is built with research.resource_usage.build_resource_usage.
        Exact workset/resource part, method, use, node and evaluation references
        are verified before recording. Historical links cannot manufacture past
        consumption. Does not select a branch, run science or activate a skill.
        """
        from moldarwin.active.store import CampaignStore
        from moldarwin.research.journal import ResearchJournal
        from moldarwin.research.resource_usage import record_resource_usage, validate_resource_usage
        payload = validate_resource_usage(record)
        database = absolute_path(database, label="database")
        directory = absolute_path(directory, label="directory")
        workspace = absolute_path(workspace, label="workspace") if workspace is not None else None
        journal = ResearchJournal(CampaignStore(database))
        identifier = record_resource_usage(journal, payload, directory, source_id=source_id,
                                           source_kind=source_kind, workspace=workspace)
        return ok(record_id=identifier, record=journal.get(identifier))

    @mcp.tool()
    @tool(Cost.CHEAP)
    def moldarwin_method_record(database: str, record: dict[str, Any]) -> str:
        """CHEAP. Append a validated method version, use or evaluation to the existing journal.

        Saving provenance does not execute a method, admit an observation or establish improvement.
        """
        from moldarwin.active.store import CampaignStore
        from moldarwin.research.journal import ResearchJournal
        from moldarwin.research.schema import method_record_from_dict

        value = method_record_from_dict(record)
        journal = ResearchJournal(CampaignStore(absolute_path(database, label="database")))
        identifier = journal.record(value)
        return ok(record_id=identifier, record=journal.get(identifier))

    @mcp.tool()
    @tool(Cost.FREE)
    def moldarwin_method_read(database: str, record_id: str) -> str:
        """FREE. Read an immutable method record without inferring actual use or scientific benefit."""
        from moldarwin.active.store import CampaignStore
        from moldarwin.research.journal import ResearchJournal
        from moldarwin.research.schema import method_record_from_dict

        store = CampaignStore(absolute_path(database, label="database"), read_only=True)
        record = ResearchJournal(store).get(record_id)
        method_record_from_dict(record)
        return ok(record_id=record_id, record=record)

    @mcp.tool()
    @tool(Cost.FREE)
    def moldarwin_revision_compare(
        assessment_role: str,
        declared_scope: list[str],
        dimensions: list[dict[str, Any]] | None = None,
        measured_scope: list[str] | None = None,
        base_catalogue_digest: str | None = None,
        candidate_catalogue_digest: str | None = None,
        base_view: dict[str, Any] | None = None,
        candidate_view: dict[str, Any] | None = None,
        task_nodes: dict[str, Any] | None = None,
        alpha: float = 0.05,
        detail: str = "summary",
    ) -> str:
        """FREE. Paired Pareto comparison of a candidate method or skill against its baseline.

        Computes exact sign/McNemar tests per dimension across warrant, refusal, coverage,
        provenance, and cost without collapsing them into one scalar score. A cost saving
        never pays for a quality or warrant regression; waivers are tracked as cost, not wins;
        and diagnostic measurements are capped at diagnostic_only.

        Optionally pass base_view + candidate_view (either verbatim derived views or
        workspace/entry selectors) plus task_nodes ({task_id: node_id} or
        {task_id: {"base": ..., "candidate": ...}}) to extract paired warrant observations
        and fault-catalogue digests automatically. Defaults to detail='summary' for compact
        token usage; pass detail='full' for the complete comparison object accepted by
        resolve_method_revision. Never modifies records or promotes a method.
        """
        from moldarwin.economics.stage import Evidence
        from moldarwin.mcp.evidence import _entry_argument
        from moldarwin.research.admission_bindings import build_admission_view
        from moldarwin.research.revision_score import (
            Dimension,
            Family,
            compact_comparison,
            compare_revision,
            warrant_observations_from_admission_view,
        )

        if detail not in {"summary", "full"}:
            raise ValueError("detail must be 'summary' or 'full'")

        def _resolve_view(spec: dict[str, Any]) -> dict[str, Any]:
            if not isinstance(spec, dict):
                raise ValueError("view input must be a mapping")
            if "nodes" in spec and "catalogue_digest" in spec:
                return spec
            ws = spec.get("workspace")
            return build_admission_view(
                absolute_path(ws, label="workspace") if ws is not None else None,
                checkpoint_ref=spec.get("checkpoint_ref"),
                entry=_entry_argument(spec["entry"]) if "entry" in spec else None,
                read_context=spec.get("read_context"),
                policy=spec.get("policy"),
                purpose=spec.get("purpose"),
                labels=spec.get("labels"),
                extra_bindings=spec.get("bindings"),
                scope=spec.get("scope"),
                detail="full",
            )["view"]

        parsed: list[tuple[Dimension, dict[str, Any], dict[str, Any]]] = []
        base_digest = base_catalogue_digest
        cand_digest = candidate_catalogue_digest

        if base_view is not None or candidate_view is not None:
            if base_view is None or candidate_view is None or not task_nodes:
                raise ValueError("base_view, candidate_view, and task_nodes must be supplied together")
            b_map: dict[str, str] = {}
            c_map: dict[str, str] = {}
            for task_id, target in task_nodes.items():
                if isinstance(target, str):
                    b_map[task_id] = target
                    c_map[task_id] = target
                elif isinstance(target, dict) and set(target) == {"base", "candidate"}:
                    b_map[task_id] = target["base"]
                    c_map[task_id] = target["candidate"]
                else:
                    raise ValueError(
                        f"task_nodes[{task_id!r}] must be a node_id string or "
                        "{'base': node_id, 'candidate': node_id}"
                    )
            b_warrant, b_cat = warrant_observations_from_admission_view(_resolve_view(base_view), b_map)
            c_warrant, c_cat = warrant_observations_from_admission_view(_resolve_view(candidate_view), c_map)
            if base_digest is not None and base_digest != b_cat:
                raise ValueError("base_catalogue_digest disagrees with base_view catalogue_digest")
            if cand_digest is not None and cand_digest != c_cat:
                raise ValueError("candidate_catalogue_digest disagrees with candidate_view catalogue_digest")
            base_digest, cand_digest = b_cat, c_cat
            parsed.append((Dimension("warrant", Family.WARRANT), b_warrant, c_warrant))

        for entry_dim in dimensions or ():
            if not isinstance(entry_dim, dict):
                raise ValueError("each dimension entry must be an object")
            dim = Dimension(
                name=entry_dim["name"],
                family=Family(entry_dim["family"]),
                minimum_gain=entry_dim.get("minimum_gain", 0.0),
                minimum_gain_evidence=Evidence(entry_dim.get("minimum_gain_evidence", "convention")),
                minimum_gain_source=entry_dim.get("minimum_gain_source", ""),
                unit=entry_dim.get("unit", ""),
            )
            parsed.append((dim, entry_dim["base"], entry_dim["candidate"]))

        comparison = compare_revision(
            dimensions=parsed,
            assessment_role=assessment_role,
            base_catalogue_digest=base_digest or "",
            candidate_catalogue_digest=cand_digest or "",
            declared_scope=declared_scope,
            measured_scope=measured_scope or (),
            alpha=alpha,
        )
        payload = compact_comparison(comparison) if detail == "summary" else comparison.as_dict()
        return ok(detail=detail, comparison=payload)
