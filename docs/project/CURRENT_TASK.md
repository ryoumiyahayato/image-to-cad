# 当前任务：接触文字与独立邻线、普通主图和 EXE

> 2026-11-24 收口记录。普通主图、417 保护账本、全部新增保存检查及最终对照已完成；同版本 Windows 实际 EXE 已核实，PR #48 已合入 main `5e146bedc95c6dabef178d575a4a88f8b90272dc`，合入 tree 与执行 tree 精确相同。c241 代表 GUI 与最终版共同实体桥接通过，原严格保存 FAIL 保留，没有在 cbac 重复 GUI。产品 `0.3.0-dev / LOCAL_NO_GO`，保存兼容 `LIMITED`，工程师工时验收 `NOT_RUN`。

执行提交 `cbac773b197daee7c8f0baec1a8abfdeb33e30d1`，tree `bc5e5b0e554870b54d009672c361bfd74e2e4a1d`。本地 **2858 passed／28 skipped，ruff PASS**。普通主图、实际 EXE 和最终 main 分别记录版本；文档提交不替代执行锚点。源码主图与 Windows 分别绑定实际字体资源；恢复源码检查点时必须还原对应资源，不能用另一平台字体继承检查结论。

## 固定范围与实际保存结果

以 `QUARTER_labels_343e0f7.dxf` 的 417 个正式顶层对象为基线，沿用同一冻结 A2 四分之一区域、200 DPI、纸面毫米及普通 `native-objects`。有效原始观察可复用，受影响采用、来源归属、组装、保存冷读和预览重新执行，不向旧 DXF 拼对象。

| 固定位置 | 来源与边界 | 最终保存主图 |
| --- | --- | --- |
| LAUNDRY | 文字与整条穿越曲线有原图依据；右端 D 圆仍未正式恢复 | 完整恢复：1 TEXT＋1 独立 LWPOLYLINE |
| 213 上方 BEDROOM | 曲线右端到原图已确认、主 DXF 尚未恢复的 E 圆边 | 完整恢复：1 TEXT＋1 独立 LWPOLYLINE |
| `2LP-10,12` | 完整转写可靠，但字体会使首个 1 新碰独立圆边，布局门拒绝 TEXT | 文字待修；原圆、接线、下划线和原字形横划全部保持 |
| EBB-3 | 完整曲线有来源，文字仍未确认 | 仅新增 1 独立 LWPOLYLINE，文字待修 |
| 冻结后保留的同类位置 | 外部分叉未证明，0 条完整路径，0 次补充 OCR | 文字和接触路径仍待修，没有插入断头路径 |

实际保存为 **2／5 个完整目标，3 个仍有待修内容**。新增 2 条完整 TEXT、三条目标完整曲线，另有右侧 `2LP-11,13` 附近一条自然恢复的独立下划线；旧 TEXT 修正为 0。仅当完整文字与独立完整图线同时成立，才计一个完整位置。其他纯转写分歧继续单列，不用残缺前缀冒充完整标签。

## 通用修改与边界

原图路径按方向连续性和有限分叉证明追踪到实际端点或可靠接点；裁框边缘、字框内短枝不能充当独立图线终端。文字与线可以共享真实接触墨迹；派生识别图不填白缝、不增加字符证据。完整采用同时绑定原始转写、全行字形和标点；宽原始观察仍有源后缀时，窄前缀不得采用。

邻圆保护使用重放通过的原始字形／标点像素责任，避免整块文字框误吞真实圆边。新白缝门只核验已证明独立邻圆与字形间的原始白缝，检查既有字体的完整 TEXT 轮廓；出现新增接触时保留可靠转写为待修，不改字、不拆字、不移动邻线或放宽识别。真实原图接触和普通 O／0 保持。保存冷读使用实际 TEXT 的位置、字高、宽度和旋转；完成检查点绑定新增依赖，缺证不能绕门。

历史失败独立保留：`ab9a08d` **保存来源 PASS／417 保护 FAIL**；`c241191` 原圆和旧曲线端点已恢复，但实际对照发现 `2LP-10,12` 的字体封闭原白缝，**视觉 FAIL**。两版文件、账本与检查点保留，不能将单项来源 PASS 改写成完整交付通过。

## 最终普通主图与核验

| 项目 | 实际结论 |
| --- | --- |
| 普通主图 | `QUARTER_contact_cbac773.dxf`，185418 B；任务 `COMPLETED_WITH_ISSUES`，exit 0 |
| SHA256 | `3ffaa79bce32447a19077c6b6f4eb47b955003ddb1af89aa2d3f1f4671e3ab4a` |
| 正式对象 | **417 + 2 TEXT + 4 LWPOLYLINE = 423**；另 48 个 REVIEW，不计正式成果 |
| 原有对象和 BLOCK | 417 个全部精确保留，0 退场、0 改变；原五标签、房号、圆标记、门墙及完整路径保持 |
| 保存、来源和重复 | 普通整区完整冷读 PASS，0 结构错误／修复、0 精确重复线段；全部新增来源检查 PASS |
| 全部新增编辑隔离 | 2 TEXT、4 路径的 14 次程序编辑＋一次无编辑普通保存重开全部 PASS，47 BLOCK 保持；不是 GUI 全量操作 |
| 原图／旧版／新版对照 | 已实际打开 11 张重点对照及 1 张最终整区预览；见 `ROOT_VISUAL_INSPECTION.json` |
| c241 GUI 到最终版桥接 | 422 个共同正式对象、47 BLOCK、文字样式与字体字节精确相同，四个代表对象相同，PASS；不升级原 GUI strict FAIL |
| 同版本 Windows 实际 EXE | [run 45415693790／#681](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45415693790) 成功；实际触发接触处理，新增 1 TEXT＋1 独立路径；四组 8／8 保存来源冷读、10／10 CI 编辑读回 PASS |
| main 集成 | [PR #48](https://github.com/ryoumiyahayato/image-to-cad/pull/48)，`5e146bedc95c6dabef178d575a4a88f8b90272dc`；父提交为原 main 534fb97 与执行 cbac773，合入 tree 完全相同 |
| 恢复入口 | `recover_contact.py` 已实际查询成功；阶段包 `CONTACT_STAGE02_FINAL_MAIN_cbac773.zip` 已保存；最终私有交付名 `CONTACT_FINAL_RECOVERY_cbac773.zip` |

后续文档提交仅修改本轮四份 Markdown，不改变实际运行版本。旧历史远端分支清理继续 `BLOCKED_CREDENTIALS`，不重试；本轮开发提交已由 merge 父提交精确可达。

上述实际文件、逐对象账本、五目标结果和保存编辑分别由 `BASELINE_417_DESTINATIONS.json`、`FIVE_CASES_SAVED_RESULT.json`、`EDIT_ISOLATION.json` 及 `GUI_C241_NATIVE_VERSION_BRIDGE.json` 绑定。CT03 TEXT 未采用，原横划回归基线责任；没有因此退场旧对象。

## 已完成的代表 GUI，结论范围受限

LibreCAD 在 **c241191** 的实际副本操作两处、记录 14 张截图：删 LAUNDRY 整串 TEXT 后曲线保持；删 BEDROOM 独立曲线后文字保持；将 BEDROOM 直接改为 `BEDROOM-EDIT`，普通保存、退出并重开。最终保存与重开副本字节一致。最终版的共同实体属性桥接通过，只有 CT03 TEXT 移除、原横划恢复；没有在 cbac 重复 GUI。

`GUI_DIFF_DIAGNOSTIC_c241191.json` 以原 `1e-8` 公差确认两项完整删除；相对首次 LibreCAD 普通保存后的编辑基准文件，除改字对象外，其余 468 个实际实体及 47 个 BLOCK／123 个成员不变。改字同时使目标字体样式变为 `wqy-microhei`，普通保存还产生无 owner 的 PLOTSETTINGS，原严格保存审计 **FAIL** 保留。首次 GUI 保存中的 XDATA 丢失、47 个 INSERT 的 zscale 1→0、字体／图层／版本变化继续 **LIMITED**。诊断不修文件、不改变阈值、不豁免旧失败。

Windows 使用执行提交 cbac773，工作流 **2878 passed／8 skipped**，适用 CI 7／7 success；独立检查按实际打包的 72 份源码和 136 份资源绑定，未新增 OCR。实际 EXE 为 25401367 B，SHA256 `6db766f1be62aab4ca516f929812432fb7d0de44a1708de4dc4131d5e21959e8`。ROOM17、圆形标记、单行标签检查保留；原 strict-three-complete **FAIL（2 完整／1 待修）** 继续单列。历史见[单行标签记录](../native/SINGLE_LINE_LABELS_20261122.md)，本轮实现、边界和精确版本见[字线接触记录](../native/TEXT_CONTACT_20261124.md)。
