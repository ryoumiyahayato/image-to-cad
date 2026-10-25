# 检查点

2026-10-25：W02 中文顶部来源边界修复。基线为可访问的 `ece85a401a93f12743e493ac050929bbfd5a8da5` / `delivery/w02-member-lifecycle-rebuilt`；独立分支 `fix/w02-glyph-source-boundary`，工作树 `/workspace/work/w02-glyph-boundary`。原 `work@900511b`、`fix/w02-member-lifecycle-rebuilt@ece85a4` 及其工作树保持干净，未更新 main。804d488 与历史句柄关系不是本轮前置条件。

## 本轮根因与生产来源判定

- `ocr_layout._binary_crop` 的 `_remove_long_rules` 对排版遮罩做长线形态学去除。“业”的竖笔被一并削掉顶部，随后逐字框只见清理后的笔画：本例第二字框为 `(96,83,21,15)`。完整行来源 `row_masks` 却保有未经此过滤的连通字形，含遗漏的 6 个强墨迹像素；生产阈值下对应 14 个像素的可见成员因此落在原字符归属范围外。
- 唯一生产修改在 `ocr_layout.py`：新增 `_restore_verified_character_tops`，只在 `_restore_cell_text_rows` 已通过完整行/单元格来源、全部行替换安全及原生 TEXT 资格检查后，恢复可证明的字符上界，再登记同一 `VerifiedCellTextSource`。
- 证据完全来自实际栅格和已有行证明：每个 CJK 字符须有一个完整、未触及证明边界的强墨迹连通成员；该成员只与一个已有字符横向范围相交，完整落在该范围内，并实际接触原字符主体。只把上界恢复到该成员的真实最小 y；横向范围、下界、OCR bbox、显示 quad 均保持。
- 新增覆盖区按现有 `_candidate_region_mask` 栅格化，使用原始灰度的非白墨迹检查：新增区内每个弱墨迹连通部分须连接该字强源核；遇到分离墨迹或连到行证明以外的强源核，保持原范围。跨字连通、多分量/分离小点、证明边界格线及无主体接触也不恢复。不使用固定边距、PDF PATH 编号、图纸坐标或对象句柄作为生产条件。
- 本例五个强字形成员分别落入五个原有横向范围，第二字的实际源顶端为 y=80；该字框恢复为 `(96,80,21,18)`。其余四字框不变。该位置是测量结果，不是生产常量。
- `preserve_verified_text_members`、结构/共享保护和完整载体补全规则未修改。新的范围先进入原有独占归属，再由 ece85a4 的退场链消费；没有令该函数直接吸收未证明的像素。`source_adapter` 保持只读且源码未改。

## 本轮实测

复用同一 PDF 第 2 页、136 DPI、原转录与原裁片。来源图像逐像素相同，三行完整 `core_runs` / `source_member_runs` 与 ece85a4 一致：中文涉及载体仍为 1,840，英文共享载体仍为 1,132，中文强源核仍为 582。没有剔除统计像素或改变完整性规则。

| 本轮案例 | PASS | FAIL | ABSTAIN | 归属与残留 |
| --- | --- | --- | --- | --- |
| W02 / Discipline→DisciplineA | 7 | 0 | 5 | 顶部新增支持 14/14；载体/缓存缺口 23/23→9/9；已证明源核残留仍 0 |
| 中文改单字局部回归 | 7 | 0 | 5 | “专业负责人→专业负责者”，缓存重导出、保存读回正确；整行结构冲突标记仍保留 |
| 施工图→施工表 | 3 | 0 | 3 | 原 585 像素载体退出，来源/缓存缺口及残留均 0 |

- 顶部恢复为 6 个强墨迹＋8 个弱边缘，共 14 个生产源像素；没有丢失此前文字成员支持。局部 `[y,x0,x1)` 为 `[80,103,106)`、`[80,107,110)`、`[81,103,111)`，仅用于记录实际测量。
- 从 ece85a4 实际缓存的 `contour_binary` 提取与新增支持相交的成员，得到一个完整连通成员，其 14 个像素与新增支持逐像素相等；对应独立闭合轮廓没有其他源像素或共享成员。再以缓存源顶点与 DXF 顶点的坐标变换绑定实体；本轮基线工件的局部句柄为 E0，没有据此假定历史身份。
- 该轮廓退出可见层及所有隐藏层，未进入 `source_text_outline_mask` 或 `uncertain_text_outline_mask`。缓存重导出、改字保存、新进程重开及再次保存后均未出现。完整 582 个已证明中文强源核与可见几何交集为 0，包含先前已修复的 54 个残留覆盖像素。
- 原 114 个非退场可见几何中，本轮单独列出上述一个应退出目标。其余 **113 个**按实际坐标、属性和笔宽元数据逐一匹配：其他缺失 0、新增 0，21 条 LINE 保持。三个原生 TEXT 的原始几何也相同；没有把 114 设为目标数量。
- 缓存内字符框与新进程来源重放的字符框一致。新进程读取再保存、另一个进程重开：TEXT 10C 为“专业负责者”，英文 Discipline / Responsible 正确；正常英文编辑副本为 DisciplineA。当前句柄只用于各自工件内的检查。
- 剩余 **9** 为受格线归属带保护的中文弱边缘 6，加英文弱边缘 3，处理均未改变。英文另报的 5 仍为 `[79,144,146)` 的两个中文弱边缘与 `[113,125,128)` 的三个英文弱边缘；它们全部包含在剩余 9 内，不重复相加。
- 此前 23→9 是实际新增来源支持的结果，不是预设门槛。完整载体退出仍 ABSTAIN；历史旧 E3→新 E0 及 804d488 关系仍未核实，本轮当前成员已独立建立来源关联，不依赖这些历史关系。

## 本轮命令与检查

已读取 AGENTS、当前及基线 CHECKPOINT、交接报告与产品/执行约束。确认远端基线后执行：

```bash
git worktree add -b fix/w02-glyph-source-boundary /workspace/work/w02-glyph-boundary ece85a401a93f12743e493ac050929bbfd5a8da5
```

新增真实边界回归在生产修改前先失败，确认完整行源核仍有未被逐字支持覆盖的顶部；修改后通过。新增 8 个纯栅格分量用例包括正例、分离弱点、外来强源、弱连接的外来强源、跨字共享、边界格线、无主体接触及 ASCII。上一轮新增的真实退场回归只按本轮实际来源结果更新剩余缺口断言；0.1.1 原测试、报告、基线与冻结证据未改。

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH="$PWD:$PWD/cad_photo_to_dxf" \
/workspace/work/.venv/bin/python -m pytest -q \
 cad_photo_to_dxf/tests/test_table_text_layout.py::test_verified_character_tops_cover_unfiltered_glyph_ink_without_expanding_neighbors \
 cad_photo_to_dxf/tests/test_table_text_layout.py::test_verified_character_top_keeps_detached_shared_and_foreign_source \
 cad_photo_to_dxf/tests/test_table_text_layout.py::test_real_cell_exits_owned_members_after_row_downgrade_and_cache_roundtrip \
 cad_photo_to_dxf/tests/test_table_text_layout.py::test_normal_processing_export_preview_and_edit_roundtrip \
 cad_photo_to_dxf/tests/test_table_text_layout.py::test_full_line_source_proof_preserves_layout_and_owns_complete_ink_carriers \
 cad_photo_to_dxf/tests/test_table_text_layout.py::test_uncertain_cells_do_not_invent_row_positions \
 cad_photo_to_dxf/tests/test_table_text_layout.py::test_whole_carrier_is_not_suppressed_when_source_or_structure_is_shared \
 cad_photo_to_dxf/tests/test_table_text_layout.py::test_real_cell_recovers_complete_separate_source_rows_without_approving_touching_letters \
 cad_photo_to_dxf/tests/test_source_text_layout.py::test_cell_clipping_preserves_tight_source_quad_and_clips_at_rule \
 cad_photo_to_dxf/tests/test_content_ownership.py::test_true_structure_line_downgrades_overlapping_editable_text
/workspace/work/.venv/bin/python -m ruff check --config cad_photo_to_dxf/ruff.toml cad_photo_to_dxf/app/ocr/ocr_layout.py cad_photo_to_dxf/tests/test_table_text_layout.py
/workspace/work/.venv/bin/python -m compileall -q cad_photo_to_dxf/app/ocr/ocr_layout.py cad_photo_to_dxf/tests/test_table_text_layout.py
git diff --check
```

结果：**22 passed**；2 个修改 Python 文件 Ruff/编译通过，diff 检查通过。只运行受影响入口，没有运行全量测试、全仓库回归或历史测试全集。

真实研究继续使用前节已记录的 `source_study.make_case`、`source_adapter.validate_with_source` 两案例循环，输出目录换为 `/workspace/work/w02-top-study`；另在全新 Python 进程调用同一只读校验接口，仍为 7 PASS / 0 FAIL / 5 ABSTAIN，来源/缓存缺口均为 9/5/5。缓存使用 `load_trace_cache` → `export_final_structure_dxf`，TEXT 按原字符串定位后保存，独立进程用 ezdxf 重开、再保存、再重开并复查。临时产物仅留 work，没有新验证脚本或证据包。

独立分支提交，并提供相对 ece85a4 的完整补丁；交付分支为 `delivery/w02-glyph-source-boundary`，不更新 main、不创建 PR、不触发仓库 main/fix/** 的全量 CI。补丁通过 `git format-patch --stdout ece85a4..HEAD` 生成，在另一个干净 ece85a4 工作树运行 `git apply --check`；提交及可访问链接随最终交付给出。

LibreCAD GUI、DWG 往返、真人验收均 **NOT_RUN**。不新增门禁、验收矩阵、证据包、验证框架及对应脚本；没有独立计算/比对哈希或生成指纹清单，工具自带来源完整性校验保持。局部边界和轮廓退出不代表完整载体、完整表线、整页或整体 CAD 交付验收通过。

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
