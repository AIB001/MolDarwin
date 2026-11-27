"""First-principles 3D pocket interaction profiling, exit-vector calculus, and isoform selectivity mapping.

Operates directly on standard PDB + SDF inputs using exact 3D vector geometry (analytical
sphere-ray steric clearance, Bondi van der Waals radii, Kabsch SVD pocket superposition, and
Zamyatnin residue volumes) so MolDarwin understands *where* and *why* to edit a ligand before
invoking PRISM generation/editing, MolCat screening, or alchemical FEP.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

POCKET_PROFILE_SCHEMA = "moldarwin-pocket-profile/1"
SELECTIVITY_MAP_SCHEMA = "moldarwin-isoform-selectivity-map/1"

#: Bondi (1964) atomic van der Waals radii in Angstrom (Evidence: literature).
BONDI_VDW_A: dict[str, float] = {
    "H": 1.20,
    "C": 1.70,
    "N": 1.55,
    "O": 1.52,
    "F": 1.47,
    "P": 1.80,
    "S": 1.80,
    "CL": 1.75,
    "BR": 1.85,
    "I": 1.98,
    "B": 1.92,
}

#: Zamyatnin (1972) standard amino-acid residue volumes in A^3 (Evidence: literature).
AA_VOLUME_A3: dict[str, float] = {
    "GLY": 60.1,
    "ALA": 88.6,
    "SER": 89.0,
    "CYS": 108.5,
    "ASP": 111.1,
    "PRO": 112.7,
    "ASN": 114.1,
    "THR": 116.1,
    "GLU": 138.4,
    "VAL": 140.0,
    "GLN": 143.8,
    "HIS": 153.2,
    "HID": 153.2,
    "HIE": 153.2,
    "HIP": 153.2,
    "MET": 162.9,
    "ILE": 166.7,
    "LEU": 166.7,
    "LYS": 168.6,
    "ARG": 173.4,
    "PHE": 189.9,
    "TYR": 193.6,
    "TRP": 227.8,
}

#: Coarse physicochemical residue classes for isoform selectivity directives (Evidence: literature).
AA_PHYSCHEM_CLASS: dict[str, str] = {
    "GLY": "small_nonpolar",
    "ALA": "small_nonpolar",
    "PRO": "small_nonpolar",
    "VAL": "bulky_hydrophobic",
    "LEU": "bulky_hydrophobic",
    "ILE": "bulky_hydrophobic",
    "MET": "bulky_hydrophobic",
    "CYS": "polar_uncharged",
    "SER": "polar_uncharged",
    "THR": "polar_uncharged",
    "ASN": "polar_uncharged",
    "GLN": "polar_uncharged",
    "PHE": "aromatic",
    "TYR": "aromatic_polar",
    "TRP": "aromatic_polar",
    "HIS": "aromatic_polar",
    "HID": "aromatic_polar",
    "HIE": "aromatic_polar",
    "HIP": "basic",
    "ASP": "acidic",
    "GLU": "acidic",
    "LYS": "basic",
    "ARG": "basic",
}

#: Default 3D geometry thresholds (Evidence: convention, standard structural medchem bounds).
DEFAULT_HBOND_CUTOFF_A: float = 3.5
DEFAULT_CONTACT_CUTOFF_A: float = 4.5
DEFAULT_RAY_MAX_A: float = 6.0
DEFAULT_PROBE_RADIUS_A: float = 1.70
DEFAULT_VOLUME_DIFF_THRESHOLD_A3: float = 15.0

_WATER_RESNAMES = frozenset({"HOH", "WAT", "DOD", "H2O", "SOL"})
_ANION_ATOMS = {("ASP", "OD1"), ("ASP", "OD2"), ("GLU", "OE1"), ("GLU", "OE2")}
_CATION_ATOMS = {
    ("LYS", "NZ"),
    ("ARG", "NH1"),
    ("ARG", "NH2"),
    ("ARG", "NE"),
    ("HIP", "ND1"),
    ("HIP", "NE2"),
}
_SC_HBD_ATOMS = {
    ("SER", "OG"), ("THR", "OG1"), ("TYR", "OH"), ("TRP", "NE1"),
    ("ASN", "ND2"), ("GLN", "NE2"), ("HIS", "ND1"), ("HIS", "NE2"),
    ("HID", "ND1"), ("HIE", "NE2"), ("HIP", "ND1"), ("HIP", "NE2"),
    ("LYS", "NZ"), ("ARG", "NE"), ("ARG", "NH1"), ("ARG", "NH2"),
    ("CYS", "SG"),
}
_SC_HBA_ATOMS = {
    ("SER", "OG"), ("THR", "OG1"), ("TYR", "OH"), ("ASN", "OD1"),
    ("GLN", "OE1"), ("ASP", "OD1"), ("ASP", "OD2"), ("GLU", "OE1"),
    ("GLU", "OE2"), ("HIS", "ND1"), ("HIS", "NE2"), ("HID", "NE2"),
    ("HIE", "ND1"), ("CYS", "SG"), ("MET", "SD"),
}


def _classify_protein_atom(resname: str, atom_name: str, elem: str) -> str:
    rn = resname.upper()
    an = atom_name.upper()
    if (rn, an) in _ANION_ATOMS:
        return "anion"
    if (rn, an) in _CATION_ATOMS:
        return "cation"
    if an == "O" or an == "OXT":
        return "hba"
    if an == "N" and rn != "PRO":
        return "hbd"
    is_d = (rn, an) in _SC_HBD_ATOMS
    is_a = (rn, an) in _SC_HBA_ATOMS
    if is_d and is_a:
        return "hbd_hba"
    if is_d:
        return "hbd"
    if is_a:
        return "hba"
    if elem in {"N", "O"}:
        return "polar"
    if rn in {"PHE", "TYR", "TRP", "HIS", "HID", "HIE", "HIP"} and elem == "C" and an not in {"C", "CA", "CB"}:
        return "aromatic"
    return "hydrophobic"


def _parse_pdb_structure(pdb_path: str | Path) -> dict[str, Any]:
    """Parse protein heavy atoms, CA trace, and crystal waters from a PDB file."""
    path = Path(pdb_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"receptor PDB not found: {path}")

    prot_atoms: list[dict[str, Any]] = []
    waters: list[dict[str, Any]] = []
    ca_by_res: dict[tuple[str, int, str], dict[str, Any]] = {}

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if len(line) < 54:
            continue
        rec = line[:6].strip()
        if rec not in {"ATOM", "HETATM"}:
            continue
        resname = line[17:20].strip().upper()
        atom_name = line[12:16].strip().upper()
        chain = line[21:22].strip() or "A"
        resseq_str = line[22:26].strip()
        icode = line[26:27].strip()
        elem = (line[76:78].strip() if len(line) >= 78 else "").upper()
        if not elem:
            elem = "".join(ch for ch in atom_name if ch.isalpha())[:1].upper()
        if elem == "H":
            continue
        try:
            resseq = int(resseq_str)
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
            bfac = float(line[60:66]) if len(line) >= 66 and line[60:66].strip() else 0.0
        except ValueError:
            continue

        if resname in _WATER_RESNAMES and elem == "O":
            waters.append({
                "water_id": f"{chain}:{resseq}{icode}",
                "xyz": np.array([x, y, z], dtype=float),
                "bfactor": bfac,
            })
            continue

        if rec != "ATOM":
            continue

        res_id = f"{chain}:{resname}{resseq}{icode}"
        role = _classify_protein_atom(resname, atom_name, elem)
        item = {
            "chain": chain,
            "resname": resname,
            "resseq": resseq,
            "icode": icode,
            "res_id": res_id,
            "atom_name": atom_name,
            "elem": elem,
            "vdw": BONDI_VDW_A.get(elem, 1.70),
            "role": role,
            "xyz": np.array([x, y, z], dtype=float),
        }
        prot_atoms.append(item)
        if atom_name == "CA":
            ca_by_res[(chain, resseq, icode)] = item

    if not prot_atoms:
        raise ValueError(f"no protein heavy ATOM records found in {path}")

    return {
        "path": str(path),
        "atoms": prot_atoms,
        "coords": np.vstack([a["xyz"] for a in prot_atoms]),
        "vdw": np.array([a["vdw"] for a in prot_atoms], dtype=float),
        "waters": waters,
        "ca_by_res": ca_by_res,
    }


def _parse_ligand_3d(ligand_sdf: str | Path) -> dict[str, Any]:
    """Load 3D ligand coordinates and RDKit heavy-atom chemistry (preserving explicit H rays)."""
    from rdkit import Chem

    path = Path(ligand_sdf).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"ligand SDF not found: {path}")

    suppl = Chem.SDMolSupplier(str(path), removeHs=False, sanitize=True)
    mol_full = suppl[0] if len(suppl) > 0 else None
    if mol_full is None:
        raise ValueError(f"RDKit could not parse valid 3D ligand from {path}")
    if mol_full.GetNumConformers() == 0:
        raise ValueError(f"ligand SDF has no 3D conformer: {path}")

    conf = mol_full.GetConformer()
    heavy_atoms: list[dict[str, Any]] = []
    full_to_heavy: dict[int, int] = {}

    for atom in mol_full.GetAtoms():
        if atom.GetAtomicNum() == 1:
            continue
        full_to_heavy[atom.GetIdx()] = len(full_to_heavy)

    for atom in mol_full.GetAtoms():
        if atom.GetAtomicNum() == 1:
            continue
        idx = atom.GetIdx()
        h_idx = full_to_heavy[idx]
        pos = conf.GetAtomPosition(idx)
        xyz = np.array([pos.x, pos.y, pos.z], dtype=float)

        explicit_h_vecs: list[np.ndarray] = []
        heavy_neighbor_coords: list[np.ndarray] = []
        for nbr in atom.GetNeighbors():
            npos = conf.GetAtomPosition(nbr.GetIdx())
            nxyz = np.array([npos.x, npos.y, npos.z], dtype=float)
            if nbr.GetAtomicNum() == 1:
                vec = nxyz - xyz
                nrm = float(np.linalg.norm(vec))
                if nrm > 1e-6:
                    explicit_h_vecs.append(vec / nrm)
            else:
                heavy_neighbor_coords.append(nxyz)

        total_h = atom.GetTotalNumHs(includeNeighbors=True)
        sym = atom.GetSymbol()
        is_hbd = sym in {"N", "O", "S"} and total_h > 0
        is_hba = sym in {"N", "O", "F"} and not (sym == "N" and atom.GetFormalCharge() > 0)
        degree_heavy = len(heavy_neighbor_coords)

        # Outward growth vectors: exact explicit-H bond directions when present, else
        # geometric bisector away from bonded heavy neighbors.
        growth_vecs: list[np.ndarray] = list(explicit_h_vecs)
        if (
            not growth_vecs
            and heavy_neighbor_coords
            and (total_h > 0 or (degree_heavy == 1 and sym in {"C", "F", "Cl", "Br"}))
        ):
            away = np.sum([xyz - nc for nc in heavy_neighbor_coords], axis=0)
            nrm = float(np.linalg.norm(away))
            if nrm > 1e-6:
                growth_vecs.append(away / nrm)

        is_substitutable = bool(
            (sym == "C" and (total_h > 0 or degree_heavy == 1))
            or (sym in {"F", "Cl", "Br"} and degree_heavy == 1)
            or (sym == "N" and total_h > 0 and not atom.GetIsAromatic())
        )
        heavy_atoms.append({
            "heavy_index": h_idx,
            "full_index": idx,
            "symbol": sym,
            "is_aromatic": atom.GetIsAromatic(),
            "in_ring": atom.IsInRing(),
            "formal_charge": atom.GetFormalCharge(),
            "total_h": total_h,
            "heavy_degree": degree_heavy,
            "is_hbd": is_hbd,
            "is_hba": is_hba,
            "is_substitutable": is_substitutable,
            "xyz": xyz,
            "growth_vecs": growth_vecs,
        })

    mol_no_h = Chem.RemoveHs(mol_full)
    can_smiles = Chem.MolToSmiles(mol_no_h, canonical=True)
    return {
        "path": str(path),
        "smiles": can_smiles,
        "heavy_atoms": heavy_atoms,
        "coords": np.vstack([a["xyz"] for a in heavy_atoms]),
    }


def _ray_steric_clearance(
    origin: np.ndarray,
    direction: np.ndarray,
    prot_coords: np.ndarray,
    prot_vdw: np.ndarray,
    *,
    probe_radius_A: float = DEFAULT_PROBE_RADIUS_A,
    ray_max_A: float = DEFAULT_RAY_MAX_A,
) -> tuple[float, int | None]:
    """Exact analytical distance along ray before a probe sphere hits protein vdW surface."""
    rel = prot_coords - origin  # (M, 3)
    proj = rel @ direction  # (M,)
    forward = proj > 0.0
    if not np.any(forward):
        return float(ray_max_A), None

    rel_f = rel[forward]
    proj_f = proj[forward]
    vdw_f = prot_vdw[forward] + probe_radius_A
    perp_sq = np.maximum(0.0, np.sum(rel_f * rel_f, axis=1) - proj_f * proj_f)
    hit_mask = perp_sq < (vdw_f * vdw_f)
    if not np.any(hit_mask):
        return float(ray_max_A), None

    idx_f = np.flatnonzero(forward)[hit_mask]
    t_hits = proj_f[hit_mask] - np.sqrt(vdw_f[hit_mask] ** 2 - perp_sq[hit_mask])
    t_hits = np.maximum(0.0, t_hits)
    best_local = int(np.argmin(t_hits))
    clearance = float(min(ray_max_A, t_hits[best_local]))
    return clearance, int(idx_f[best_local])


def _subpocket_environment(
    origin: np.ndarray,
    direction: np.ndarray,
    prot_atoms: list[dict[str, Any]],
    prot_coords: np.ndarray,
) -> tuple[str, int, list[str]]:
    """Characterize chemical polarity and enclosure around the target growth subpocket."""
    probe_center = origin + 2.5 * direction
    dists = np.linalg.norm(prot_coords - probe_center, axis=1)
    near_idx = np.flatnonzero(dists <= 4.5)
    if len(near_idx) == 0:
        return "solvent_exposed", 0, []

    counts: dict[str, int] = {}
    residues: set[str] = set()
    for i in near_idx:
        atom = prot_atoms[int(i)]
        role = atom["role"]
        counts[role] = counts.get(role, 0) + 1
        residues.add(atom["res_id"])

    n_near = len(near_idx)
    if n_near <= 3:
        return "solvent_exposed", n_near, sorted(residues)
    n_anion = counts.get("anion", 0)
    n_cation = counts.get("cation", 0)
    n_hba = counts.get("hba", 0) + counts.get("hbd_hba", 0) + n_anion
    n_hbd = counts.get("hbd", 0) + counts.get("hbd_hba", 0) + n_cation
    n_hydro = counts.get("hydrophobic", 0) + counts.get("aromatic", 0)

    if n_anion >= 2 and n_anion >= n_cation:
        env = "anionic_polar"
    elif n_cation >= 2 and n_cation > n_anion:
        env = "cationic_polar"
    elif n_hydro >= 0.70 * n_near:
        env = "hydrophobic"
    elif n_hba > n_hbd and n_hba >= 2:
        env = "polar_acceptor_rich"
    elif n_hbd > n_hba and n_hbd >= 2:
        env = "polar_donor_rich"
    else:
        env = "mixed_amphiphilic"
    return env, n_near, sorted(residues)[:8]


def _classify_clearance(clearance_A: float, subpocket_env: str) -> str:
    """Classify radial clearance beyond vdW contact (r_prot + 1.70 A probe).

    Physical room mapping (Evidence: convention / Bondi vdW radii):
      - >= 3.4 A (atom-to-atom >= 6.8 A): open subpocket / ring growth or solvent exposed
      - >= 2.1 A (atom-to-atom >= 5.5 A): medium subpocket (-Et, -CF3, -OMe, -CN)
      - >= 1.05 A (atom-to-atom >= 4.45 A): compact subpocket (-F, -Me, -OH)
      - < 1.05 A: tight steric wall
    """
    if subpocket_env == "solvent_exposed" and clearance_A >= 3.4:
        return "solvent_exposed"
    if clearance_A >= 3.4:
        return "open_subpocket"
    if clearance_A >= 2.1:
        return "medium_subpocket"
    if clearance_A >= 1.05:
        return "compact_subpocket"
    return "tight_steric_wall"


def profile_3d_pocket_and_vectors(
    receptor_pdb: str | Path,
    ligand_sdf: str | Path,
    *,
    hbond_cutoff_A: float = DEFAULT_HBOND_CUTOFF_A,
    contact_cutoff_A: float = DEFAULT_CONTACT_CUTOFF_A,
    ray_max_A: float = DEFAULT_RAY_MAX_A,
) -> dict[str, Any]:
    """Profile 3D protein-ligand interactions, locked anchors, and editable growth vectors.

    Separates critical pharmacophore anchors (``anchor_atom_indices``) from accessible growth
    vectors (``editable_atom_indices``) and solvent-exposed ADMET handles so downstream
    analog generation never breaks key H-bonds or grows into steric walls.
    """
    prot = _parse_pdb_structure(receptor_pdb)
    lig = _parse_ligand_3d(ligand_sdf)
    prot_atoms = prot["atoms"]
    prot_coords = prot["coords"]
    prot_vdw = prot["vdw"]
    waters = prot["waters"]

    atom_profiles: list[dict[str, Any]] = []
    anchor_indices: list[int] = []
    editable_indices: list[int] = []
    solvent_handles: list[int] = []
    water_adjacent_indices: list[int] = []
    anchor_interactions: list[dict[str, Any]] = []

    for latom in lig["heavy_atoms"]:
        h_idx = latom["heavy_index"]
        xyz = latom["xyz"]
        dists = np.linalg.norm(prot_coords - xyz, axis=1)
        min_idx = int(np.argmin(dists))
        min_dist = float(dists[min_idx])

        # Check complementary polar H-bond / salt-bridge anchors
        polar_contacts: list[dict[str, Any]] = []
        near_hbond_idx = np.flatnonzero(dists <= hbond_cutoff_A)
        for pi in near_hbond_idx:
            pa = prot_atoms[int(pi)]
            d = float(dists[int(pi)])
            role = pa["role"]
            complementary = (
                (latom["is_hbd"] and role in {"hba", "hbd_hba", "anion"})
                or (latom["is_hba"] and role in {"hbd", "hbd_hba", "cation"})
                or (latom["formal_charge"] > 0 and role == "anion")
                or (latom["formal_charge"] < 0 and role == "cation")
            )
            if complementary:
                polar_contacts.append({
                    "protein_residue": pa["res_id"],
                    "protein_atom": pa["atom_name"],
                    "protein_role": role,
                    "distance_A": round(d, 3),
                })

        # Check nearby crystallographic water molecules
        near_waters: list[dict[str, Any]] = []
        for w in waters:
            dw = float(np.linalg.norm(w["xyz"] - xyz))
            if dw <= 3.8:
                near_waters.append({"water_id": w["water_id"], "distance_A": round(dw, 3)})

        # Evaluate best outward growth vector if substitutable
        best_clearance: float | None = None
        best_vec: list[float] | None = None
        best_env: str | None = None
        best_room: str | None = None
        best_wall_res: str | None = None
        subpocket_residues: list[str] = []

        if latom["is_substitutable"] and latom["growth_vecs"]:
            for vec in latom["growth_vecs"]:
                clr, hit_pi = _ray_steric_clearance(
                    xyz, vec, prot_coords, prot_vdw, ray_max_A=ray_max_A
                )
                if best_clearance is None or clr > best_clearance:
                    best_clearance = clr
                    best_vec = [round(float(c), 4) for c in vec]
                    best_env, _, subpocket_residues = _subpocket_environment(
                        xyz, vec, prot_atoms, prot_coords
                    )
                    best_room = _classify_clearance(clr, best_env)
                    best_wall_res = prot_atoms[hit_pi]["res_id"] if hit_pi is not None else None

        # Assign primary structural role
        if polar_contacts:
            structural_role = "anchor_locked"
            anchor_indices.append(h_idx)
            for pc in polar_contacts:
                anchor_interactions.append({
                    "ligand_heavy_index": h_idx,
                    "ligand_symbol": latom["symbol"],
                    **pc,
                })
        elif best_room == "solvent_exposed":
            structural_role = "solvent_exposed"
            editable_indices.append(h_idx)
            solvent_handles.append(h_idx)
        elif best_room in {"open_subpocket", "medium_subpocket", "compact_subpocket"}:
            structural_role = "growth_vector"
            editable_indices.append(h_idx)
        elif near_waters:
            structural_role = "water_adjacent"
        else:
            n_contacts = int(np.sum(dists <= contact_cutoff_A))
            structural_role = "buried_core" if n_contacts >= 4 else "peripheral_noneditable"

        if near_waters:
            water_adjacent_indices.append(h_idx)

        atom_profiles.append({
            "heavy_index": h_idx,
            "symbol": latom["symbol"],
            "is_aromatic": latom["is_aromatic"],
            "in_ring": latom["in_ring"],
            "total_h": latom["total_h"],
            "structural_role": structural_role,
            "nearest_protein_residue": prot_atoms[min_idx]["res_id"],
            "nearest_protein_dist_A": round(min_dist, 3),
            "polar_contacts": polar_contacts,
            "near_waters": near_waters,
            "growth_vector": best_vec,
            "clearance_A": round(best_clearance, 3) if best_clearance is not None else None,
            "steric_room": best_room,
            "subpocket_environment": best_env,
            "steric_wall_residue": best_wall_res,
            "subpocket_residues": subpocket_residues,
        })

    growth_vectors = sorted(
        [a for a in atom_profiles if a["structural_role"] in {"growth_vector", "solvent_exposed"}],
        key=lambda r: -(r["clearance_A"] or 0.0),
    )
    return {
        "schema": POCKET_PROFILE_SCHEMA,
        "receptor_pdb": prot["path"],
        "ligand_sdf": lig["path"],
        "ligand_smiles": lig["smiles"],
        "heavy_atom_count": len(atom_profiles),
        "anchor_atom_indices": sorted(anchor_indices),
        "editable_atom_indices": sorted(editable_indices),
        "solvent_handle_indices": sorted(solvent_handles),
        "water_adjacent_indices": sorted(water_adjacent_indices),
        "anchor_interactions": anchor_interactions,
        "top_growth_vectors": growth_vectors[:10],
        "atom_profiles": atom_profiles,
        "thresholds": {
            "hbond_cutoff_A": hbond_cutoff_A,
            "contact_cutoff_A": contact_cutoff_A,
            "ray_max_A": ray_max_A,
            "probe_radius_A": DEFAULT_PROBE_RADIUS_A,
            "evidence": "convention_and_literature_bondi_vdw",
        },
    }


def _kabsch_align(mobile: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Exact Kabsch SVD optimal rigid-body superposition (mobile -> reference)."""
    c_mob = np.mean(mobile, axis=0)
    c_ref = np.mean(reference, axis=0)
    p = mobile - c_mob
    q = reference - c_ref
    cov = p.T @ q
    u, _, vt = np.linalg.svd(cov)
    d = np.linalg.det(vt.T @ u.T)
    diag = np.diag([1.0, 1.0, -1.0 if d < 0 else 1.0])
    rot = vt.T @ diag @ u.T
    trans = c_ref - rot @ c_mob
    aligned = mobile @ rot.T + trans
    rmsd = float(np.sqrt(np.mean(np.sum((aligned - reference) ** 2, axis=1))))
    return rot, trans, rmsd


def map_isoform_selectivity_vectors(
    target_pdb: str | Path,
    offtarget_pdb: str | Path,
    reference_ligand_sdf: str | Path,
    *,
    pocket_cutoff_A: float = 6.5,
    ca_match_cutoff_A: float = 3.0,
    auto_kabsch_align: bool = True,
) -> dict[str, Any]:
    """Map binding-site residue differences between target and off-target onto ligand exit vectors.

    Superposes the off-target binding site onto the target binding site via Kabsch SVD when
    requested, identifies every divergent binding-site residue, quantifies sidechain volume
    difference (Zamyatnin A^3) and physicochemical shift, and pairs each difference with the
    closest editable ligand exit vector to produce 3D-grounded selectivity directives.
    """
    target = _parse_pdb_structure(target_pdb)
    offtarget = _parse_pdb_structure(offtarget_pdb)
    lig = _parse_ligand_3d(reference_ligand_sdf)
    pocket = profile_3d_pocket_and_vectors(target_pdb, reference_ligand_sdf)

    lig_coords = lig["coords"]
    lig_center = np.mean(lig_coords, axis=0)

    # Identify target binding-site residues (any heavy atom within pocket_cutoff_A of ligand)
    target_pocket_keys: set[tuple[str, int, str]] = set()
    res_heavy_centroids: dict[tuple[str, int, str], list[np.ndarray]] = {}
    for atom in target["atoms"]:
        key = (atom["chain"], atom["resseq"], atom["icode"])
        d_min = float(np.min(np.linalg.norm(lig_coords - atom["xyz"], axis=1)))
        if d_min <= pocket_cutoff_A:
            target_pocket_keys.add(key)
        res_heavy_centroids.setdefault(key, []).append(atom["xyz"])

    target_ca_keys = sorted(k for k in target_pocket_keys if k in target["ca_by_res"])
    off_ca_items = list(offtarget["ca_by_res"].items())

    # Optional Kabsch alignment using shared (chain, resseq, icode) CA pairs or nearest CA pairs
    alignment_mode = "pre_aligned"
    alignment_rmsd: float | None = None
    rot = np.eye(3)
    trans = np.zeros(3)

    if auto_kabsch_align and target_ca_keys and off_ca_items:
        shared_keys = [k for k in target_ca_keys if k in offtarget["ca_by_res"]]
        if len(shared_keys) >= 4:
            ref_pts = np.vstack([target["ca_by_res"][k]["xyz"] for k in shared_keys])
            mob_pts = np.vstack([offtarget["ca_by_res"][k]["xyz"] for k in shared_keys])
            rot, trans, alignment_rmsd = _kabsch_align(mob_pts, ref_pts)
            alignment_mode = f"kabsch_shared_resseq_n{len(shared_keys)}"
        else:
            # Match by nearest CA within 4.0 A in initial frame
            off_ca_coords = np.vstack([v["xyz"] for _, v in off_ca_items])
            ref_list, mob_list = [], []
            for k in target_ca_keys:
                t_xyz = target["ca_by_res"][k]["xyz"]
                ds = np.linalg.norm(off_ca_coords - t_xyz, axis=1)
                j = int(np.argmin(ds))
                if float(ds[j]) <= 4.0:
                    ref_list.append(t_xyz)
                    mob_list.append(off_ca_coords[j])
            if len(ref_list) >= 4:
                rot, trans, alignment_rmsd = _kabsch_align(np.vstack(mob_list), np.vstack(ref_list))
                alignment_mode = f"kabsch_nearest_ca_n{len(ref_list)}"

    off_ca_aligned = [
        (key, info, info["xyz"] @ rot.T + trans)
        for key, info in off_ca_items
    ]
    off_ca_xyz_mat = (
        np.vstack([row[2] for row in off_ca_aligned]) if off_ca_aligned else np.zeros((0, 3))
    )

    editable_profiles = [
        a for a in pocket["atom_profiles"]
        if a["heavy_index"] in set(pocket["editable_atom_indices"])
    ]
    editable_xyz = {
        a["heavy_index"]: lig["heavy_atoms"][a["heavy_index"]]["xyz"]
        for a in editable_profiles
    }

    divergent_residues: list[dict[str, Any]] = []
    conserved_count = 0

    for t_key in target_ca_keys:
        t_ca = target["ca_by_res"][t_key]
        if len(off_ca_xyz_mat) == 0:
            continue
        ds = np.linalg.norm(off_ca_xyz_mat - t_ca["xyz"], axis=1)
        best_j = int(np.argmin(ds))
        ca_dist = float(ds[best_j])
        if ca_dist > ca_match_cutoff_A:
            continue
        _, o_ca, _ = off_ca_aligned[best_j]
        if t_ca["resname"] == o_ca["resname"]:
            conserved_count += 1
            continue

        t_res = t_ca["resname"]
        o_res = o_ca["resname"]
        v_t = AA_VOLUME_A3.get(t_res, 130.0)
        v_o = AA_VOLUME_A3.get(o_res, 130.0)
        delta_v = round(v_t - v_o, 1)
        c_t = AA_PHYSCHEM_CLASS.get(t_res, "unknown")
        c_o = AA_PHYSCHEM_CLASS.get(o_res, "unknown")

        res_centroid = np.mean(np.vstack(res_heavy_centroids[t_key]), axis=0)
        min_lig_dist = float(np.min(np.linalg.norm(lig_coords - res_centroid, axis=1)))

        # Pair with closest editable ligand exit vector (preferring directional alignment)
        best_vector_match: dict[str, Any] | None = None
        best_score = math.inf
        for ep in editable_profiles:
            h_idx = ep["heavy_index"]
            l_xyz = editable_xyz[h_idx]
            d_vec = res_centroid - l_xyz
            d_len = float(np.linalg.norm(d_vec))
            cos_align: float | None = None
            if ep["growth_vector"] is not None and d_len > 1e-6:
                gvec = np.array(ep["growth_vector"], dtype=float)
                cos_align = float(np.dot(gvec, d_vec / d_len))
            # Penalize vectors pointing strictly away from the divergent residue
            eff_score = d_len - (1.5 * max(0.0, cos_align or 0.0))
            if eff_score < best_score:
                best_score = eff_score
                best_vector_match = {
                    "ligand_heavy_index": h_idx,
                    "ligand_symbol": ep["symbol"],
                    "distance_to_residue_A": round(d_len, 3),
                    "vector_alignment_cos": round(cos_align, 3) if cos_align is not None else None,
                    "clearance_A": ep["clearance_A"],
                    "steric_room": ep["steric_room"],
                }

        # Actionable selectivity mechanism classification
        if delta_v <= -DEFAULT_VOLUME_DIFF_THRESHOLD_A3:
            mechanism = "steric_clash_offtarget_opportunity"
            directive = (
                f"Target {t_ca['res_id']} ({v_t:.0f} A^3) is smaller than off-target {o_ca['res_id']} "
                f"({v_o:.0f} A^3, dV={delta_v:+.1f} A^3): grow a compact substituent toward this "
                f"subpocket to selectively clash with the bulkier off-target sidechain."
            )
        elif delta_v >= DEFAULT_VOLUME_DIFF_THRESHOLD_A3:
            mechanism = "steric_constraint_in_target"
            directive = (
                f"Target {t_ca['res_id']} ({v_t:.0f} A^3) is bulkier than off-target {o_ca['res_id']} "
                f"({v_o:.0f} A^3, dV={delta_v:+.1f} A^3): avoid oversized substituents here; exploit "
                f"van der Waals complementarity or electrostatic specificity instead."
            )
        elif c_t != c_o:
            mechanism = "electrostatic_polarity_selectivity_opportunity"
            directive = (
                f"Target {t_ca['res_id']} ({c_t}) differs chemically from off-target {o_ca['res_id']} "
                f"({c_o}): introduce a complementary H-bond or dipole group oriented toward {t_ca['res_id']}."
            )
        else:
            mechanism = "subtle_sidechain_difference"
            directive = (
                f"Subtle substitution {t_ca['res_id']} vs {o_ca['res_id']} (dV={delta_v:+.1f} A^3): "
                f"probe with fine steric/electronic R-group scan and verify via paired RBFE."
            )

        divergent_residues.append({
            "target_residue": t_ca["res_id"],
            "offtarget_residue": o_ca["res_id"],
            "ca_distance_A": round(ca_dist, 3),
            "ligand_min_dist_A": round(min_lig_dist, 3),
            "target_volume_A3": v_t,
            "offtarget_volume_A3": v_o,
            "delta_volume_A3": delta_v,
            "target_class": c_t,
            "offtarget_class": c_o,
            "mechanism": mechanism,
            "directive": directive,
            "paired_exit_vector": best_vector_match,
        })

    divergent_residues.sort(
        key=lambda r: (
            0 if r["mechanism"] == "steric_clash_offtarget_opportunity" else 1,
            r["paired_exit_vector"]["distance_to_residue_A"] if r["paired_exit_vector"] else 99.0,
        )
    )
    return {
        "schema": SELECTIVITY_MAP_SCHEMA,
        "target_pdb": target["path"],
        "offtarget_pdb": offtarget["path"],
        "ligand_sdf": lig["path"],
        "ligand_centroid_A": [round(float(c), 3) for c in lig_center],
        "alignment_mode": alignment_mode,
        "alignment_ca_rmsd_A": round(alignment_rmsd, 3) if alignment_rmsd is not None else None,
        "pocket_residues_compared": conserved_count + len(divergent_residues),
        "conserved_pocket_residues": conserved_count,
        "divergent_residue_count": len(divergent_residues),
        "selectivity_directives": divergent_residues,
        "anchor_atom_indices": pocket["anchor_atom_indices"],
        "editable_atom_indices": pocket["editable_atom_indices"],
        "volume_table_evidence": "literature_zamyatnin_1972",
    }


__all__ = [
    "AA_PHYSCHEM_CLASS",
    "AA_VOLUME_A3",
    "BONDI_VDW_A",
    "POCKET_PROFILE_SCHEMA",
    "SELECTIVITY_MAP_SCHEMA",
    "map_isoform_selectivity_vectors",
    "profile_3d_pocket_and_vectors",
]
