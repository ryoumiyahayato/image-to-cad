# page-001 真实用户验收失败只读审计

审计对象是用户提供的 `page-001.dxf`、相邻 `export.report.json` 和
`环保局主大楼.pdf`。生产代码、阈值和回归基线均未修改。
当前 240 DPI 生产流程复算得到的 structure_id 与 report 完全一致：
`cb64caae9892bdb64147f991f06a98b29e56eec18d593caff58d040d7697b441`。

## 核心结果

- OCR 候选：208
- 原生 TEXT：37
- fallback：169 个文字候选，
  1393 个 DXF LWPOLYLINE 实体
- TRACE_TEXT_SYMBOL：1406 个 DXF 实体
- RESIDUAL_GRAPHIC：report 中 2 个
  OCR 候选，DXF 中 535 个实体
- TRACE_STRAIGHT：633 个实体
- 降级码：`replacement_unsafe=169`，
  `confidence_below_contract=2`

完整 208 行候选流转在 `ocr-routing.csv`；候选与实体计数矩阵在
`layer-entity-counts.json`。

## fallback 根因

互斥主因计数为：

| 原因 | 数量 |
| --- | --- |
| bbox_or_orientation_unreliable | 3 |
| connected_component_crosses_bbox | 72 |
| connected_component_spans_characters | 42 |
| incomplete_character_coverage | 1 |
| ownership_pixels_incomplete | 6 |
| uncovered_nearby_ink | 45 |

表格单元格裁剪是关联条件而非硬拒绝条件：
106 个候选位置被裁剪，
但该步骤本身造成 `replacement_safe` 从 true 变 false 的数量为 0。
归属仲裁有 6 个文字候选因像素不完整被降级，均有结构线冲突证据。
`fallback-reasons.json` 内含 30 个具体例子。

## TRACE_TEXT_SYMBOL 与 fallback

两层 1px 光栅的原始重叠像素为 0。
按“TRACE_TEXT_SYMBOL 对象至少 60% 像素与 fallback 精确重合或落在
其 1px 邻域”这一严格同字形判据，重复对象数为 0；
仅 bbox 相交的 TRACE_TEXT_SYMBOL 对象为 24 个。
有 16 个已经路由到 fallback 的 OCR 候选框内同时出现
fallback 和 text-symbol 像素。像素唯一性与对象语义唯一性分别判定：

- 源像素在两层之间唯一：True
- OCR 候选对象只有一个最终语义：False
- 合同违反：True

这说明即使相同描边像素没有大面积重复，同一个 OCR 对象仍可能被拆成
fallback 与 text-symbol 两种最终表示。全部像素/bbox 证据见
`layer-overlap.json`。

## 原生文字显示

DXF 使用毫米，X/Y 换算各为
0.105822650 /
0.105795581 mm/px；
未发现数量级或纵横比错误。实际字高固定为候选框的 0.78，
宽度比例中位数为
0.603。
过小/零散感由原生文字只剩 37 行、字高和宽度再次收缩、LFF 字体度量及
查看器配色共同造成。逐实体插入点、基线、字高、宽度、旋转和 XDATA 在
`native-text-geometry.json`。

## 颜色来源

当前输出层 ACI 颜色：

| 图层 | ACI |
| --- | --- |
| SCAN_UNDERLAY | 8 |
| TRACE_STRAIGHT | 5 |
| TRACE_CURVE | 6 |
| TRACE_TEXT_SYMBOL | 6 |
| TEXT_FALLBACK_OUTLINE | 2 |
| RESIDUAL_GRAPHIC | 3 |
| OCR_TEXT | 6 |
| SIGNATURE_OVERLAY | 6 |

这些颜色由 `TracePalette` 明确用于“区分几何”，最早在 `c96545f`
进入默认生产导出；当前完整配色在 phase 10 后形成。正常/诊断模式设计和
首个文字回归提交的证据见 `commit-regression-analysis.md`。

## 渲染图

- `layer-trace-straight.png`
- `layer-ocr-text.png`
- `layer-text-fallback-outline.png`
- `layer-trace-text-symbol.png`
- `layer-residual-graphic.png`
- `composite-all-layers.png`

单层图为白底黑色 1px 实体光栅；合成图使用当前 ACI 分类色。

## 后续四个独立修复任务（本次不实施）

### A. 默认图层颜色和正常显示模式

将生产默认改为正常模式：保留语义图层，实体 BYLAYER，统一 ACI 7 或
克制可配置色；当前分类色只在显式诊断模式启用。验收应覆盖暗色 CAD、
白底打印和 DWG 转换。

### B. 原生 TEXT 的尺寸、位置和字体

单独校准 0.78 字高、0.98 宽度填充、基线 lift、最小宽度比例和 LFF/替代
字体度量。用源 bbox/quad 对齐误差、归一化字高和 LibreCAD/AutoCAD
截图做验收，不与 OCR 路由阈值混改。

### C. OCR 候选进入 fallback/text-symbol 的错误路由

为每个安全条件保留结构化原因码；区分“风险提示”和“硬拒绝”。
修复 fallback 候选内部仍出现 text-symbol 的对象级语义分裂，并增加
候选级与像素级唯一性测试。

### D. 结构线漏检和自动补线召回

独立建立结构线真值 ROI、断线长度/方向/线宽证据和召回指标；只在文字、
Logo、签名保护合同通过后评估补线，避免以提高召回重新引入全页交叉乱线。

审计到此停止；没有宣称问题已解决。
