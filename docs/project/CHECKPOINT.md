# 检查点

2026-10-25：W02 成员生命周期最小修复，**从 81f364f 重新实现，未恢复 804d488**。本轮用户取消了必须取得 804d488 的前置要求。

## 恢复、范围与根因

- 实际原工作树 `/workspace/image-to-cad` 为干净的 `work@900511b`，保持不变。检查本项目本地 refs、worktree、reflog、`/workspace` 与 `/tmp` 中相关补丁/仓库记录及共享下载目录，没有 804d488 或完整补丁；可访问的原执行记录只有本线程、此前的隔离快照与研究产物。没有重置、清理或删除分支，也未假称能访问另一个已退出的执行环境。
- `git ls-remote --heads origin` 仍为 `main@81f364f`。创建命令：`git worktree add -b fix/w02-member-lifecycle-rebuilt /workspace/work/w02-member-lifecycle 81f364f`。此前只读分析保存在 `/workspace/work/origin-main/docs/project/CHECKPOINT.md`；其指定基线阻断结论被本轮新授权替代，历史工件缺失事实仍成立。
- `_arbitrate_texts` 因结构边缘使中文整行 `replacement_safe=False`；`finalize_content_ownership` 随后按整行标记重新分配，把原已独立归给文字的成员一并撤销。本轮观察到第一轮 text 归属从 1,817 降至 899，丢失 918 个已归属成员像素。后续完整载体补全受结构边缘阻断，跨候选保护又令部分旧轮廓保持可见，形成 54 个已证明源核残留覆盖像素。
- 生产改动仅在 `content_ownership.preserve_verified_text_members` 与 `optimized_trace._assign_and_reconcile` 的调用处：保留仲裁前已独占归 text、目前仍有原生替换且匹配完整来源证明的成员。匹配文本、bbox、quad、character_boxes、source，并要求证明中的所有行仍可输出 TEXT。遇到受保护强源核则不保留该行成员；不把 line/logo/signature/residual 转给文字，仅从 graphic 恢复原有成员。
- 整行降级、格线保护、完整载体补全和跨候选保护规则均未放宽。未扩大删除框、删除共享 PATH、隐藏旧成员或修改完整性标记；source_adapter、0.1.1 原测试/报告/基线与冻结证据不变。没有补齐新来源像素的代码。

## 来源身份与实际局部结果

原件仍为 `warehouse-electrical-vector.pdf` 第 2 页、136 DPI；W02 裁片 `[4080,2200,4390,2410]`，干净对照 `[4463,2558,4592,2659]`。复用原有转录，不运行 OCR 模型。三行源核和载体区间与 81f364f 实际重建及冻结报告的对应数组相同；缓存上下文、来源重放、原生 TEXT 绑定均由既有 source_study / source_adapter 完成，没有新增独立哈希或指纹清单。

| 本轮实际案例 | PASS | FAIL | ABSTAIN | 结果 |
| --- | --- | --- | --- | --- |
| 81f364f W02（本线程已重跑的基线） | 7 | 1 | 4 | 已证明源核残留 54；中文归属缺口/缓存缺口 23/251，英文各 5/233 |
| 重新实现后 W02：Discipline→DisciplineA | 7 | 0 | 5 | 已证明源核残留 0；中文缺口/缓存缺口 23/23，英文各 5/5 |
| 本轮中文改单字回归：专业负责人→专业负责者 | 7 | 0 | 5 | TEXT 与缓存重导出、保存读回成立；整行仍 replacement_safe=False |
| 同页施工图→施工表 | 3 | 0 | 3 | 585 个来源载体像素退出，归属/缓存缺口和残留均为 0 |

统计没有缩小：中文完整载体仍为 1,840 像素，英文共享载体仍为 1,132；582 个中文强源核中 576 个被现有重放归属证明，另 6 个仍未归 text。54→0 仅证明已确认成员退出，不能当作完整来源退出 PASS。

23 个载体归属缺口原样保留，来源构成为 20 个中文、3 个英文。裁片局部区间 `[y,x0,x1)`：

- 中文顶部 14：`[80,103,106)`、`[80,107,110)`、`[81,103,111)`；第二字的逐字框从 y=83 开始，一像素扩展仍漏掉其顶部。此前原 PDF 隔离渲染对应第 2 页 PATH 5334/5335。
- 中文弱边缘 6：`[79,85,87)`、`[79,123,125)`、`[79,144,146)`；生产格线 LSD-000189 的归属带覆盖它们，阻止整载体补全。此前原 PDF 隔离绘制对应 PATH 5330/5344/5355；没有把生产 line 标签当作真实格线角色。
- 英文弱边缘 3：`[113,125,128)`；此前原 PDF 隔离绘制对应 PATH 5374。
- 本轮以实际连通载体与重放 text mask 再次计算：中文缺口=23，英文缺口=5，交集=5。英文的 5 正是 `[79,144,146)` 的 2 个中文弱边缘与 `[113,125,128)` 的 3 个英文弱边缘，不能相加成 28。当前补丁只保留旧独占成员，不以人工 PDF 观察直接转移保护归属。

成员检查以来源核、缓存轮廓顶点和保存后实体几何建立关联，不用跨文件同名句柄认定身份：

- 修复前 3 个可见成员覆盖已证明中文源核，合计 54 个像素。本轮基线工件中的句柄恰为 E0/E1/E2；修复后、缓存重导出及改字保存读回文件中，所有图层均找不到这三个几何形状。生产可见轮廓、source_text_outline_mask、uncertain_text_outline_mask 对已证明源核的交集均为 0。
- 基线 117 个可见非 TEXT 中，上述 3 个是应退出目标；其余 114 个与修复后对象按坐标、属性和笔宽元数据逐一匹配，缺失 0、新增 0，含 21 条 LINE。114 是实测结果，不是预设目标，也不能把其中保留的争议文字来源成员统称为已证明非目标。
- 英文原生 TEXT 保持，格线与其他非退场可见几何保持。缓存重新导出后把中文改成“专业负责者”，另起 Python 进程读回：实际句柄 10D、字符串正确；Discipline、Responsible 正确。正常英文编辑工件仍为 DisciplineA；两种编辑在各自副本中完成。
- 当前基线 `contours[52]` 的源坐标顶点 `(103,80),(103,81),(110,81),(109,80),(107,80),(106,81),(105,80)` 与本轮固定输出中的保留成员相同，可独立绑定为同一来源几何；本轮两工件的局部句柄分别为 E3、E0。它对应上述 14 个中文来源像素，仍保留，不能误当成已退出的三个成员。
- 历史交接旧 E3→新 E0、TEXT 112 和原 804d488 的身份关系仍未核实。本轮 10D、114 等数值没有被当成历史身份关联证据。缺少历史 DXF/缓存或逐成员来源与保存实体顶点记录时保留该限制；当前可复现问题已经独立处理。

## 命令与检查

使用现有临时环境 `/workspace/work/.venv`。所有命令在独立工作树运行；`QT_QPA_PLATFORM=offscreen`，`PYTHONPATH="$PWD:$PWD/cad_photo_to_dxf"`。

新增真实回归在未修复源码上先失败：`test_real_cell_exits_owned_members_after_row_downgrade_and_cache_roundtrip` 得到 `54 != 0`；生产修复后通过。新增 9 个局部参数用例检查文本/bbox/quad/字形范围/来源匹配、受保护源核、缺证明和从未拥有的成员均不能越权退出。

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH="$PWD:$PWD/cad_photo_to_dxf" \
/workspace/work/.venv/bin/python -m pytest -q \
 cad_photo_to_dxf/tests/test_content_ownership.py::test_verified_members_survive_only_with_matching_proof_and_exclusive_source \
 cad_photo_to_dxf/tests/test_content_ownership.py::test_true_structure_line_downgrades_overlapping_editable_text \
 cad_photo_to_dxf/tests/test_content_ownership.py::test_unsafe_text_stays_explicit_graphic_outline_not_default_residual \
 cad_photo_to_dxf/tests/test_content_ownership.py::test_character_stroke_line_candidate_is_arbitrated_to_text \
 cad_photo_to_dxf/tests/test_content_ownership.py::test_logo_text_conflict_preserves_only_exact_overlap_as_residual \
 cad_photo_to_dxf/tests/test_table_text_layout.py::test_real_cell_exits_owned_members_after_row_downgrade_and_cache_roundtrip \
 cad_photo_to_dxf/tests/test_table_text_layout.py::test_normal_processing_export_preview_and_edit_roundtrip \
 cad_photo_to_dxf/tests/test_table_text_layout.py::test_whole_carrier_is_not_suppressed_when_source_or_structure_is_shared \
 cad_photo_to_dxf/tests/test_ownership_commit_veto.py::test_new_committed_piece_still_must_pass_semantic_ownership

/workspace/work/.venv/bin/python -m ruff check --config cad_photo_to_dxf/ruff.toml \
 cad_photo_to_dxf/app/geometry/content_ownership.py cad_photo_to_dxf/app/geometry/optimized_trace.py \
 cad_photo_to_dxf/tests/test_content_ownership.py cad_photo_to_dxf/tests/test_table_text_layout.py
/workspace/work/.venv/bin/python -m compileall -q \
 cad_photo_to_dxf/app/geometry/content_ownership.py cad_photo_to_dxf/app/geometry/optimized_trace.py \
 cad_photo_to_dxf/tests/test_content_ownership.py cad_photo_to_dxf/tests/test_table_text_layout.py
git diff --check
```

结果：**19 passed**；4 个修改 Python 文件 Ruff/编译通过，diff 检查通过。没有运行 33/71/113 项全集或全仓库回归。

两个真实案例仅调用现有 `source_study.make_case` 和 `source_adapter.validate_with_source`，没有调用带额外控制组的 `source_study.run`：

```python
root = Path('/workspace/work/w02-rebuilt-study')  # 复现时选择新目录
for name, crop, rows, edit in (
    ('w02-cell', (4080,2200,4390,2410), candidates(), ('Discipline','DisciplineA')),
    ('w02-single', (4463,2558,4592,2659),
     (_candidate('施工图',(4493,2588,69,41)),), ('施工图','施工表')),
):
    args = make_case(root/name, crop, rows, edit)
    report = validate_with_source(**args)
    print(name, report['summary'], report['source_ledger']['rows'])
```

导入沿用 `tools.drafting_rules.source_study.make_case`、`tools.drafting_rules.source_adapter.validate_with_source`、`tests.test_table_text_layout.candidates`、`tests.test_source_text_layout._candidate`。临时 DXF/cache/report 留在 work，不作为新证据包提交。来源核由重放 `partition_content` + `complete_verified_text_ownership` 与完整 row_masks 相交取得，没有手工剔除像素。

可转移补丁用 `git format-patch --stdout 81f364f..HEAD` 保存，覆盖本轮全部生产源码、局部测试及必要文档；在另一个从 81f364f 建立的干净工作树执行 `git apply --check`。交付分支使用 `delivery/w02-member-lifecycle-rebuilt`，不更新 main，也不创建会触发全套回归的 PR；该分支不匹配仓库现有全量 CI 的 main/fix/** 触发条件。具体提交与下载链接随最终交付给出。

source_adapter 保持只读；无新门禁、验收矩阵、证据包、验证框架或对应脚本。LibreCAD GUI、DWG 往返、真人验收均 **NOT_RUN**。这只是已确认 W02 成员的生产退场修复，不是完整载体、整页、完整表线或整体 CAD 交付通过；剩余项目继续 ABSTAIN。

2026-10-25：真实来源接入阶段 CLOSED，入口 main `e333dc4`。新增只读 `verified-source-carriers-v1`；0.1.1 原规则、引擎、报告和旧基线未改。
W02 三行同文件比较：7 PASS / 5 ABSTAIN → 7 PASS / 1 FAIL / 4 ABSTAIN；中文源核残留已可判，未修生产。既有同页“施工图”干净对照的 585 个源像素验证退出 PASS。
71 项包测试、113 项相关旧回归和 EXACT 保真检查通过；完整证据见 [本轮报告](../../tools/drafting_rules/SOURCE_ADAPTER_ZH.md)。GUI/DWG/真人净收益仍 NOT_RUN。

2026-10-25：从 main `ce89a8d` 复核原型，更新到 0.1.1。GB/T 10609.1-2008 官方 5 页公开正文已读，§3.1 登记正式依据候选；字体标准仅核实官方元数据。
修正表线 OCS/WCS 误判；同一镜像 DXF 由旧版 6 PASS 变为新版 5 PASS / 1 FAIL；非世界 XY 平面弃判。
49 项包测试、113 项相关旧回归、EXACT 保真检查通过。W02 真实单元格仍 7 PASS / 5 ABSTAIN；未接生产、未训练、未进行真人 CAD UAT。

2026-10-25：首个独立制图规则包 `cn-sheet-text-table@0.1.0`。基础 main `900511b5a884421bc372a39fc7f59ded18639ac9`；不改生产链。
真实 W02 双语单元格已运行：3 TEXT，正常编辑 7 PASS / 5 ABSTAIN；超长文字反例 1 FAIL；另加无关轮廓移位 2 FAIL。
正式条文尚未取得；国标候选不可执行。具体命令、最终测试与失败清单见 [规则包报告](../../tools/drafting_rules/REPORT_ZH.md)。

2026-10-24：SOURCE_CANDIDATE。原 main 76b4c8c，原文档检查点 8f78f13。恢复根与归属见 SOURCE_SYNC_RESULT_20261024.md。候选源码保存不表示新的产品验收。

见 [同步结果](SOURCE_SYNC_RESULT_20261024.md)。
