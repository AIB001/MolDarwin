#!/usr/bin/env python3
"""Decide how far the epistemic-layer upgrade goes, from measured values only.

Reads a JSON file of measurements and exits non-zero when a threshold says stop.
Thresholds are conventions chosen for this upgrade, not measurements; they are
printed with the decision so a reader can disagree with the convention rather
than with the arithmetic.

Usage:
    python tools/upgrade_gate.py gate.json

gate.json may hold any subset of these keys. A key that is absent is reported as
not measured and never defaulted to a passing value:

    fate_changed_pct    percentage of molecules whose recorded fate changes when
                        completion/verification/admission are not separated
    true_actives_pct    of those, the percentage that are真阳性
    intersection_n      absolute number of molecules in the measured intersection
    recomputable_pct    percentage of recorded history that can enter training
    corpus_steps        usable step count
    corpus_min_class    smallest per-class step count a later comparison needs
"""

import json
import sys

STOP, PARTIAL, FULL = 2, 1, 0

CONVENTIONS = {
    "fate_changed_pct": (2.0, 10.0),
    "true_actives_pct": (10.0, None),
    "recomputable_pct": (30.0, None),
    "corpus_steps": (500, None),
    "corpus_min_class": (50, None),
}


def main(path: str) -> int:
    with open(path, encoding="utf-8") as handle:
        m = json.load(handle)

    lines, verdict, notes = [], FULL, []

    def get(key):
        if key not in m or m[key] is None:
            lines.append(f"  {key:<20} NOT MEASURED")
            return None
        lines.append(f"  {key:<20} {m[key]}")
        return m[key]

    lines.append("measured:")
    fate = get("fate_changed_pct")
    actives = get("true_actives_pct")
    inter = get("intersection_n")
    recomp = get("recomputable_pct")
    steps = get("corpus_steps")
    minclass = get("corpus_min_class")

    if fate is None:
        notes.append("B 数字未测 ⇒ 不要开始实现。先跑 P0。")
        verdict = STOP
    elif fate < CONVENTIONS["fate_changed_pct"][0]:
        notes.append(f"命运改变 {fate}% < 2% ⇒ admission 是工程卫生。降为工程 note,不重构。")
        verdict = STOP
    elif fate < CONVENTIONS["fate_changed_pct"][1]:
        notes.append(f"命运改变 {fate}% 在 2–10% ⇒ 只做 admission 传播,跳过 skill 发射点改造。")
        verdict = max(verdict, PARTIAL)
    else:
        notes.append(f"命运改变 {fate}% > 10% ⇒ 全量升级,且尽早(每个新 campaign 增加需重算的记录)。")

    if actives is not None and actives < CONVENTIONS["true_actives_pct"][0]:
        notes.append(f"其中真阳性 {actives}% < 10% ⇒ 效应多半落在不重要的分子上。按 2% 以下处理。")
        verdict = STOP
    if inter is not None and inter < 10:
        notes.append(f"交集仅 {inter} 个分子 ⇒ 欠功效。这个数用于定前瞻实验规模,不要当结论。")

    if recomp is None:
        notes.append("可重算比例未测 ⇒ 不要改历史记录。先跑 recomputability-audit skill。")
        verdict = max(verdict, PARTIAL)
    elif recomp < CONVENTIONS["recomputable_pct"][0]:
        notes.append(f"可重算 {recomp}% < 30% ⇒ 传播只对新记录生效,历史整批标旧分区不重算。")
        verdict = max(verdict, PARTIAL)

    if steps is not None and steps < CONVENTIONS["corpus_steps"][0]:
        notes.append(f"可用 step {steps} < 500 ⇒ 报告数量,不要训练模型。")
    if minclass is not None and minclass < CONVENTIONS["corpus_min_class"][0]:
        notes.append(f"最小类 {minclass} < 50 ⇒ 该类不足以支撑比较。")

    print("\n".join(lines))
    print("\nthresholds (convention, not measurement):")
    for key, (low, high) in CONVENTIONS.items():
        print(f"  {key:<20} low={low}" + (f" high={high}" if high else ""))
    print("\ndecision:", {FULL: "FULL", PARTIAL: "PARTIAL", STOP: "STOP"}[verdict])
    for note in notes:
        print("  -", note)
    return verdict


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(64)
    raise SystemExit(main(sys.argv[1]))
