"""Scalable, tiered on-demand skill discovery for built-in and generated skills.

Built-in skills live in ``moldarwin.skills.WORKFLOWS``; fine-grained, target- or
method-specific skills generated during RSI live in caller-supplied directories or
``MOLDARWIN_SKILL_DIRS`` and are indexed live without restarting the server.

Progressive disclosure keeps context cost O(1) even at hundreds of specialized skills:
- Tier 1 (``find_skills``): reads only the YAML frontmatter header (first 16 KiB) of each
  ``SKILL.md`` and directory filenames — never full skill bodies or ``references/``.
  Computes ``manifest_sha256`` only for the top-K returned generated matches so their
  ``read`` handles work directly with ``moldarwin_skill_read``.
- Tier 2 (``moldarwin_skill_read(slug)``): loads only the chosen ``SKILL.md`` and lists
  its ``available_members``.
- Tier 3 (``moldarwin_skill_read(slug, member="references/...")``): loads deep references
  only when explicitly requested.

Matching is purely deterministic and lexical over declared frontmatter fields (``name``,
``domain``, ``tags``/``triggers``, ``applicable_when``, ``description``); ``invalid_when``
is surfaced verbatim on every Tier-1 card so the host sees negative boundaries before
paying tokens to load the body. Scoring weights are ``convention`` (ranking aid only,
never an applicability verdict or activation grant).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from moldarwin import skills

ENV_SKILL_DIRS = "MOLDARWIN_SKILL_DIRS"
MAX_SCAN_SKILLS = 1024
MAX_LIMIT = 20

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")
_LIST_KEYS = frozenset({"tags", "triggers", "tools"})
_TEXT_KEYS = frozenset({
    "name",
    "description",
    "domain",
    "family",
    "applicable_when",
    "invalid_when",
    "maturity",
    "supersedes",
})
_MATURITIES = frozenset({"draft", "validated", "retired"})

#: 15 orthogonal, three-pillar active v2 built-in skills (Evidence: convention /
#: balanced MolOrigin + MolCat + PRISM + Drug-Design DMTA coverage, hiding overlapping
#: sweep-era historical skills from default Tier-1 discovery while keeping every bundle
#: readable via moldarwin_skill_read or discoverable with include_legacy=True).
ACTIVE_V2_BUILTIN_SKILLS: frozenset[str] = frozenset({
    # Core autonomy, epistemology, decisions, and target controls (4)
    "autonomous-planning",
    "research",
    "research-decision",
    "target-parameters",
    # Cross-pillar drug-design reasoning + RSI method/skill creation (3)
    "drug-design",
    "method-optimization",
    "rsi-skill-creator",
    # MolCat screening gate calibration & PRISM 3D generation + physics (3)
    "gate-calibration",
    "generation-planning",
    "prism-physics",
    # MolOrigin chemical discovery, selectivity, and synthesizable sourcing (5)
    "molorigin-structure-templates",
    "molorigin-assay-literature",
    "molorigin-selectivity-evidence",
    "molorigin-analogue-search",
    "molorigin-compound-sourcing",
})

# Deterministic lexical weights (Evidence: convention — search ranking aid only).
_W_EXACT_NAME = 100
_W_EXACT_TAG = 40
_W_DOMAIN = 25
_W_NAME_TOKEN = 15
_W_APPLICABLE_TOKEN = 10
_W_DESC_TOKEN = 5


def _tokenize(text: str) -> set[str]:
    return {tok for tok in _TOKEN_RE.findall(text.lower()) if len(tok) >= 2 or not tok.isascii()}


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _parse_inline_list(raw: str) -> list[str]:
    text = raw.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    items = [_strip_quotes(part) for part in text.split(",")]
    return [item for item in items if item]


def parse_skill_header(root: Path) -> dict[str, Any]:
    """Read ONLY YAML frontmatter from ``root / SKILL.md`` and count member paths.

    Never reads the Markdown body, ``references/`` contents, or ``scripts/`` contents.
    """
    skill_md = root / "SKILL.md"
    with skill_md.open("rb") as handle:
        head = handle.read(skills.FRONTMATTER_BYTES)
    text = head.decode("utf-8", "replace")
    parts = text.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError(
            f"SKILL.md must open with YAML frontmatter within its first {skills.FRONTMATTER_BYTES} bytes"
        )

    raw_meta: dict[str, Any] = {}
    current_list_key: str | None = None
    for raw_line in parts[1].splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if current_list_key is not None and stripped.startswith("- "):
            item = _strip_quotes(stripped[2:])
            if item:
                raw_meta.setdefault(current_list_key, []).append(item)
            continue
        current_list_key = None
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key in _LIST_KEYS:
            if not value:
                raw_meta.setdefault(key, [])
                current_list_key = key
            else:
                raw_meta[key] = _parse_inline_list(value)
        elif key in _TEXT_KEYS:
            raw_meta[key] = _strip_quotes(value)

    name = raw_meta.get("name", "")
    description = raw_meta.get("description", "")
    if not name or not skills.SKILL_NAME.fullmatch(name):
        raise ValueError(f"invalid or missing skill frontmatter name: {name!r}")
    if not description:
        raise ValueError("skill frontmatter must declare description")

    # Merge tags + triggers into one deduplicated, lowercase-normalized list.
    merged_tags: list[str] = []
    seen_tags: set[str] = set()
    for field in ("tags", "triggers"):
        for item in raw_meta.get(field, ()):
            norm = item.strip().lower()
            if norm and norm not in seen_tags:
                seen_tags.add(norm)
                merged_tags.append(norm)

    domain_raw = raw_meta.get("domain") or raw_meta.get("family") or ""
    domain = domain_raw.strip().lower() if domain_raw else None

    maturity_raw = raw_meta.get("maturity", "").strip().lower()
    maturity = maturity_raw if maturity_raw in _MATURITIES else None

    ref_count = 0
    script_count = 0
    refs_dir = root / "references"
    if refs_dir.is_dir() and not skills.redirected(refs_dir):
        ref_count = sum(1 for p in refs_dir.rglob("*") if p.is_file())
    scripts_dir = root / "scripts"
    if scripts_dir.is_dir() and not skills.redirected(scripts_dir):
        script_count = sum(1 for p in scripts_dir.rglob("*") if p.is_file())

    return {
        "name": name,
        "slug": skills.derived_slug(name),
        "description": description,
        "domain": domain,
        "tags": merged_tags,
        "applicable_when": raw_meta.get("applicable_when") or None,
        "invalid_when": raw_meta.get("invalid_when") or None,
        "tools": [t.strip() for t in raw_meta.get("tools", ()) if t.strip()],
        "maturity": maturity,
        "supersedes": raw_meta.get("supersedes") or None,
        "member_counts": {"references": ref_count, "scripts": script_count},
    }


def _inferred_domain(slug: str) -> str:
    """Fallback domain bucket for built-in skills that predate frontmatter ``domain:``."""
    groups = skills.library_catalog()["libraries"]
    if slug in groups["memory"]:
        return "memory"
    if slug in groups["rsi"]:
        return "rsi"
    if slug.startswith("molorigin-") or "data" in slug:
        return "data"
    if any(tok in slug for tok in ("screen", "sweep", "gate", "target")):
        return "screening"
    if any(tok in slug for tok in ("method", "literature", "contract", "regime", "audit", "oracle", "corpus")):
        return "methodology"
    if "campaign" in slug or "generation" in slug or "monitoring" in slug:
        return "campaign"
    return "general"


def _configured_extra_dirs(extra_dirs: list[str] | tuple[str, ...] | None) -> list[Path]:
    raw: list[str] = []
    env_val = os.environ.get(ENV_SKILL_DIRS, "").strip()
    if env_val:
        raw.extend(part for part in env_val.split(os.pathsep) if part.strip())
    if extra_dirs is not None:
        if not isinstance(extra_dirs, (list, tuple)) or any(not isinstance(p, str) for p in extra_dirs):
            raise ValueError("extra_dirs must be a list of absolute directory paths")
        raw.extend(extra_dirs)

    resolved: list[Path] = []
    seen: set[Path] = set()
    for item in raw:
        path = Path(item)
        if not path.is_absolute():
            raise ValueError(f"skill directory must be absolute: {item!r}")
        if any(skills.redirected(p) for p in (path, *path.parents)):
            raise ValueError(f"skill directory cannot contain symlinks or junctions: {item!r}")
        norm = path.resolve()
        if norm not in seen:
            seen.add(norm)
            resolved.append(norm)
    return resolved


def _scan_all_headers(extra_roots: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Scan built-in skills + live extra directories, reading headers only."""
    entries: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen_roots: set[Path] = set()

    # 1. Built-in registered skills.
    for slug in sorted(skills.WORKFLOWS):
        try:
            root = skills.bundle_root(slug)
            resolved = root.resolve()
            if resolved in seen_roots:
                continue
            seen_roots.add(resolved)
            header = parse_skill_header(root)
            domain_basis = "explicit" if header["domain"] else "group_inferred"
            domain = header["domain"] or _inferred_domain(slug)
            entries.append({
                **header,
                "slug": slug,
                "source": "builtin",
                "surface_tier": "active_v2" if slug in ACTIVE_V2_BUILTIN_SKILLS else "legacy",
                "domain": domain,
                "domain_basis": domain_basis,
                "_root": root,
            })
        except (OSError, ValueError, KeyError) as exc:
            skipped.append({"skill": slug, "source": "builtin", "reason": str(exc)})

    # 2. Live-scanned generated / project-local skill directories (no server restart needed).
    for directory in extra_roots:
        if not directory.is_dir():
            skipped.append({"directory": str(directory), "source": "generated", "reason": "directory does not exist"})
            continue
        try:
            children = sorted(directory.iterdir())
        except OSError as exc:
            skipped.append({"directory": str(directory), "source": "generated", "reason": str(exc)})
            continue
        for child in children:
            if len(entries) >= MAX_SCAN_SKILLS:
                skipped.append({"directory": str(directory), "source": "generated", "reason": "scan cap reached"})
                break
            if not child.is_dir() or not (child / "SKILL.md").is_file():
                continue
            if skills.redirected(child):
                skipped.append({"skill": child.name, "source": "generated", "reason": "symlinked skill directory refused"})
                continue
            resolved = child.resolve()
            if resolved in seen_roots:
                continue
            seen_roots.add(resolved)
            try:
                header = parse_skill_header(child)
            except (OSError, ValueError) as exc:
                skipped.append({"skill": child.name, "source": "generated", "reason": str(exc)})
                continue
            domain_basis = "explicit" if header["domain"] else "unclassified"
            domain = header["domain"] or "generated"
            entries.append({
                **header,
                "source": "generated",
                "surface_tier": "generated",
                "domain": domain,
                "domain_basis": domain_basis,
                "_root": child,
            })

    return entries, skipped


def _score_entry(
    entry: dict[str, Any],
    query_lower: str,
    query_tokens: set[str],
    requested_tags: set[str],
) -> tuple[int, list[str]]:
    score = 0
    matched_on: list[str] = []

    slug_lower = entry["slug"].lower()
    name_lower = entry["name"].lower()
    tags_set = set(entry["tags"])

    if query_lower:
        if query_lower in {slug_lower, name_lower}:
            score += _W_EXACT_NAME
            matched_on.append("exact_name")
        elif query_lower in slug_lower or query_lower in name_lower:
            score += _W_EXACT_NAME // 2
            matched_on.append("name_substring")

        tag_hits = sorted(tags_set & query_tokens)
        if query_lower in tags_set and query_lower not in tag_hits:
            tag_hits.append(query_lower)
        if tag_hits:
            score += _W_EXACT_TAG * len(tag_hits)
            matched_on.append("tags:" + ",".join(tag_hits[:4]))

        if entry["domain"] in query_tokens or query_lower == entry["domain"]:
            score += _W_DOMAIN
            matched_on.append("domain:" + entry["domain"])

        name_toks = _tokenize(f"{slug_lower} {name_lower}")
        name_hits = sorted(name_toks & query_tokens)
        if name_hits:
            score += _W_NAME_TOKEN * len(name_hits)
            matched_on.append("name_tokens:" + ",".join(name_hits[:4]))

        if entry["applicable_when"]:
            app_hits = sorted(_tokenize(entry["applicable_when"]) & query_tokens)
            if app_hits:
                score += _W_APPLICABLE_TOKEN * len(app_hits)
                matched_on.append("applicable_when:" + ",".join(app_hits[:4]))

        desc_hits = sorted(_tokenize(entry["description"]) & query_tokens)
        if desc_hits:
            score += _W_DESC_TOKEN * len(desc_hits)
            matched_on.append("description:" + ",".join(desc_hits[:4]))

    if requested_tags:
        req_hits = sorted(tags_set & requested_tags)
        if req_hits:
            score += _W_EXACT_TAG * len(req_hits)
            matched_on.append("requested_tags:" + ",".join(req_hits[:4]))

    return score, matched_on


def _render_card(entry: dict[str, Any], *, score: int, matched_on: list[str]) -> dict[str, Any]:
    root: Path = entry["_root"]
    if entry["source"] == "builtin":
        read_handle = {
            "tool": "moldarwin_skill_read",
            "arguments": {"slug": entry["slug"]},
        }
    else:
        # Hash ONLY the returned top-K generated skills so scanning hundreds stays header-only.
        manifest, _ = skills.snapshot(entry["slug"], bundle_ref={"root": str(root)})
        read_handle = {
            "tool": "moldarwin_skill_read",
            "arguments": {
                "slug": entry["slug"],
                "bundle_ref": {
                    "root": str(root),
                    "manifest_sha256": manifest["manifest_sha256"],
                },
            },
        }
    card: dict[str, Any] = {
        "slug": entry["slug"],
        "name": entry["name"],
        "source": entry["source"],
        "surface_tier": entry.get("surface_tier", "active_v2"),
        "domain": entry["domain"],
        "domain_basis": entry["domain_basis"],
        "tags": entry["tags"],
        "description": entry["description"],
        "member_counts": entry["member_counts"],
        "read": read_handle,
    }
    if entry["applicable_when"] is not None:
        card["applicable_when"] = entry["applicable_when"]
    if entry["invalid_when"] is not None:
        card["invalid_when"] = entry["invalid_when"]
    if entry["maturity"] is not None:
        card["maturity"] = entry["maturity"]
    if entry["tools"]:
        card["tools"] = entry["tools"]
    if matched_on:
        card["matched_on"] = matched_on
        card["score"] = score
    return card


def find_skills(
    query: str = "",
    *,
    domain: str | None = None,
    tags: list[str] | None = None,
    source: str | None = None,
    extra_dirs: list[str] | tuple[str, ...] | None = None,
    include_retired: bool = False,
    include_legacy: bool = False,
    list_domains: bool = False,
    limit: int = 5,
) -> dict[str, Any]:
    """Tier-1 lazy skill discovery over active v2 built-in and live generated skill directories.

    Reads only frontmatter headers (never full bodies or references). Hides overlapping
    legacy built-in skills by default (``include_legacy=False``) based on the 6-campaign
    Verb Census; set ``include_legacy=True`` to search all historical bundles. When
    ``list_domains`` is true, returns a compact domain/tag taxonomy histogram without
    returning skill cards.
    """
    if not isinstance(query, str):
        raise ValueError("query must be text")
    if domain is not None and (not isinstance(domain, str) or not domain.strip()):
        raise ValueError("domain must be nonempty text or null")
    if source is not None and source not in {"builtin", "generated"}:
        raise ValueError("source must be 'builtin', 'generated', or null")
    if tags is not None and (
        not isinstance(tags, (list, tuple)) or any(not isinstance(t, str) or not t.strip() for t in tags)
    ):
        raise ValueError("tags must be a list of nonempty strings")
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be an integer in 1..{MAX_LIMIT}")

    extra_roots = _configured_extra_dirs(extra_dirs)
    entries, skipped = _scan_all_headers(extra_roots)

    # Filter retired and (by default) legacy overlapping built-in skills.
    non_retired = [e for e in entries if include_retired or e["maturity"] != "retired"]
    retired_hidden = len(entries) - len(non_retired)
    active_entries = [
        e for e in non_retired if include_legacy or e.get("surface_tier") != "legacy"
    ]
    legacy_hidden = len(non_retired) - len(active_entries)

    if list_domains:
        by_domain: dict[str, int] = {}
        by_source: dict[str, int] = {"builtin": 0, "generated": 0}
        tag_counts: dict[str, int] = {}
        for item in active_entries:
            by_domain[item["domain"]] = by_domain.get(item["domain"], 0) + 1
            by_source[item["source"]] = by_source.get(item["source"], 0) + 1
            for tag in item["tags"]:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        top_tags = [
            {"tag": tag, "count": count}
            for tag, count in sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:30]
        ]
        return {
            "schema": "moldarwin-skill-index/1",
            "mode": "taxonomy",
            "total_skills": len(active_entries),
            "retired_hidden": retired_hidden,
            "legacy_hidden": legacy_hidden,
            "by_domain": dict(sorted(by_domain.items())),
            "by_source": by_source,
            "top_tags": top_tags,
            "coverage": {
                "scanned_skills": len(entries),
                "skipped_entries": skipped,
                "extra_dirs": [str(p) for p in extra_roots],
                "bodies_read": 0,
            },
        }

    domain_filter = domain.strip().lower() if domain else None
    requested_tags = {t.strip().lower() for t in (tags or ())}
    query_lower = query.strip().lower()
    query_tokens = _tokenize(query_lower)

    candidates: list[tuple[int, str, dict[str, Any], list[str]]] = []
    for item in active_entries:
        if source is not None and item["source"] != source:
            continue
        if domain_filter is not None and item["domain"] != domain_filter:
            continue
        if requested_tags and not (requested_tags <= set(item["tags"])):
            continue
        score, matched_on = _score_entry(item, query_lower, query_tokens, requested_tags)
        if query_lower and score == 0:
            continue
        candidates.append((score, item["slug"], item, matched_on))

    # Highest score first, deterministic alphabetical tie-break on slug.
    candidates.sort(key=lambda row: (-row[0], row[1]))
    selected = candidates[:limit]
    cards = [_render_card(item, score=score, matched_on=matched_on) for score, _, item, matched_on in selected]

    return {
        "schema": "moldarwin-skill-index/1",
        "mode": "search",
        "query": query,
        "filters": {
            "domain": domain_filter,
            "tags": sorted(requested_tags),
            "source": source,
            "include_retired": include_retired,
            "include_legacy": include_legacy,
        },
        "skills": cards,
        "coverage": {
            "scanned_skills": len(entries),
            "active_skills": len(active_entries),
            "retired_hidden": retired_hidden,
            "legacy_hidden": legacy_hidden,
            "matched_skills": len(candidates),
            "returned_skills": len(cards),
            "truncated": len(candidates) > len(cards),
            "skipped_entries": skipped,
            "extra_dirs": [str(p) for p in extra_roots],
            "bodies_read": 0,
        },
        "selection_basis": "deterministic_frontmatter_match; host decides whether to load via moldarwin_skill_read",
        "ranking_weights_evidence": "convention",
    }


def write_generated_skill(
    directory: str | Path,
    *,
    name: str,
    description: str,
    body: str,
    domain: str,
    tags: list[str] | tuple[str, ...],
    applicable_when: str,
    invalid_when: str,
    maturity: str = "draft",
    tools: list[str] | tuple[str, ...] | None = None,
    supersedes: str | None = None,
    references: dict[str, str] | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Publish a fine-grained generated skill bundle with structured Tier-1 routing frontmatter.

    Writes ``<directory>/<name>/SKILL.md`` (plus optional ``references/...`` files) atomically
    and validates the resulting bundle via :func:`moldarwin.skills.snapshot`, so it becomes
    immediately discoverable by :func:`find_skills` and readable via ``moldarwin_skill_read``
    without restarting the MCP server.
    """
    if not isinstance(name, str) or not skills.SKILL_NAME.fullmatch(name):
        raise ValueError(f"invalid skill name {name!r}; use lowercase letters, digits, and hyphens")
    for label, text in (
        ("description", description),
        ("domain", domain),
        ("applicable_when", applicable_when),
        ("invalid_when", invalid_when),
        ("body", body),
    ):
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{label} must be nonempty text")
    if maturity not in _MATURITIES:
        raise ValueError(f"maturity must be one of {sorted(_MATURITIES)}")
    clean_tags = [t.strip().lower() for t in tags if isinstance(t, str) and t.strip()]
    if not clean_tags:
        raise ValueError("tags must contain at least one nonempty routing tag")

    base = Path(directory)
    if not base.is_absolute():
        raise ValueError("skill output directory must be absolute")
    if any(skills.redirected(p) for p in (base, *base.parents)):
        raise ValueError("skill output directory cannot contain symlinks or junctions")

    bundle_dir = base / name
    if bundle_dir.exists() and not overwrite:
        raise FileExistsError(f"skill bundle already exists: {bundle_dir}; pass overwrite=True or version the name")

    def _one_line(val: str) -> str:
        return " ".join(val.strip().splitlines())

    front_lines = [
        "---",
        f"name: {name}",
        f"description: {_one_line(description)}",
        f"domain: {domain.strip().lower()}",
        "tags: [" + ", ".join(dict.fromkeys(clean_tags)) + "]",
        f"applicable_when: {_one_line(applicable_when)}",
        f"invalid_when: {_one_line(invalid_when)}",
        f"maturity: {maturity}",
    ]
    if tools:
        clean_tools = [t.strip() for t in tools if isinstance(t, str) and t.strip()]
        if clean_tools:
            front_lines.append("tools: [" + ", ".join(dict.fromkeys(clean_tools)) + "]")
    if supersedes:
        front_lines.append(f"supersedes: {_one_line(supersedes)}")
    front_lines.append("---")

    skill_text = "\n".join(front_lines) + "\n\n" + body.strip() + "\n"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "SKILL.md").write_text(skill_text, encoding="utf-8")

    for rel, content in (references or {}).items():
        skills._canonical_member(rel)
        target = bundle_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    slug = skills.derived_slug(name)
    manifest, _ = skills.snapshot(slug, bundle_ref={"root": str(bundle_dir)})
    return {
        "slug": slug,
        "name": name,
        "root": str(bundle_dir),
        "manifest_sha256": manifest["manifest_sha256"],
        "bundle_ref": {"root": str(bundle_dir), "manifest_sha256": manifest["manifest_sha256"]},
        "member_count": len(manifest["files"]),
    }


__all__ = [
    "ACTIVE_V2_BUILTIN_SKILLS",
    "ENV_SKILL_DIRS",
    "find_skills",
    "parse_skill_header",
    "write_generated_skill",
]
