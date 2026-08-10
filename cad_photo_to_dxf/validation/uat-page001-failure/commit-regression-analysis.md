# page-001 提交回归分析

## 结论

第一个造成原生文字显著下降的提交是
`5a1b06585b6f068bb5f61e16fd32b96e4f54275b`
（`refactor: freeze current system baseline (phase 1)`）。
同一 PDF、同一第一页、同一 240 DPI、同一 OCR 运行时的边界复算显示：
父提交 `d9fbda7` 有 208 个候选、139 个可输出原生 TEXT；
`5a1b065` 仍是 208 个候选，但只剩 43 个可输出原生 TEXT。
下降 96 个（69.1%），不是 OCR 候选数下降，而是该提交首次在
`accepted_ocr_texts()` 中把 `replacement_safe=false` 设为硬拒绝条件。

`8fd1d6c`（phase 10）是第一个把这些被拒绝的候选显式路由到
`TEXT_FALLBACK_OUTLINE` / `RESIDUAL_GRAPHIC` 的提交。它造成 fallback
图层实体显性激增，但不是最早的原生 TEXT 下降点。

## 同 DPI 边界复算

| 提交 | OCR 候选 | approved | replacement_safe | 可输出原生 TEXT |
| --- | --- | --- | --- | --- |
| d9fbda7 | 208 | 141 | 43 | 139 |
| 5a1b065 | 208 | 208 | 43 | 43 |

当前 production 再经内容归属仲裁，6 个原本安全的候选因源像素不完整降级，
并有 2 个低置信候选优先进入 residual，最终得到 report 中的
37 TEXT、169 fallback、2 residual。

## 当前文件与最近较好产物

最近的重构前/边界处较好产物是 `d9fbda7` 提交中保存的
`validation/user-pdf-check/environment-page-001.dxf`。该文件可观察到
214 个候选支撑的原生 TEXT、0 个显式 fallback、
861 个 text-symbol。它没有候选级 report，因此“原始 OCR 总候选数”
只能报告为可观察下界 214；同 DPI 边界复算给出的原始总数是 208。

当前用户文件为 208 个候选、
37 个原生 TEXT、169
个 fallback 候选（对应 1393 个 DXF 实体）、
1406 个 text-symbol 实体、535 个 residual 实体。

## 阶段产物时间线（统一 120 DPI 回归页）

| 版本/阶段 | 原生 TEXT | fallback 实体 | text-symbol 实体 | residual 实体 |
| --- | --- | --- | --- | --- |
| phase4 | 11 | 0 | 2275 | 0 |
| phase5 | 11 | 0 | 2256 | 0 |
| phase7 | 11 | 0 | 2256 | 0 |
| phase8 | 10 | 0 | 2262 | 0 |
| phase9 | 10 | 0 | 2262 | 0 |
| phase10 | 10 | 1098 | 1164 | 14 |
| phase11 | 10 | 1098 | 1164 | 14 |
| phase12 | 10 | 1098 | 1164 | 14 |

phase 4 已只剩 11 个原生 TEXT，说明问题早于 phase 8/10；
phase 10 首次把原先混在一般轮廓/text-symbol 中的不安全候选显式着色和分层。

## 正确、错误与漏出样本

较好产物中可直接核对的正确样本：
无锡市建筑设计研究院, 有限责任公司, 附楼3, 49100, 8400, 5800, 7600, 11400, 6500, 3800, 2700, ±0.000, FK1, 一层消防平面图。

当前仍为原生 TEXT 的正确样本：
附楼3, 49100, 8400, 7600, 11400, 3800, 2700, ±0.000, FK1。

历史/当前 OCR 中可见的错误样本：
WUOI ARCHITECTURAL, DESIGH AND RESEARCH INSTTUTE Ca,LH., 国泉甲级工程设计证卡编号：100107-aj, NOWEB, 肥电间
；当前仍出现：
DESIGH AND RESEARCH INSTIUTE Co,LH., 国泉甲级工程资计证卡编号：100107-sj, NOWES, 肥电间, 驿电机房。

历史原生 TEXT 中、当前 OCR 候选已经没有的例子（“未识别”）：
WUOI ARCHITECTURAL, DESIGH AND RESEARCH INSTTUTE Ca,LH., 国泉甲级工程设计证卡编号：100107-aj, NOWEB, 3-B, 50, 90, 161, 重注机柜, 147, 应鸟控制被恒您, NH-BV-4x-G209C, 消火栓居泵钱, 165, 135。

当前已识别但没有成为原生 TEXT 的例子：
无锡市建筑设计研究院, 有限责任公司, WUDI ARCHITECTURAL, DESIGH AND RESEARCH INSTIUTE Co,LH., 国泉甲级工程资计证卡编号：100107-sj, 3, NOWES, 5800, 6500, 2500, 5900, 5400, 162, 监注机柜, 潮防控制室与安保监控宣。

## 字高、位置与单位

当前 DXF 使用毫米，源图 [3964, 2803]
映射到 [419.48098449707027, 296.54501291910805] mm。
X/Y 比例差只有
0.000256，
没有发现整页比例换算错误。

与历史像素坐标 DXF 的共同文字做页面归一化后，
位置偏差中位数为 0.490 mm，
归一化字高比（当前/历史）中位数为 0.992。
当前每行字高固定取候选框的 0.78，宽度填充 0.98；
实际宽度比例中位数为
0.603。
因此截图中的“过小、零散”主要来自：171/208 候选没有形成原生 TEXT、
字高再缩为 78%、大量行被横向压缩，以及 LFF 字体/查看器度量差异；
不是 1:1 页面换算出现数量级错误。

## 图层颜色回归

首个默认多色输出提交是
`c96545f84f537e075e75de23ea91886f9b6df2b7`
（2026-07-22，`fix: clean damaged scans and stabilize editable CAD export (#22)`）。
该提交引入 `TracePalette`，注释即为“用于区分几何”，并在生产 GUI
默认传入蓝/绿/品红调试色。`5a1b065` 把 curve 从 ACI 3 改成 ACI 6；
`8fd1d6c` 又加入 fallback=ACI 2、residual=ACI 3。

建议方案（本次未实现）：

- 正常模式（默认）：保留全部语义图层，实体颜色使用 BYLAYER；
  默认主色 ACI 7（暗色背景白、打印黑），fallback/residual 可选 ACI 8
  的克制灰色。颜色由导出配置统一控制，不在实体上写死。
- 诊断模式（显式开启）：保留当前分类色，
  straight=5、curve=6、text-symbol=6、fallback=2、residual=3、
  OCR_TEXT=6、signature=6，并在报告中标注“诊断配色”。

## 首个回归提交的具体代码语义

`git diff d9fbda7..5a1b065 -- app/ocr_outline_export.py` 的决定性变化是：
在置信度检查之前新增 `if not item.replacement_safe: continue`。
这将原先仅供 UI 诊断的安全标志变为原生 TEXT 的硬门槛。
phase 8 的归属仲裁再增加 6 个当前页降级；phase 10 只把既有降级显式分层。

本文件仅完成定位和设计，没有修改生产代码、阈值或回归基线。
