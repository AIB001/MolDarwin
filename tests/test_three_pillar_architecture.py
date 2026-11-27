"""Architectural boundary guardrails enforcing the three-pillar CADD division of labor.

Prevents:
  1. Demoting MolOrigin (``data``) or MolCat (``screening``) to ``legacy`` in favor of a single engine.
  2. Unclassified GROMACS/PRISM simulation shim creep inside ``src/moldarwin/physics/``.
  3. Broken or fabricated introspection over pinned vendored assets (``MolOrigin``, ``MolCat``, ``PRISM``).
"""

from __future__ import annotations

from pathlib import Path

from moldarwin.domain_pack import CADD_DOMAIN_PACK_ID, get_cadd_domain_pack
from moldarwin.mcp.profiles import (
    PACK_ENGINE_PILLARS,
    PACK_TIERS,
    THREE_PILLAR_PACKS,
    pack_catalog,
)
from moldarwin.physics import PHYSICS_MODULE_BOUNDARIES
from moldarwin.skill_index import ACTIVE_V2_BUILTIN_SKILLS, find_skills


def test_physics_boundary_registry_classifies_every_module_and_freezes_prism_shims():
    """Every Python module under src/moldarwin/physics/ must be explicitly classified."""
    physics_dir = Path(__file__).resolve().parents[1] / "src" / "moldarwin" / "physics"
    actual_modules = sorted(
        p.stem for p in physics_dir.glob("*.py") if p.stem != "__init__"
    )
    assert sorted(PHYSICS_MODULE_BOUNDARIES) == actual_modules

    allowed_layers = {"moldarwin_scientific_boundary", "prism_runtime_compat_shim"}
    shims = []
    for mod_name, meta in PHYSICS_MODULE_BOUNDARIES.items():
        assert meta["layer"] in allowed_layers, f"invalid layer for {mod_name}: {meta}"
        if meta["layer"] == "prism_runtime_compat_shim":
            assert meta["freeze_policy"] == "bugfix_only_until_upstreamed_to_prism"
            assert meta["upstream_target"].startswith("AIB001/PRISM:")
            shims.append(mod_name)
    assert set(shims) == {"adaptive", "enhanced_sampling", "prism_bridge", "prism_fep"}


def test_three_pillar_balance_across_profiles_domain_pack_and_skills():
    """MolOrigin, MolCat, and PRISM must stand as equal core pillars in profiles, skills, and probes."""
    assert THREE_PILLAR_PACKS == ("data", "screening", "prism")
    assert PACK_ENGINE_PILLARS == {"data": "molorigin", "screening": "molcat", "prism": "prism"}
    for pack_name in THREE_PILLAR_PACKS:
        assert PACK_TIERS[pack_name] == "core_pillar"
    for loop_pack in ("active", "workflow"):
        assert PACK_TIERS[loop_pack] == "drug_design_loop"

    cat = pack_catalog(include_legacy=False)
    for pack_name in THREE_PILLAR_PACKS:
        assert cat[pack_name]["engine_pillar"] == PACK_ENGINE_PILLARS[pack_name]

    # Active skills cover MolOrigin, MolCat (gate-calibration), PRISM (generation + physics), and Drug Design
    for required_skill in ("drug-design", "gate-calibration", "generation-planning", "prism-physics"):
        assert required_skill in ACTIVE_V2_BUILTIN_SKILLS
    hit = find_skills(query="drug design free wilson selectivity mpo ehvi", source="builtin", limit=3)
    assert hit["skills"][0]["slug"] == "drug-design"

    # Honest introspection over pinned vendored assets without editing asset/
    pack = get_cadd_domain_pack()
    assert pack.pack_id == CADD_DOMAIN_PACK_ID == "cadd_drug_design"
    pillars = pack.probe_pillars()
    assert pillars["molorigin"]["skill_count"] >= 6
    assert pillars["molcat"]["available"] is True
    assert pillars["molcat"]["plugin_count"] >= 50
    for fam in ("admet_medchem", "synthesis_retrosynthesis", "docking_cofold_pose"):
        assert pillars["molcat"]["family_counts"][fam] >= 3
    assert pillars["prism"]["pinned_root_present"] is True
    assert len(pillars["prism"]["generation_adapters_present"]) >= 6
    # Honest report about upstream prism/design (Hard Constraint 7: never fabricate availability)
    assert isinstance(pillars["prism"]["prism_design_present_in_pinned_asset"], bool)
    assert set(pillars["prism"]["runtime_compat_shims_in_moldarwin"]) == {
        "adaptive",
        "enhanced_sampling",
        "prism_bridge",
        "prism_fep",
    }
