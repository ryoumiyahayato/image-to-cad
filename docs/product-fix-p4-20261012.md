Image to CAD P4 同源检测观测归并，2026-10-12

本轮确认的 Tiny House 同轨 Hough/LSD 重复已修复。其他双边缘和碎片问题保留。
版本 0.3.0-dev；分支 codex/source-support-lifecycle-instrumentation；HEAD 20b2247fdfdf90fbe10e6daacffe5e339d19cb13。未提交、发布或清理原有缓存。已有未提交工作保留。

源为 D:/programs/CAD-Materials/incoming/res_005/BFP_Modern_Cottage_Plan_Set.pdf 物理 p9，实际项目 BFP-TP-04 The Tiny House，240 DPI。作者原 CAD 从 PDF 内嵌附件读取；原文件未改。
作者 LINE B2 为 (36,102)→(84,102) inch；映射到源像素 (645,966.75)→(825,966.75)。CAD inch→像素比例 3.75，源原点 (510,1349.25)，Y 反向。该窗框上沿在源图为一条笔画；两个检测器分别观察其局部范围。

真实根因：HOUGH-000012 和 LSD-001004 的中心轨迹均舍入到白色 y=965，实际强墨迹在 y=966（灰度 39），邻接抗锯齿在 y=967。调和的 _source_support_intervals 只检查中心轨迹，因无直接支持进入“未确定关系，保留已接受对象”分支；跨检测器判断已有机制，但此处未被执行。不是只处理同检测器，也不是 DXF 导出复制。

改动沿现有流程：
- app/geometry/source_stroke_reconciliation.py：consolidate_detector_aliases / _source_bound_raster_alias，复用局部 production claim 和现有空间索引。方向／整数轨迹只作检索条件；还须整条候选覆盖包含于已有代表、端点在原有源帽范围、每个内部轴向站位绑定同一连续完整源带，无空白或第二条弱／强源带，无保护区域。独立共享的精确 CAD 端点阻止归并。保留已有坐标与全部父来源，不延长或补线。
- app/geometry/optimized_trace.py：几何准备及 stroke_presentation 完成后、内容归属准入前调用。早期前置调用试产曾改变后续代表选择，已撤回；交付只采用 final/after.dxf。
- app/core/processing.py：更新算法缓存标识，避免旧缓存复用旧重复结果；软件版本号未改。
- tests/test_source_stroke_reconciliation_v1.py：9 个新增用例，含真实源裁片、输入反序、断口、第二源带、弱源带、保护区、不同端点及独立接点。新增源裁片仅 1882 字节，来自 p9 的 (700,830)-(850,995)。

正常产品路径为 load_image → ProductionProcessingService.process_page → FinalStructure → export_final_structure_dxf；OCR 启用，240 DPI。作者 CAD 不参与运行时规则。

| 对象 | 修复前 | 修复后 |
|---|---|---|
| 指定窗框 FinalStructure | 两条独立来源 | 一条，含 HOUGH-000012 和 LSD-001004 来源 |
| 实际 DXF | 9F 与 135 两条 LINE | 9F 对应的原几何一条 LINE；135 原几何不再输出（handle 仅定位） |
| 全页 LINE | 209 | 196，净减少 13 |
| 全页其他对象 | 24 TEXT、499 LWPOLYLINE、3 HATCH | 数量、属性、顶点／路径相同 |
| LINE 源覆盖 | 原覆盖像素并集 | 并集完全相同，丢失 0 像素；无新增 LINE 几何 |

保留 LINE 的源坐标 (721,965)→(824,965) 未变；实际毫米坐标 (76.3432565,177.3577734)→(87.2494360,177.3577734)。另一个被替代观测原毫米坐标 (76.4358996,177.3413452)→(87.2891559,177.3428510)。归并减少重复选择，不重新设计窗框。

最终处理 52.788 秒、导出 1.027 秒、总计 54.240 秒；上一轮基线处理 55.746 秒、总计 57.489 秒。单次对照未见明显新增负担，不作为稳定性能比率。新判断只扫描候选局部窗口和索引邻居，不重新扫描整页像素，不做全部候选配对。
DXF 673,900 字节。使用与旧结果相同的纸面毫米标定，未施加建筑模型 1:1 比例。

22 个直接相关 pytest 用例通过（9 新增、6 原局部窗口契约、7 既有源调和保护）；未运行全量测试。W01 已关闭缺陷的 3 条保存接点线另行通过当前归并入口回放，几何及共享端点未变，未重新转换 W01 整页。
真实窗格横线及相邻竖边保留，局部交叉方向不归并，不同端点观测保留。实际被移除的 13 条观测没有独立共享的精确 CAD 端点；新 LINE 坐标集合为旧集合子集，不增加端点移动或连接。未发现本轮新增源笔画丢失；全模型工程拓扑正确性未作断言。
实际 DXF 的 LINE/TEXT 在内存中编辑、写出、复读成功，实体总数保留；交付文件未被手工编辑。最终预览从该保存 DXF 渲染，无整页源图底图。未进行 LibreCAD 原生打开验收。
本页无 IMAGE、CIRCLE、MTEXT 或签名实例，不声称完成这些对象的新增整页回归。TEXT 内容、方向和样式未变；所有有效 LWPOLYLINE/HATCH（含图形轮廓）保持；保护区域用例通过。未改 OCR、字体、P2B 或原始素材。

交付：
- [旧实际 DXF](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/after-fix/res_005-p9/drawing.dxf)
- [新实际 DXF](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fix-p4-20261012/final/after.dxf)
- [作者原始内嵌 CAD 副本](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fix-p4-20261012/final/author-BFP-TP-04-clean.dxf)
- [源图／原 CAD／旧 DXF／新 DXF 对照](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fix-p4-20261012/final/window-comparison.png)
- [新 DXF 全页预览](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fix-p4-20261012/final/final-preview.png)

CAD 对照是原模型几何的同尺度局部显示，ARC 仅在绘制参考图时离散显示，原始 CAD 仍保留 ARC。原始 PDF 的线宽和模型绘图线宽不作为一一对应证据。

限制：当前归并只处理有完整源带依据的近轴向同整数轨迹整条观测。不同整数轨迹、不同长度超出端帽、独立共享节点和证据不足的关系保留。窗框／门扇仍有两侧边缘重复及曲线碎片；例如 y≈967.65 的另一侧观测未强行合并。下一项几何问题应定位这些边缘与真实边界的源带及节点关系，而非全局收紧距离阈值。
未经批准的此前约 156 MB 缓存未删除。早期试产文件也未自动清理。冻结数据、模型和 P3B 状态未动。本轮停止。
