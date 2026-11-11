# 第一轮决定记录

状态:已决定 v1 · 2026-11-05
依据:阶段 0–3 的实跑结果与 Opus 复核(`ADMISSION_PROPAGATION_REVIEW_R1.md`)
作用对象:`RSI_REWARD.md`、`ADMISSION_PROPAGATION.md`、`src/etalon/learn/admission_view.py`

第一部分是项目负责人的决定原文。第二部分是把这些决定落到代码上时查到的事实,
包括一处与硬约束 1 的冲突。第二部分不改变任何决定,只记录每条决定落地时需要的
具体化,以及这些具体化分别由谁作出。

---

## 第一部分 · 决定原文

### 对 RSI_REWARD.md 的三处更正(规范依据本身写错了)

#### U1 · 第 22–23 行:边"已经存在"是错的

原文说前提被记录、准入被记录、而它们之间的关系是一条已经存在的边。**第三句是假的** ——
图节点与 `Ruling` 之间没有任何记录的关系。

改为:前提被记录,准入被记录,**而把二者联系起来的关系尚未被记录,这是第一件要建的东西**。
因为约束 4 禁止回填,这个关系只能从现在起对新记录建立,历史节点永久为 `not_recorded`。

#### U2 · 第二节"不可博弈"的论证不完整

原文的论证只覆盖了**比较**(EXACT 比较没有阈值旋钮),没覆盖**准入决定**。waiver 是一个
旋钮:批准一个 waiver 就能让一条被 `WRONG_SUBJECT` 挡住的测量进来。

补充:奖励只计 `Admission.ADMITTED`。`ADMITTED_UNDER_WAIVER` 是独立枚举值,**不计为赢**,
waiver 的数量单独报告并计入成本。waiver 因此不再是旋钮 —— 转动它只会使分子不计分。

#### U3 · 传播"只会压低"是错的

见 D5。原文的单向性主张被复核推翻,已在实现文档中标注。

### 决定

#### D1 · 奖励不得读 `teaches`,必须重算

`rule()` 会因 3 条 `THRESHOLD` fault 扣下结果,所以它的 admission 混了可博弈的成分。

**决定:**奖励计算一个**只考虑 `Exactness.EXACT` 且 `Consequence.WRONG_SUBJECT` 的 fault**
的独立准入判定,不复用 `Ruling.admission` / `teaches`。`rule()` 的输出保持不变,两者并存。

`DERIVED` 当前为 0 条,所以活的区分只有 EXACT / THRESHOLD 两档;若将来有 fault 用
`DERIVED`,按 `THRESHOLD` 处理(可错向两边,更不可信)。

#### D2 · 5 个在 catalogue 之外的阻断路径

**决定:收进 catalogue。** 一个能挡住准入而不在目录里的路径,使 `catalogue_digest` 无法
覆盖整个阻断面,于是"冻结目录做比较"这条不变式是假的。

收进来之前,`catalogue_digest` 的不变式必须自己声明覆盖不全,并列出那 5 条。
**不允许在未声明的情况下继续使用那条不变式。**

#### D3 · waiver 作为旋钮

**决定:**见 U2。只计 `ADMITTED`,waiver 单独报告并计入成本。

#### D4 · 遗漏 binding 可改善表面状态(复核提出)

不提交某个 binding,就能把 J 从 `withheld` 变成 `not_recorded`。

**决定:`not_recorded` 计为输,不计为中性。** 进分母,不进分子。

第一性原理:奖励数的是有依据的决策;一个无法建立依据的决策不是有依据的决策。所以遗漏
一无所得。这同时是"`not_recorded` 在奖励里怎么算"的答案。

#### D5 · `supports` 的默认值

**决定:默认 `used`,不是 `relied_on`。**

一条未记录类型的边不得被当作前提。把它当前提正是"一条单薄的已准入支持边产出 `admitted`"
的成因。默认 `used` 之后,未记录的边产出 `not_recorded` —— 诚实的答案。

方向与 `admissible.py` 已有的不对称论证一致:扣下一条好测量损失一个分子的信息,放进一条坏
测量损失的是此后每个分子都适用的阈值。

#### D6 · 替换 `truncated` 这个判断依据

`truncated` 为 false 不等于图完整:前提记录取不到时、scoped 图超出跳数时,前提边会被丢掉
而 `truncated` 仍为 false,导致 J 被误判 `admitted`。

**决定:改成正向的完整性断言。** 视图必须要求"每条前提边都已取到且每一跳都在 scope 内",
否则返回 `not_recorded`。**缺少截断标志不是完整性的证据。**

#### D7 · binding 是否带 store 的 status

复核第 3 条:`ruling.admission` ≠ store 实际决定(store 记的是 `status == "ok" and teaches`)。
两个"已准入"的概念能互相不一致。

**决定:binding 必须带上 store 的 status,且不一致时报错。** 不得静默偏向任何一侧 ——
两个真相是正确性问题,不是整洁度问题。

#### D8 · `compare_views` 是否校验图版本

**决定:是。** 与 `catalogue_digest` 同理:两侧图版本不一致的比较不是比较。不一致时拒绝,
不是静默降级。

### 归档与测试缺口

复核报告存进 `docs/thin-harness/`。变异测试暴露的 10 个未被捕获的变异必须补测,优先三类:
`rule()` 在 store 实际使用的参数下的路径(`require_comparator=False`)、两跳以上的传播、
`catalogue_digest` 具体包含哪些字段。

### 下一步的唯一关键路径

**从现在起在 dispatch 时记录 node ↔ Ruling 的链接。** 在那之前:**不要报告任何奖励数字。**

### 环境待办

项目需要一个固定的 Python ≥3.11 环境。本轮结果只能对着 `/tmp/etalon-venv` 的 freeze 复算,
证据强度低于固定环境。

---

## 第二部分 · 落地时查到的事实(2026-11-05,由实现会话记录)

每一条注明是**查到的事实**,还是**为了让决定可执行而作的具体化**。后一类是实现方的选择,
不是项目负责人的决定。以 ⚑ 标记的项需要负责人确认或推翻。

### D2 与硬约束 1 冲突 ⚑(查到的事实)

把那 5 个代码收进 `FAULTS`,会改变 `rule()` 的输出字节。`admissible.py:235` 用
`real = [code for code in blocking if code in BY_CODE]` 决定是否写 "Withheld: …" 这条 note。
所以 `NO_EXPENSIVE_VALUE` 一旦进入 `BY_CODE`,这类 ruling 的 `notes` 就会变,I1 的 pin
随之失效。此外 `preflight_faults()`、`postflight_faults()`、`wrong_subject()` 的返回值也会变,
而这些函数在别处被使用。每个新条目还需要 `phase`、`band`、`evidence`,目前都没有人定。

所以本轮只做 D2 的过渡部分(声明覆盖不全),不收进 catalogue。完成 D2 需要二选一:
放宽约束 1 对 `notes` 文本的要求,或者为这 5 条另立一个目录,不进 `BY_CODE`。

另外,这 5 条在 `CampaignStore` 的行里实际只可能出现 2 条:`Evaluation` 强制值有限,
store 又传 `require_comparator=False`(复核 2.8,已核对)。

### D1 的具体化(实现方选择)

exact 面按以下优先级判定,取最差的一项:
- **store 状态不是 `ok` → `withheld`**:计算没有完成,这是 exact 事实。D7 保证此时 ruling
  本身也不 teach。
- **`blocking` 中有 EXACT∧WRONG_SUBJECT 代码 → `withheld`。**
- **`blocking` 中有不在目录里的代码 → `not_recorded`** ⚑。它们没有 `exactness`,把它们判为
  exact 等于替 D2 作了分类。按 D4,`withheld` 和 `not_recorded` 都计为输,所以这里的选择
  不影响奖励,只影响传播时取到的值。
- **`unchecked` 中有 EXACT∧WRONG_SUBJECT 代码 → `not_recorded`** ⚑。这是新发现的旋钮:
  `rule()` 把不可评估的观察放进 `unchecked`,不挡准入。于是一次修订只要让 exact 检查
  "不可评估",就能避开它触发。exact 面不能把没跑的检查当作通过。
- **`waived` 中有 EXACT∧WRONG_SUBJECT 代码 → `admitted_under_waiver`**(按 U2,不计为赢)。
- **THRESHOLD / DERIVED 代码,不论在哪个列表里,都忽略。**
- 其余情况为 `admitted`。

### 仍然开着的旋钮 ⚑(查到的事实)

如果一个检查根本没有发出观察,ruling 里就完全没有它。从 `Ruling` 本身判断不出某条
exact fault 是"没触发"还是"没检查"。一次修订如果停止发出某条观察,exact 面看不见。
要堵住它,需要每个 endpoint 声明一组必须出现的检查,而这不在本轮范围内。

### 奖励的单位未定义 ⚑(查到的事实)

D3/D4 定了分子和分母怎么计,但"一个决策"对应图里的哪些节点没有定义。`kind` 对所有
非 trace 节点都是推断的。所以本轮不实现任何汇总函数,只实现节点级的 exact 面。
这与"不要报告任何奖励数字"一致。

### D5 的具体化(实现方选择)

`supports` 和 `evaluated_node` 默认为 `used`;人工标签可以把它们改成 `relied_on`。
`premise_basis` 字段因此不再有意义,换成 `unlabelled_candidate_premises`:一个节点上
处于默认状态的人工类边,列出它们的目标,让读者看到哪些可能是前提。
label 键改为 `"<from>|<to>|<kind>"`,解决复核 2.10 的碰撞问题。

### D6 的具体化(实现方选择,依据查到的事实)

两种 builder 的输出不同(已核对):
- **unscoped builder(`graph_memory.py`)不产出任何正向的完整性断言。** 前提记录取不到
  时只写一条 `issues`,这条 `issues` 甚至不带节点 id(`graph_memory.py:363`);目标不在
  `selected` 里的边被静默过滤(`:445`)。所以对 unscoped 图,完整性**永远无法被断言**。
- **scoped builder(`graph_scope.py`)产出 `scope_receipt`**,其中 `reference_coverage_complete`
  是计算出来的(`:388`),被丢掉的边列在 `deliberate_boundary_refs` / `boundary_relations` 里。
  所以 scoped 图可以正向断言完整,条件是:
  - `scope_receipt.schema == "etalon-research-graph-scope/1"`;
  - `reference_coverage_complete is True`,`traversal_complete is True`;
  - 两个边界列表都为空;
  - `scope_receipt.issues == []`,顶层 `issues == []`,`truncated is False`。

不满足时,每个节点在两个面上派生出的 admission 都封顶为 `not_recorded`,理由写
`graph_completeness_not_asserted`;叶子自身的值照常报告。`truncated` 的图不再被拒绝,
改为同样封顶。结果是:在 builder 加上正向断言之前,**任何 unscoped 真实图都只能得到
`not_recorded`**。这正是 D6 原文的意思,并非副作用。

### D7 的具体化(实现方选择)

binding 新增 `store_status`(`Evaluation.status`,∈ `ok`/`failed`/`invalid`/`blocked`)和
`store_admitted`(`observations.admitted`)。以下任一情况都拒绝:
- `store_admitted != (store_status == "ok" and teaches(ruling))`,即与 store 自己的公式不符;
- `teaches(ruling) != store_admitted`,即两个"已准入"不一致。

后果:status 不是 ok、而 `rule()` 判了准入的行(复核 2.3 跑出过这种情况)**无法被绑定**,
该节点因此是 `not_recorded`。
另外,ruling 本身必须内部一致:有 `blocking` ⇔ `withheld`;没有 `blocking` 但有 `waived`
⇔ `admitted_under_waiver`(复核 1.1 / P1)。

### D8 的具体化(实现方选择)⚑

"图版本"按 `graph_view_id`(图内容的 digest)执行:两侧不同、或任一侧缺失时拒绝比较。
同时校验两侧自身的 `view_id`,以发现手工改过的视图。

这样一来,`compare_views` 只比较**同一张图上不同 binding** 的结果。不同修订产生不同的图,
它们之间的比较走奖励汇总,而汇总带 `catalogue_digest`,不走逐节点 diff。
如果原意是图的 schema 版本,改这一处即可。

`compare_views` 同时报告移动的方向(`raised` / `lowered`),回应复核 2.5。

### 第一轮的三处计数差异(已查清)

1. **"282 个 setup error 只有 20 个带原因"是我的解析错误。** pytest 的 section 头只用单个
   `_`,而我的正则要求至少三个。修正后 **283 个 setup error 全部带原因**:239 个缺
   `pydantic`,44 个缺 `rdkit`。实现方报的 282 也是数错了,实际是 283。
   清单见 `/tmp/etalon-setup-causes.txt`。
2. **343 vs 340:汇总是对的,我的清单错了。** 清单里有 3 行不是 pytest 的结果行,是被捕获的
   日志(`ERROR    etalon.mcp:_common.py:374 etalon_resource_feedback raised`,一次;
   `… etalon_devices raised`,两次),它们碰巧以 `ERROR ` 开头。
   以 `^ERROR tests/` 计,是 340 = 57(collection)+ 283(setup)。
3. **`test_standardize_parallel.py` 实际缺 `pyarrow`**,不是找不到 `etalon`(核对了
   collection section 里的 `E` 行)。

### doctor 的缺口(查到的事实)

在这台机器上,`PYTHONPATH=src /usr/bin/python3 -m etalon doctor`(3.9.6)**在 import 时就崩了**:
`ImportError: cannot import name 'StrEnum' from 'enum'`,退出码 1,输出的是 traceback。
`etalon/__main__.py`、`etalon/__init__.py`、`etalon/doctor.py` 里都没有 `sys.version_info`
检查,而 `__main__.py` 会先 import `campaign.pipeline`,根本走不到 doctor。
所以 doctor 无法报告"解释器版本不足"。本轮没有修。
