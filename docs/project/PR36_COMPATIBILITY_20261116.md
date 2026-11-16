# PR #36 兼容核对与修复 — 2026-11-16

本记录承接 [r13 同步记录](ONLINE_R13_SYNC_20261116.md)，范围是已同步源码的测试、维护检查、独立制图规则适配和静态兼容。它不登记新的转换精度、目标 CAD GUI、DWG 往返或 Release 验收。

## 1. 版本、证据与状态

**代码事实：** 从 PR #36 已同步头 `d5c05642de7150b254ccccafb8716bf7dfbab503` 建立独立分支 `fix/r13-compatibility-20261116`。兼容修复分为七个本地提交，主体检查点为 `593b23e1330588ca67040506982147c6caf1d518`，完整来源账本补充保存至 `57719e0fd5e05164e003d20fabcfb757dbe66979`；没有改写 main、历史基线或独立精度研究分支。这些是本地恢复提交，线上提交及检查按实际发布后的 Git/CI 记录对应。

| 提交 | 独立修复范围 |
| --- | --- |
| `bd54664` | 八份生成报告退出跟踪，保留固定提交、blob 和 SHA-256 恢复索引 |
| `5a31c31` | LINE 来源快照的像素中心坐标与 ARC 仿射椭圆测试 |
| `cc3b307` | 逐项审查 r13 的有限栅格保留迁移 |
| `b88519c` | 独立制图规则适配可验证的原生 SOLID HATCH |
| `3e73eaa` | 类型声明、已验证长度的类型窄化，以及两种不完整输入的明确拒绝 |
| `593b23e` | 现有 Ruff 规则下的分层语法和局部名字修复 |
| `57719e0` | 三个 case 的完整 LINE 来源账本、原始缓存字段完整性及同结构身份反例 |

**自动化事实：** 最终完整支持环境检查已完成，结果见第 6 节。首轮之后的独立复核发现，结构身份 payload 本身并不覆盖全部 LINE 来源字段；已为所有 case 追加独立来源账本绑定和相同结构身份的反例，再运行完整单测、保留性、整体 Ruff 和编译。结构身份投影与完整 LINE 来源证明分开，不把前者写成后者的替代证据。

原始线上失败日志、旧新版本比较、保存 DXF、完整身份 payload、测试 XML、环境和源码哈希保存在私有复现资料 `continuation_compatibility/`，不向公开仓库加入真实私图、运行缓存或大体积生成物。本文给出可公开复核的代码、合同和恢复索引。

## 2. 原六项 CI 失败的具体处理

在 d5c0564 的实际 Linux 和 Windows CI 日志中，以下六项失败一致。另有三个 drafting 失败及八份生成报告的仓库卫生问题，分开处理。

| 原失败 | 已核实原因与修复 | 保留的反例或断言 |
| --- | --- | --- |
| `test_formal_exporter_carries_sources[document]` | 文档导出的观测 LINE 使用纸面像素中心，旧测试把像素边界当来源快照。测试改为独立计算 `((x + 0.5) * sx, (height - y - 0.5) * sy)`，并增加非等比纸面尺寸与 drawing scale。单页未标定的旧坐标约定保留。 | 错用边界坐标的快照仍必须拒绝；来源、成员和属性验证没有绕过。 |
| `test_document_export_consumes_arc_and_refuses_ellipse_transform` | 正式纸面导出已支持非均匀变换的 ELLIPSE，旧测试仍要求抛错。改为实际保存 ELLIPSE 后核对六种比例/方向组合、17 个参数点、解析极值和来源属性，并再保存读回。 | 只允许圆的 `transformed_arc` 仍拒绝非相似变换；没有删除该限制。 |
| `test_current_transition_keeps_historical_records_and_source_obligations` | 已同步 r13 的算法身份和两类实际栅格保留变化尚未进入维护合同。经旧 main 与 d5c0564 的独立完整输出比较后建立新版本有限迁移。 | 旧基线不改；未列入清单的 mask、路径、层级或几何变化仍拒绝。完整 LINE 来源另用独立账本核对。 |
| 两个 `test_current_contract_rejects_unreviewed_storage_versions[...]` 参数用例 | 旧算法身份先失败，遮住了各自应验证的 schema/cache 失败。新维护合同显式绑定已审查算法、schema 4、cache 11，再独立验证错误版本。 | 未登记算法、结构版本或缓存版本仍拒绝，没有通配接受。 |
| `test_real_cell_exits_owned_members_after_source_arbitration_and_cache_roundtrip` | 保存结果包含可见原生 HATCH，旧来源渲染器拒绝整个文件而返回未知；测试还假定独立残余必须有至少三个轮廓点。适配有限 HATCH 后，按实际 1/2 点来源 runs、原黑像素、TEXT 归属和 HATCH 来源标记检查。 | 文字源退出、英文不变和非目标保持照常断言；不能用实体数或“看起来没有残留”替代来源证据。 |

对应测试见 [LINE 来源](../../cad_photo_to_dxf/tests/test_line_source_ref.py)、[原生圆弧](../../cad_photo_to_dxf/tests/test_native_arc_pipeline.py)、[保留性迁移](../../cad_photo_to_dxf/tests/test_preservation_transition.py) 和 [单元格文字](../../cad_photo_to_dxf/tests/test_table_text_layout.py)。

### 独立 drafting 适配的边界

真实 W02 保存文件新增的三个 SOLID HATCH 使旧检查器的 edit-isolation 弃判，并使来源渲染失去完整性。这是适配器能力缺口；2026-10-25 的历史残留 FAIL 仍按当时源码和输出保留，不把历史报告改成当前结果。

[DXF 适配器](../../tools/drafting_rules/dxf_adapter.py) 和 [来源适配器](../../tools/drafting_rules/source_adapter.py) 只新增无关联、非渐变、世界 XY 平面、闭合直边的独立 SOLID HATCH。完整实体标签和图层等资源参与非目标隔离指纹。来源覆盖检查包含填充内部；孔洞和亚像素边界存在不确定性时保守弃判，不仅检查轮廓边缘。不支持的 OCS、曲边、开放边界、关联来源或扩展资源仍弃判。

同一实际 W02 输出的三行可在完整来源证据下通过；中文 1,840 个来源像素的残余、未归属和缓存缺口均为 0。缺失缓存归属必须 ABSTAIN；把真实来源恢复为轮廓或实心 HATCH 必须 FAIL。真实填充内部、带孔填充、边界/资源变异和不支持结构均有反例。首轮 LINE/ARC/HATCH 专项为 169 PASS；最终独立 drafting 结果另见第 6 节。

## 3. 有限保留迁移，不重建历史基线

详细合同见 [2026-11-16 保留迁移](../refactor/preservation-transition-20261116.md)、[新精确测量](../refactor/preservation-current-20261116.json) 和 [逐项栅格变化](../refactor/preservation-raster-transition-20261116.json)。旧 main `81f364fbe4eee1df00dadefabaef0d1a72993e6e` 与 d5c0564 在相同环境、相同三个 compact 输入和独立进程中比较；旧 main 重现旧合同的全部字段。

仅 `sample-test` 有以下变化：

- 原先误按物理纸边删除的九像素外圈恢复，恰为 **55,476 个原黑像素**；原 JPEG 对应灰度均为 67–76。旧黑像素删除为 0，外圈内部差异为 0。该检查不推断图像边缘是工程边框。
- **14 条退化轮廓**从人工 bbox 恢复为真实 1/2 点来源 runs，共 **63 个原黑源格**，以可见 SOLID HATCH 保存。
- 连同外圈，实际改变 **15 条 contour / 15 个保存成员**。其余 **423 个保存实体**的完整语义记录和顺序保持，包括所有 229 条 LINE；比较只归一化已核实的全局结构版本标记，不放过其他来源属性。

另外两个 compact case 的完整结构身份和保存记录相同。以下三个旧文件字节不变：

| 历史文件 | SHA-256 |
| --- | --- |
| `preservation-baseline.json` | `e99b745cc6b50a058b5b975f06e4cb58b05ce705e033e692f1ab91f4dc4d27ee` |
| `preservation-current-p10a.json` | `d2abc1f852dd23e389da0455c3482a267a2a4a424471bdc6f46e41d4e3ce6196` |
| `preservation-current-20261024.json` | `9a8ded89dfb5d134d816a615d3dda6e46b99b3d40bf1c3d13ad53be10f502b85` |

维护检查先验证实际新 mask 和每条允许变化，再仅在断言用临时副本中逆投影回历史结构；该副本不进入产品、缓存或导出。**身份投影保护其 payload 实际包含的字段，全部 LINE 来源必须另以独立 ledger 锁定。** `_line_payload` 的几何、笔宽和图层并不意味着 `source_ids`、history 等所有字段都被 `structure_id` 覆盖；即使实体数和结构身份不变，也不能免除来源账本检查。

新增 [完整 LINE 来源账本](../refactor/preservation-line-sources-20261116.json) 绑定三个 case 的 14、229、11 条 LINE，共 254 条。每条记录包含 `x1/y1/x2/y2/width/confidence/layer/source_ids/history/classification_confidence/classification_reasons` 全部 11 个 dataclass 字段，成员及来源列表顺序也参与摘要。检查分别作用于运行结构、加载默认值之前的原始缓存 `lines_json` 和恢复后的结构；缓存缺字段不能被加载器的默认值掩盖。五种几何和 `structure_id` 不变的来源/置信/分类漂移，以及一个缺字段反例，专门验证这个独立合同。

独立审计已核实旧新 raw cache 与恢复结构的全部 254 条记录、11 个字段及顺序完全相同，并在三个 case 上分别实施五种变异和缺字段，共 **15 项变异、3 项缺字段均被拒绝**。原先 source ID 改变却不影响结构身份的反例保留。公开账本合同 SHA-256 为 `48b7636501cf61e433101f61897b7d57286a722368cab13198999eee20d0aa76`；私有逐字段证据为 `line_source_ledger_review.json`，独立防护复核为 `continuation_curve_review/complete_line_ledger_guard_after.json`。

保存 HATCH 另按来源端点、精确源格、标签、显示属性和平面边界检查。负例包含一像素扩张、漏原黑边缘、白像素冒充恢复证据、同大小平移、同四顶点的蝴蝶结、白 true color、invisible 和 transparency。`--baseline` 仍拒绝直接重建历史基线。

## 4. 静态兼容与不完整输入

此前 pytest 失败遮住了后续静态步骤；实际 Ruff 暴露 44 个文件的 495 项既有问题。没有改 Ruff 规则或增加/改变 `noqa`，没有改精度阈值。

| 修复层 | 数量 | 可复核证明 |
| --- | ---: | --- |
| E701/E702 同行语句展开 | 440 项，30 个文件 | 忽略位置后的完整 AST 前后一致 |
| 局部变量、回调和导入 | 55 项，27 个文件，与上一层有交集 | 实际 AST 与显式变换白名单一致；字面量多重集合不变 |

第二层包括 27 处歧义左坐标名、11 个同作用域/同参数/同表达式的 lambda 转局部函数、14 个未使用导入、fixture 的显式同名导出，以及已加载模块的三个名字导入前移。第二层不是“全部 AST 不变”；证明明确记录了有限变化，并由完整测试复核。私有证据为 `lint_layout_ast_equivalence.json`、`lint_explicit_ast_changes.json` 和 44 文件最终哈希绑定 `lint_final_source_binding.json`。

四个规定 mypy 文件另暴露八个类型问题。两个生产文件只补类型声明、已有长度验证后的 tuple 窄化，以及两种原本无法完成计算/序列化的不完整输入的明确失败：

- 纸面标定缺纵向 pixel pitch：抛 `ValueError("Invalid vertical paper calibration")`，不补造比例。
- 观察值有 cell clip bbox 而缺匹配 quad：抛 `ValueError("Cell clip bbox requires a matching quad")`，不序列化为完整证据。

[新增两个反例](../../cad_photo_to_dxf/tests/test_typed_contract_validation.py) 固定该边界；完整合法输入的几何、笔宽和来源合同没有因此改变。

## 5. 八份历史报告可按固定提交恢复

八份 `*.report.json` 是生成报告，退出 Git 跟踪并进入忽略范围，没有改卫生检查器的 allowlist。原始内容仍在固定提交 `d5c05642de7150b254ccccafb8716bf7dfbab503`，恢复索引逐份记录原路径、Git blob、字节数、SHA-256 和固定 URL：

[HISTORICAL_REPORTS.json](../../tools/drafting_rules/evidence/HISTORICAL_REPORTS.json)

[历史规则报告](../../tools/drafting_rules/REPORT_ZH.md) 的八个链接已指向上述固定提交。可使用 `git show <固定提交>:<索引中的原路径>` 恢复，再核 SHA-256；不是删除历史失败，也不以新运行覆盖旧原件。

## 6. 自动化验证与环境边界

最终支持环境为 **CPython 3.11.18、pytest 8.4.2、PySide6 6.11.3、NumPy 2.4.6、OpenCV 4.14.0.94、ezdxf 1.4.5**；Ruff 0.17.5、mypy 1.20.2。涉及 ORT 的过程在导入前禁遥测，并通过进程级 socket 禁用离线执行。

| 实际执行范围 | 结果 |
| --- | --- |
| 完整 unit | **1,728 PASS / 26 SKIP / 0 FAIL**，含新增六项来源账本反例 |
| 独立 drafting | **88 PASS / 0 SKIP / 0 FAIL**，对应代码未变的上一轮实测 |
| 维护保留性检查 | **EXACT** |
| app/test/validation/scripts/main Ruff；独立 drafting Ruff | 均 PASS |
| 规定四文件 mypy；compileall；仓库卫生 | 均 PASS |

26 项 skip 为 18 项缺少专用 TrueType 测试字体，以及 8 项 P2C 官方候选资源未准备，不记录为通过。最终运行前后 **296 个源码/测试/检查文件完全相同**，inventory SHA-256 为 `08197e42eedfc8c9fa85aa7f31550c0b805da72d5482f47d954f3300ff2b97aa`。实际启动时 Git HEAD 是 `593b23e`，同时包含尚未提交的来源账本补充；受测字节随后原样保存为 `57719e0`，不把事后提交号冒充测试启动时的 HEAD。

第一轮完整 unit 的 1,722 PASS 及原始证据保留；补充账本后完整 unit、保留性、整体 Ruff/compileall 已重跑。独立 drafting 的 88 项、四文件 mypy、drafting Ruff/compileall 和卫生检查复用代码未变的已执行结果，未把这些项目写成重复运行。两轮之间的变化只有维护检查、相关测试和独立来源账本。

此前 CPython 3.12 / PySide6 6.11.3 的一次运行有 True 引用计数测试失败；pytest 9.2 还拒绝两个 nested approx 用法，且不在项目声明的 `pytest>=8.3,<9` 范围内。这三个测试没有被改弱。切换到支持的 Python 3.11 / pytest 8.4.2 后，包含原三项、完整 reconciliation、保留迁移及两个类型反例的 **88 项环境复证全部通过**，再完成上述全套。**这不证明 Python 3.12 兼容已通过。**

复现命令与真实工作流一致：

```sh
# 工作目录 cad_photo_to_dxf；运行依赖和测试依赖按仓库 requirements 安装
python -m pytest -q
python ../maintenance/preservation_check.py
python -m ruff check app tests validation scripts main.py
python -m mypy app/core/resolution.py app/core/scale_calibrator.py app/core/reporting.py app/ocr/auxiliary_recognition.py
python -m compileall -q app tests validation scripts main.py
python scripts/check_repository_hygiene.py --repository-root .. --json-output repository-hygiene.json

# 工作目录仓库根目录
python -m pytest -q tools/drafting_rules/tests
python -m ruff check --config cad_photo_to_dxf/ruff.toml tools/drafting_rules
python -m compileall -q tools/drafting_rules
```

最终私有执行总表为 `continuation_compatibility/final_ledger_ci_summary.json`，首轮 `final_ci_summary.json` 原样保留。实际线上 Linux、Windows 打包/安装启动和固定 FreeCAD 作业结果，以 **PR #36 对应提交的独立 CI** 为准；本地通过不预言线上结果。线上检查结果由 CI 记录，不因结果产生而要求再次修改状态文档才能合并；合并和发布仍按既有项目门槛判断。

## 7. 精度研究与人工验收保持独立

独立精度分支 `accuracy/native-grid-compound-parts-20261116` 的检查点 `210817bb43f711d9985acba992cfde66e329f137` 已保留，不并入本次兼容分支。该分支的来源保护、210 项专项和三页完整输出证据有自己的来源绑定，不能加到本次兼容收益中。

后续 source-constrained 曲线 v1.1 在冻结控样的四个清晰弧形阳性组合中恢复了候选，但两个短支线归属反例失败：九种端帽/转角包络保持黑白中心状态，并不证明短支线有权退出原来源。该版本总体失败，未进入 A2、未登记生产导出，未记为真实图纸恢复收益。新 persistent-band 来源带试验具有独立合同，仍在生产之外，不属于本次合并。

本轮没有新增用户 GUI、LibreCAD 编辑保存、DWG 往返、跨编辑器显示或真人净劳动验收。此前已接受的 r13 代表操作仍按 [同步记录](ONLINE_R13_SYNC_20261116.md) 的有限范围保留；兼容 CI 不扩大那项 UAT 结论。
