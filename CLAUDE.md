## 认识论层升级期约定(2026-11 起)

### 固定术语 — 不要同义改写
- `completion` 计算是否跑完 / `verification` 是否通过声明的检查 / `admission` 结果是否可作为科学结论的依据
- `relied_on` 作为前提被依赖(admission 沿此边传播) / `used` 仅作为输入(不传播)
- 不用"审计""校验"代替 admission。不单独用"准确率":说明指的是重复性,还是与实测量的一致性

### 已撤回的固定术语(2026-11-10)

`soundness`、`progress`,以及"必须写作 precision / validity"这条用词强制,自固定术语撤回。

- 撤回的理由:这三者只以"请宿主填写"的形式存在,而按本仓库自己的说法(`.claude/skills/etalon-step-corpus/SKILL.md`),此处填入的推断值"与实测值事后不可区分" —— 那正是 `admission` 要防的失败。要求宿主填写一个无人计算的字段,是在制造不可区分性。
- **不改为导出字段**,理由是仓库自己的论证:`Consequence` 的说明写着"band 与 consequence 是两个问题,一个字段答不了两个"。`soundness` 的内容已由 `Ruling` 的 `blocking`/`waived`/`bounded`/`unverifiable`/`unchecked` 五分与 `Consequence` 的 `WRONG_SUBJECT`/`WRONG_SIZE`/`UNVERIFIABLE` 更精确承载;再加一个三值汇总是有损重述,会诱使读者用汇总而丢掉分区。
- `precision` / `validity` 在 `src/etalon` 已被占用 7 处与 53 处(后者横跨三种含义),一条在源码里处处冲突的用词约定不是约定。纪律保留在上一节,被撤回的只是对这两个 token 的强制。
- 真正缺的东西及其归属:每个 fault 自己声明"可修复 / 终止",而不是由一个汇总字段去枚举。那是 Zone C 的改动(fault catalogue 定义什么算结果),属于负责人的决定,不并入清理。

**撤回的执行点是写入处,不是本文件。** `src/etalon/research/reserved_bindings.py` 在记录写入时拒绝这两个名字:`Artifact` / `Experiment` 的 `bindings` 里出现 `soundness` 或 `progress` 一律报错,并在错误信息里说清该去读什么。实测过洞是真的(2026-11-10,`bindings={'soundness': 'sound'}` 原样写入又原样读回);定字段记录本来就拒绝(TypeError)。

这是本轮的一个方法纠正:第一版把撤回交给一个**在 28 个 skill 文件里用正则抓"填写"指令**的测试来守,那是用 prose 去管 prose —— 而本轮恰恰证明 prose-as-discipline 不成立。那个探针两次静默地匹配到零。正确的问题不是"正则怎么写得更准",而是**为什么一个不存在的字段能被写进记录**。填不进去的字段,不需要任何文档来禁止它。

依据与核查见 `docs/thin-harness/FIXED_TERMINOLOGY_STATUS.md` §6;危险本身由 `tests/test_reserved_bindings.py` 守,本文件与 source 的一致性由 `tests/test_normative_consistency.py` 的 J4 守。删掉本节不会让约束失效 —— 这正是本文件要变成 enforcement 索引的意思。

### 硬约束
1. 不改 `rule(Measurement) -> Ruling` 的语义。节点级 admission 是新增的只读导出视图。
2. 导出视图不回写叶子记录。
3. admission 状态变更保留旧值与 claim scope,照 `supersedes` 的语义,不擦除。
4. `admission` 在 dispatch 时写入,不允许事后回填。
5. 任何新数字带 Evidence 来源(`measured_here` / `measured_in_an_asset` / `literature` / `convention`)。convention 不得呈现为 measurement。
6. 不动 `asset/` 下的 MolCascade / MolQuarry / PRISM。不合并 RuntimeStore / CampaignStore / ResearchJournal —— **"合并"指的是记录命名空间**(2026-11-10 定义):共用文件与共用事务是允许的且本来就是设计(`ResearchJournal` 是 `CampaignStore` 上的前缀视图),不允许的是共用键空间或往别人的命名空间里写。理由:每个 store 本身就是一组拒绝,合并后一行记录可以走最弱的那套规则写入、却被当成带着最强的那套来读。由 `tests/test_hard_constraint_enforcement.py::test_c6_*` 执行。
7. 数不出来的量报告为未取到,不用估计值替代。
