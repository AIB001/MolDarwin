"""End-to-end tests for MolDarwin v2.2 architectural upgrades.

Covers:
  1. Executable bond-consistent RBFE atom-mapping guard (catches rewired bonds/rings/H
     parents on SND1 C26-A2 <-> C26-A6 and repairs via ring-preserving MCS to 0/0 mismatches)
     plus shallow-PPI physics escalation planner & Fault-RSI registry integration.
  2. Code-enforced ComputeLease (POSIX flock single-dispatcher lock, forbidden/unleased GPU
     refusal, cumulative CPU thread cap, k=6 high-VRAM Blackwell auto-packing, telemetry
     audit, and visible 429 exponential backoff).
  3. Read-only 4-checkpoint Sidecar Auditor (CP1-CP4 deterministic checks, clean-context
     Scripted LLM critic monotonic safety guarantee, append-only resolution ledger, and
     FREE ``moldarwin_sidecar_audit`` governance MCP tool).
  4. Streaming local building-block catalog indexer (.smi.gz -> SQLite) and catalog-constrained
     ``enumerate_reaction_analogs`` verifying 2/2 purchasable partners from birth.
"""

from __future__ import annotations

import gzip
import json

import pytest

from moldarwin.evolve import (
    CATALOG_INDEX_SCHEMA,
    build_building_block_index,
    enumerate_reaction_analogs,
    infer_complementary_buckets,
    lookup_exact_smiles,
    query_building_blocks,
)
from moldarwin.judgment import (
    SIDECAR_CHECKPOINTS,
    SIDECAR_RESOLUTION_SCHEMA,
    SIDECAR_REVIEW_SCHEMA,
    Scripted,
    record_advisory_resolution,
    run_deterministic_sidecar_audit,
    run_sidecar_review,
)
from moldarwin.physics import (
    RBFE_MAPPING_AUDIT_SCHEMA,
    SHALLOW_PPI_PROTOCOL_SCHEMA,
    plan_shallow_ppi_physics_protocol,
    verify_bond_consistent_atom_mapping,
)
from moldarwin.research.fault_rsi import FaultRSIRegistry
from moldarwin.runtime.concurrency import plan_gpu_packing
from moldarwin.runtime.lease import (
    COMPUTE_LEASE_SCHEMA,
    LEASE_AUDIT_SCHEMA,
    RETRY_BACKOFF_SCHEMA,
    ComputeLease,
    LeaseConflictError,
    LeaseViolationError,
    RetryBackoffPolicy,
    run_with_backoff,
)

# Real SND1-MTDH crystal controls: C26-A2 (7KNW/QOY) and C26-A6 (7KNX/QOV)
C26_A2_SMILES = "COc1ccc(Cl)cc1S(=O)(=O)Nc1cccn2ncnc12"
C26_A6_SMILES = "COc1ccc(Cl)cc1S(=O)(=O)Nc1cccn2nc(C)nc12"


def test_bond_consistent_rbfe_mapping_guard_catches_corrupted_map_and_synthesizes_clean_mcs():
    # 1. Clean MCS on C26-A2 <-> C26-A6 preserves the entire 22-heavy-atom core with 0 mismatches
    clean = verify_bond_consistent_atom_mapping(C26_A2_SMILES, C26_A6_SMILES)
    assert clean["schema"] == RBFE_MAPPING_AUDIT_SCHEMA
    assert clean["passed_gate"] is True
    assert clean["verdict"] == "mcs_mapping_verified"
    assert clean["mcs_heavy_core_size"] == 22
    assert clean["mcs_core_coverage"] == pytest.approx(1.0)
    assert clean["mcs_ablation"]["heavy_connectivity_or_order_mismatches"] == 0
    assert clean["mcs_ablation"]["hydrogen_neighbor_mismatch_count"] == 0

    # 2. Simulate a broken distance-only mapping by scrambling two carbon indices on the ring
    corrupted = [tuple(pair) for pair in clean["recommended_heavy_mapping"]]
    # Swap target indices of pair 2 and pair 10 (rewiring conserved bonds!)
    a1, b1 = corrupted[2]
    a2, b2 = corrupted[10]
    corrupted[2] = (a1, b2)
    corrupted[10] = (a2, b1)

    audit = verify_bond_consistent_atom_mapping(
        C26_A2_SMILES,
        C26_A6_SMILES,
        proposed_mapping=corrupted,
    )
    assert audit["passed_gate"] is False
    assert audit["verdict"] == "proposed_mapping_rejected_use_mcs"
    assert audit["proposed_ablation"]["heavy_connectivity_or_order_mismatches"] > 0
    assert audit["mcs_ablation"]["passed"] is True
    assert audit["mcs_ablation"]["heavy_connectivity_or_order_mismatches"] == 0


def test_shallow_ppi_protocol_planner_and_fault_rsi_registration():
    plan = plan_shallow_ppi_physics_protocol(
        control_md_tail_rmsd_A=3.95,
        control_rbfe_overlap_min=0.0044,
        control_rbfe_grid_shift_kcal=2.753,
        control_rbfe_sign_flip=True,
        crystal_water_site_occupancy=0.0,
        mapping_heavy_mismatches=36,
        mpi_available=True,
    )
    assert plan["schema"] == SHALLOW_PPI_PROTOCOL_SCHEMA
    assert plan["dispatch_gate"] == "hold_candidate_rbfe"
    assert plan["candidate_rbfe_allowed"] is False
    steps = {a["step"] for a in plan["protocol_actions"]}
    assert "enforce_bond_consistent_mcs_mapping" in steps
    assert "add_boresch_or_flat_bottom_orientational_restraints" in steps
    assert "reject_unverified_wet_bridge_rescue" in steps
    assert "escalate_alchemical_sampling" in steps
    esc = next(a for a in plan["protocol_actions"] if a["step"] == "escalate_alchemical_sampling")
    assert esc["sampling_mode"] == "hrex_multidir_replex"

    # Passing controls unlock candidate RBFE
    ok_plan = plan_shallow_ppi_physics_protocol(
        control_md_tail_rmsd_A=1.2,
        control_rbfe_overlap_min=0.14,
        control_rbfe_grid_shift_kcal=0.2,
        control_rbfe_sign_flip=False,
        mapping_heavy_mismatches=0,
    )
    assert ok_plan["dispatch_gate"] == "ready_for_candidate_rbfe"
    assert ok_plan["candidate_rbfe_allowed"] is True

    # FaultRSIRegistry recognizes both new empirical failure signatures
    reg = FaultRSIRegistry()
    m_map = reg.match("endpoint graph ablation found 36 heavy-pair connectivity mismatch")
    assert any(h["remediation_id"] == "prism_rbfe_mapping_bond_mismatch" for h in m_map["matches"])
    m_ppi = reg.match("Dispatch state: design_rbfe_held_control_gate after sign flip 2.75 kcal")
    assert any(h["remediation_id"] == "shallow_ppi_rbfe_control_gate_hold" for h in m_ppi["matches"])


def test_compute_lease_prevents_duplicate_dispatchers_forbidden_gpus_and_enables_k6_packing(tmp_path):
    # Forbidden GPU guard in plan_gpu_packing
    with pytest.raises(ValueError, match="forbidden GPU"):
        plan_gpu_packing([0, 4], cpu_cores=64, forbidden_gpus=[4, 5, 6, 7])

    # High-VRAM 96 GB Blackwell packing reaches k=6 when single-job SM util is 13.5%
    packed = plan_gpu_packing(
        [2, 3],
        cpu_cores=48,
        mem_per_job_mb=650.0,
        gpu_vram_mb=98304.0,
        single_job_sm_util_pct=13.5,
        max_jobs_per_gpu=8,
        forbidden_gpus=[4, 5, 6, 7],
    )
    assert packed["jobs_per_gpu"] == 6
    assert packed["total_concurrent_slots"] == 12
    assert packed["omp_threads_per_slot"] == 4
    assert packed["total_cpus_assigned"] == 48

    # Exclusive POSIX flock prevents duplicate dispatcher in same run root
    with ComputeLease(
        tmp_path,
        campaign_id="snd1-v22",
        allowed_gpus=[0, 1, 2, 3],
        forbidden_gpus=[4, 5, 6, 7],
        max_cpu_threads=64,
    ) as lease:
        snap = lease.snapshot()
        assert snap["schema"] == COMPUTE_LEASE_SCHEMA
        assert snap["allowed_gpus"] == [0, 1, 2, 3]

        # Second dispatcher must fail immediately
        dup = ComputeLease(
            tmp_path,
            campaign_id="snd1-dup",
            allowed_gpus=[0, 1],
            max_cpu_threads=32,
        )
        with pytest.raises(LeaseConflictError, match="duplicate dispatcher refused"):
            dup.acquire()

        # Forbidden GPU launch refused
        with pytest.raises(LeaseViolationError, match="forbidden GPU"):
            lease.validate_worker_launch(gpu_ids=[6], cpu_threads=8, worker_id="w_bad")

        # Cumulative CPU cap breach refused
        env1 = lease.register_worker("w1", gpu_ids=[0], cpu_threads=40, pid=111)
        assert env1 == {"OMP_NUM_THREADS": "40", "CUDA_VISIBLE_DEVICES": "0"}
        with pytest.raises(LeaseViolationError, match="CPU thread cap breach"):
            lease.register_worker("w2", gpu_ids=[1], cpu_threads=32, pid=222)
        lease.release_worker("w1")

        # Lease-scoped slot packing stays strictly inside allowed GPUs and max_cpu_threads
        slots = lease.plan_packed_slots(mem_per_job_mb=650.0, single_job_sm_util_pct=14.0)
        assert set(slots["idle_gpus"]) == {0, 1, 2, 3}
        assert slots["total_cpus_assigned"] <= 64

        # Telemetry audit detects forbidden GPU + duplicate dispatcher + CPU breach + underutilization
        audit = lease.audit_telemetry(
            campaign_gpu_pids={0: [101], 7: [999]},
            configured_cpu_threads=72,
            active_dispatchers=2,
            gpu_util_by_id={0: 32.0},
            gpu_vram_frac_by_id={0: 0.02},
        )
        assert audit["schema"] == LEASE_AUDIT_SCHEMA
        assert audit["compliant"] is False
        vcodes = {v["code"] for v in audit["violations"]}
        assert vcodes == {"duplicate_dispatcher", "cpu_cap_breach", "forbidden_gpu_occupied"}
        assert audit["warnings"][0]["code"] == "gpu_under_utilized"

    # Transient 429 backoff retries visibly and succeeds
    calls = {"n": 0}
    slept: list[float] = []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("HTTP 429 Too Many Requests")
        return "done"

    val, log = run_with_backoff(
        flaky,
        policy=RetryBackoffPolicy(max_attempts=4, initial_delay_s=30.0, backoff_factor=2.0, max_delay_s=120.0),
        sleep_fn=slept.append,
    )
    assert val == "done"
    assert log["schema"] == RETRY_BACKOFF_SCHEMA
    assert log["retries"] == 2
    assert slept == [30.0, 60.0]


def test_sidecar_auditor_all_four_checkpoints_monotonic_llm_critic_and_mcp_tool(tmp_path):
    assert len(SIDECAR_CHECKPOINTS) == 4

    # CP1: catches HTML/reCAPTCHA file and mixed Kd/IC50 pooling
    cp1 = run_deterministic_sidecar_audit(
        "CP1_TARGET_DATA",
        {
            "input_file_snippets": [{"path": "supplement.xls", "head_text": "<!DOCTYPE html><div class='g-recaptcha'>"}],
            "assay_endpoints": ["MST Kd", "split-Luc IC50"],
            "pooled_into_single_fit": True,
            "crystal_water_assumed_conserved": True,
            "conserved_bridge_water_count": 0,
        },
    )
    assert cp1["schema"] == SIDECAR_REVIEW_SCHEMA
    assert cp1["verdict"] == "block"
    rids1 = {f["rule_id"] for f in cp1["findings"]}
    assert "CP1_HTML_OR_CAPTCHA_DISGUISED_INPUT" in rids1
    assert "CP1_MIXED_OBSERVABLE_POOLING" in rids1
    assert "CP1_UNVERIFIED_CRYSTAL_WATER_ASSUMPTION" in rids1

    # CP2: warns on 0/2 catalog partners, blocks on broken RBFE atom map; LLM CANNOT downgrade block!
    scripted_downgrade = Scripted(
        replies={
            "CP2_PRE_PHYSICS": json.dumps({
                "verdict": "pass",
                "findings": [
                    {
                        "rule_id": "LLM_ADD_CATALOG_COMPARATOR",
                        "severity": "warn",
                        "summary": "Include A0005 as a 2/2 purchasable comparator.",
                        "recommendation": "Add A0005 to the MD panel.",
                    }
                ],
                "suggestions": ["Verify commercial stock for A0005 partners before ordering."],
            })
        }
    )
    cp2 = run_sidecar_review(
        "CP2_PRE_PHYSICS",
        {
            "shortlist": [{"id": "A0200", "catalog_verified_partners": 0, "hard_red_flags": []}],
            "rbfe_mapping_audits": [
                {"edge_id": "C26-A2__C26-A6", "heavy_connectivity_or_order_mismatches": 36, "passed_gate": False}
            ],
            "dispatch_design_rbfe": True,
            "rbfe_control_gate_passed": False,
        },
        transport=scripted_downgrade,
    )
    assert cp2["verdict"] == "block"  # Monotonic safety: LLM 'pass' NEVER overrides deterministic 'block'
    assert cp2["llm_critic"]["status"] == "completed"
    assert any(f["rule_id"] == "CP2_UNVERIFIED_CATALOG_PARTNERS" for f in cp2["findings"])
    assert any(f["rule_id"] == "LLM_ADD_CATALOG_COMPARATOR" for f in cp2["findings"])

    # CP3: telemetry breach & GPU under-utilization
    cp3 = run_deterministic_sidecar_audit(
        "CP3_RUNTIME_TELEMETRY",
        {
            "active_dispatchers": 2,
            "configured_cpu_threads": 64,
            "max_cpu_threads": 42,
            "allowed_gpus": [0, 1, 2, 3],
            "forbidden_gpus": [4, 5, 6, 7],
            "campaign_gpu_pids": {"0": [1234], "6": [5678]},
            "gpu_util_by_id": {"0": 38.0},
            "gpu_vram_frac_by_id": {"0": 0.03},
        },
    )
    assert cp3["verdict"] == "block"
    assert cp3["blocking_count"] == 3
    assert cp3["warning_count"] == 1

    # CP4: catches proxy overclaim and unsubstantiated wet-bridge rescue
    cp4 = run_deterministic_sidecar_audit(
        "CP4_PRE_DELIVERY",
        {
            "experimental_validation_count": 0,
            "report_text": "A0200 achieved confirmed higher potency over crystal controls.",
            "claims_admitted_candidate_rbfe": True,
            "rbfe_control_converged": False,
            "claims_wet_bridge_rescue": True,
            "full_wet_water_site_occupancy": 0.0,
        },
    )
    assert cp4["verdict"] == "block"
    assert cp4["blocking_count"] == 3

    # Append-only resolution ledger enforces rationale & blocks unwaived rejection of 'block'
    ledger = tmp_path / "sidecar_audit.jsonl"
    with pytest.raises(ValueError, match="without an explicit human waiver_ref"):
        record_advisory_resolution(
            ledger,
            checkpoint="CP2_PRE_PHYSICS",
            rule_id="CP2_RBFE_MAPPING_BOND_MISMATCH",
            severity="block",
            decision="rejected_with_rationale",
            rationale="Trying to ignore a broken atom map without waiver.",
        )
    rec = record_advisory_resolution(
        ledger,
        checkpoint="CP2_PRE_PHYSICS",
        rule_id="CP2_UNVERIFIED_CATALOG_PARTNERS",
        severity="warn",
        decision="accepted",
        rationale="Added 2/2 catalog-verified analog A0005 to the MD panel.",
    )
    assert rec["schema"] == SIDECAR_RESOLUTION_SCHEMA
    assert ledger.is_file()

    # Governance MCP tool moldarwin_sidecar_audit is registered and FREE
    from moldarwin.mcp.server import build as build_mcp_server

    server = build_mcp_server(profile="thin", packs=("governance",))
    tools = {t.name: t.fn for t in server._tool_manager.list_tools()}
    assert "moldarwin_sidecar_audit" in tools
    mcp_res = json.loads(
        tools["moldarwin_sidecar_audit"](
            checkpoint="CP2_PRE_PHYSICS",
            payload_json=json.dumps({"shortlist": [{"id": "A0200", "catalog_verified_partners": 0}]}),
        )
    )
    assert mcp_res["ok"] is True
    assert mcp_res["verdict"] == "warn"


def test_streaming_building_block_catalog_and_catalog_constrained_enumeration(tmp_path):
    # Create a miniature gzipped Mcule-style supplier catalog covering amines, sulfonyl chlorides, boronic acids
    smi_gz = tmp_path / "mcule_mini.smi.gz"
    rows = [
        "SMILES ID",
        "Nc1cccn2ncnc12 MCULE-CORE-AMINE",
        "COc1ccc(Cl)cc1S(=O)(=O)Cl MCULE-SC-01",
        "CCOc1cc(F)ccc1S(=O)(=O)Cl MCULE-SC-02",
        "FC(F)Oc1ccc(F)cc1S(=O)(=O)Cl MCULE-SC-03",
        "c1ccc(B(O)O)cc1 MCULE-BORONIC-01",
        "CC(=O)O MCULE-ACID-01",
        "CC[Si](C)(C)C MCULE-UNSUPPORTED-SI",
        "COc1ccc(Cl)cc1S(=O)(=O)Cl.Cl MCULE-SALT-SKIP",
    ]
    with gzip.open(smi_gz, "wt", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")

    db_path = tmp_path / "mcule_bb.sqlite"
    meta = build_building_block_index(smi_gz, db_path, max_mw=350.0, max_clogp=4.0)
    assert meta["schema"] == CATALOG_INDEX_SCHEMA
    assert meta["compounds_indexed"] == 6  # Si and salt skipped; B allowed for boronic_acid
    assert meta["bucket_counts"]["sulfonyl_chloride"] == 3
    assert meta["bucket_counts"]["primary_secondary_amine"] == 1
    assert meta["bucket_counts"]["boronic_acid"] == 1

    # Query sulfonyl chloride bucket
    sc_bbs = query_building_blocks(db_path, "sulfonyl_chloride", max_mw=300.0, limit=10)
    assert len(sc_bbs) == 3
    assert all(b["catalog_verified"] is True for b in sc_bbs)

    # Exact canonical lookup works
    hit = lookup_exact_smiles(db_path, ["Nc1cccn2ncnc12", "CCCCCCCCCCCCCCC"])
    assert hit["Nc1cccn2ncnc12"] == ["MCULE-CORE-AMINE"]
    assert hit["CCCCCCCCCCCCCCC"] == []

    # Complementary bucket inference on amine core for sulfonamidation -> sulfonyl_chloride
    assert infer_complementary_buckets("Nc1cccn2ncnc12", "sulfonamidation") == ["sulfonyl_chloride"]

    # Catalog-constrained reaction enumeration automatically pulls sulfonyl chlorides & verifies 2/2 partners!
    enum = enumerate_reaction_analogs(
        core_smiles="Nc1cccn2ncnc12",
        reaction_name="sulfonamidation",
        core_id="triazolopyridine_core",
        catalog_db=db_path,
        catalog_limit=10,
        max_products=10,
    )
    assert enum["core_catalog_verified"] is True
    assert enum["core_supplier_ids"] == ["MCULE-CORE-AMINE"]
    assert enum["catalog_queried_buckets"] == ["sulfonyl_chloride"]
    assert enum["product_count"] == 3
    assert all(p["catalog_verified_partners"] == 2 for p in enum["products"])
    assert all(p["partner_catalog_verified"] is True for p in enum["products"])
    assert all(p["partner_supplier_ids"] for p in enum["products"])
