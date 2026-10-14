Image to CAD 新来源整页观察，2026-10-12

选定六页，五页经正常产品服务生成实际 DXF；USDA 扫描页到时停止。未扩大输入，未处理整个资料库。
版本 0.3.0-dev。活动分支 codex/source-support-lifecycle-instrumentation，HEAD 20b2247fdfdf90fbe10e6daacffe5e339d19cb13。已有未提交修改保留。

资料位于 D:/programs/CAD-Materials/incoming。实际 342 文件，2,068,451,954 字节（1.926 GiB）；121 PDF、7,406 可读页面。未发现打开错误或加密；未逐页验证全部内容流。
已有登记的“2,012 建筑图页”含估算分类，不能当作独立图纸实测数，更不是 2,000 个 PDF。5984 页登记为逐页核验，1422 页为结构估算。登记 106 来源族，其中住宅 103；独立项目数未确认。
主要来源包括 BFP 教学图、泉州／中山农村住宅图集、Jiri Lev、Jay Osborne、WikiHouse、USDA。旧 215 份资料及早期 Drawing-Sources/Residential 包未计入本批。
相同尺寸与页数的 PDF 组为 0；不能据此宣称无重复。15 个重复来源族登记行含版本及相关材料。res_004/005/006 登记名与实际 PDF 项目不符。本轮只补充现有 SOURCE-SUPPLEMENT，未修改或移动原始资料。

CAD：3 个独立 DXF，2 个 ZIP 内含 3 DXF 和 2 DWG，另有 4 个 PDF 内嵌 DXF。合计 10 DXF 内容项和 2 DWG，含同设计版本。8 个 DXF 可解析；2 个二进制 DXF 当前解析失败，不能断言原文件损坏。DWG 只查文件头，未验证可打开。
四个 BFP 内嵌 CAD 和两个 Farmhouse 包解释了“六份配套”来源。仅核实 1 个几何配对：res_005 p9 Tiny House 与作者内嵌 BFP-TP-04-clean.dxf。56/56 LINE 端点对应，比例 1.125 PDF pt/CAD inch，PDF 原点 (153,387.225)，无旋转，最大端点差 0.0000245 pt。未对全模型评分。其他配对待确认。

| 来源 | 原始 PDF | 页码（1 起） | 实际页面 | 选择理由 |
|---|---|---:|---|---|
| res_005 | [BFP_Modern_Cottage_Plan_Set.pdf](<D:/programs/CAD-Materials/incoming/res_005/BFP_Modern_Cottage_Plan_Set.pdf>) | 9 | BFP-TP-04 The Tiny House | Original embedded CAD; small native-vector plan with wall openings. Actual title differs from registration. |
| res_057 | [QZ_Rural_Housing_100-13.pdf](<D:/programs/CAD-Materials/incoming/res_057/QZ_Rural_Housing_100-13.pdf>) | 11 | Quanzhou 100-13 first-floor plan J-04 | Chinese vector paths including outlined glyphs, columns, door/window connections and signatures. |
| res_088 | [1-第一册60-1户型.pdf](<D:/programs/CAD-Materials/incoming/res_088/1-第一册60-1户型.pdf>) | 12 | Zhongshan 60-1 first-floor plan J-07 | Different Chinese publisher, dense instructions and stair/wall connections. |
| res_021 | [S03_Tasmanian_Homestead.pdf](<D:/programs/CAD-Materials/incoming/res_021/S03_Tasmanian_Homestead.pdf>) | 3 | Tasmanian Homestead floor plan | Native-vector paths and extractable text, timber wall/door relations. |
| res_025 | [S07_Southern Farmhouse - Drawing Set - Jay Osborne 2023-02-01.pdf](<D:/programs/CAD-Materials/incoming/res_025/S07_Southern Farmhouse - Drawing Set - Jay Osborne 2023-02-01.pdf>) | 5 | Southern Farmhouse first-floor plan A1.1 | Mixed vector/raster PDF, complex wall and porch connections. |
| res_008 | [USDA_Plan_7213_Blueprints.pdf](<D:/programs/CAD-Materials/incoming/res_008/USDA_Plan_7213_Blueprints.pdf>) | 4 | USDA 7213 floor/foundation/electrical plan | Historical raster drawing with OCR text layer; actual layout differs from first-page cover. |

六页已查结构：4 页原生矢量，1 页局部栅格混合，1 页栅格主图加 OCR 文字层。整体库的矢量／扫描分布未知。Tiny House 明示为教学图、非施工文件，仅作已配对的机制样本。

正常调用：load_image → ProductionProcessingService.process_page → FinalStructure → export_final_structure_dxf。OCR 启用，240 DPI，GUI 同类最长边 4800 px 限制；没有测试简化输出。
以下耗时分别是处理／本次总耗时（秒），总耗时包括导出、预览等。尺寸为原 PDF 纸面毫米，未施加建筑模型比例，不是模型空间 1:1 工程尺寸。

| 页面 | 处理 / 总秒 | DXF 字节 | 实体数量 | 结果 | 直接观察 |
|---|---:|---:|---|---|---|
| res_005 p9 | 55.746 / 57.489 | 677,343 | LINE 209, LWPOLYLINE 499, HATCH 3, TEXT 24 | [DXF](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/after-fix/res_005-p9/drawing.dxf) · [源图](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/res_005-p9/source-overview.jpg) · [最终 DXF](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/after-fix/res_005-p9/final-overview.png) | 同一窗框重复 LINE；墙体填充及文字形制失真。 |
| res_057 p11 | 245.456 / 251.536 | 1,942,595 | LINE 551, LWPOLYLINE 1311, HATCH 15, CIRCLE 10, TEXT 153, IMAGE 1 | [DXF](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/after-fix/res_057-p11/drawing.dxf) · [源图](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/res_057-p11/source-overview.jpg) · [最终 DXF](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/after-fix/res_057-p11/final-overview.png) | 车轮廓碎片、柱填充缺失、竖向标注压缩；剖切标记误识别为额外 7。 |
| res_088 p12 | 224.833 / 236.289 | 4,991,138 | LINE 418, LWPOLYLINE 4650, HATCH 5, CIRCLE 12, TEXT 181 | [DXF](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/after-fix/res_088-p12/drawing.dxf) · [源图](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/res_088-p12/source-overview.jpg) · [最终 DXF](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/after-fix/res_088-p12/final-overview.png) | 楼梯／墙柱区域多重轮廓；密集文字和尺寸需人工复核。 |
| res_021 p3 | 237.074 / 243.077 | 2,537,868 | LINE 440, LWPOLYLINE 2394, HATCH 6, TEXT 159, IMAGE 1 | [DXF](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/after-fix/res_021-p3/drawing.dxf) · [源图](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/res_021-p3/source-overview.jpg) · [最终 DXF](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/after-fix/res_021-p3/final-overview.png) | 门窗／木构边界碎片及多重轮廓；竖向标注压缩。 |
| res_025 p5 | 247.981 / 259.602 | 4,315,068 | LINE 430, LWPOLYLINE 4790, HATCH 3, CIRCLE 8, TEXT 360, IMAGE 5 | [DXF](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/after-fix/res_025-p5/drawing.dxf) · [源图](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/res_025-p5/source-overview.jpg) · [最终 DXF](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/after-fix/res_025-p5/final-overview.png) | 竖向尺寸成为细条；门窗与门廊边界多重轮廓。 |
| res_008 p4 | 0.000 / 301.279 | 0 | 无输出 | [停止日志](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/after-fix/res_008-p4/run.json) · [源图](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/res_008-p4/source-overview.jpg) | 301.279 秒停止，未生成 DXF；停在调和账本处理。 |

五份 DXF 均读取成功，7 个 IMAGE 相对依赖文件均存在，无 SCAN_UNDERLAY 实体。TEXT 和 LINE 可逐实体编辑；五份都在内存中编辑、写出、复读并保留实体数。实际输出文件未被手工修改。
五份结果可作参照和局部编辑；重复边界、碎片和不可读标注仍需修正，不能作为免复核的工程 CAD。未记录完整人工操作，不报告精确修改次数或准确率。未输出 DIMENSION；曲线多以多段线表示，ARC 恢复不足。图层不能直接等同墙体、轴线等工程语义。
final-preview.png 从实际保存 DXF 渲染，没有整页源图覆盖。默认 FinalStructure 预览走相同实体输出，但归一化纸面坐标后像素有差异；未证明逐像素一致，未定位全部栅格差异。示例泉州页面 41,964 像素不同，灰度差中位数 4，差值 >16 的 282 像素。
LibreCAD 文件对话框的元素索引和焦点状态不一致，重新读取后仍无法可靠输入；已退出对话框，旧打开文档未保存或关闭。本轮原生 CAD 打开、编辑和保存验证存在缺口。

允许范围内做了一次阻断修复：源笔画调和每条线的覆盖测量反复分配、扫描全页数组。首轮泉州和中山未在 300 秒截止内完成。修改 app/geometry/source_stroke_reconciliation.py 的 _measurement_claim_window、_claim_measurements、_claim_delta_measurements，改用局部窗口，保留全页厚度、全局端点舍入和边缘裁切。未改检测、合并、连接规则。
添加 tests/test_source_stroke_reconciliation_v1.py 的 6 个像素测量契约用例，6 通过；现有独立双线、空心双边界、部分恢复、斜线回滚 4 个用例通过，共 10。未运行全套测试。Tiny House 修复前后 735 个 DXF 实体属性及多段线顶点相同，总时约 93.216 → 57.489 秒。泉州和中山随后完成。
仍有共同耗时点：source_stroke_reconciliation.py:2774 的 _build_gap_extent_v2_record 逐对象 json.loads(context.route_ledger_json)。本轮不叠加第二项修复。USDA 页在 301.279 秒停止，无 DXF，不再重试。未观察到内存不足。

下一轮建议优先两项，不在本轮自动实施：

1. 同一物理窗框线被 Hough/LSD 双重接受。Tiny House 作者 CAD 及 PDF 证明源线相同；输出 LINE 9F/135 分别来自 HOUGH-000012 (721,965)→(824,965) 与 LSD-001004 (721.875,965.155)→(824.375,965.141)。两路同时进入 FinalStructure，首次问题在检测结果接受／源笔画调和，具体接受分支待进一步定位。可沿现有源支持和关系机制有界修复，减少编辑时重影、重复选择；真实平行墙面和窗格必须保留。handle 仅定位。
2. 竖向尺寸文字的方向／框尺度错误。Southern Farmhouse p5 源 PDF 的 14'-0" [4200] 文字矩阵 (0,5,-5,0,58.0768,420.3760)，为 90°；输出 TEXT 155E 同字符串，height 9.279439 mm、width 0.02489469、rotation 0°、insert (18.633725,150.062852) mm，形成细条。错误方向在 OCR 候选框／文字几何阶段已经存在，DXF 写入沿用该框。沿现有文字方向和框拟合修复，能恢复可读尺寸并保留 TEXT 编辑性；不改变已修订号数字逻辑、字体系统或全局缩放。

另有未关闭限制：泉州的 L 形剖切标记被额外识别为 TEXT“7”（confidence 0.99937、replacement_safe=false、reviewed=false）；原始“1”仍正确，不是旧修订号 1→7 再现。源覆盖拒绝与原生 TEXT 输出资格仍存在局部不一致，应保留候选的不确定性。不能据此删除全部非 replacement_safe 文字。
墙柱填充和门窗轮廓变化已见，但未做全模型拓扑判断。WQY 字形差异、源轮廓归属、原生 PDF 信息未被正常栅格入口利用的问题保留。

对照均为左源图、右实际 DXF，同一区域；未手工删实体：
- [Tiny House 窗框与墙体](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/res_005-p9/plan-comparison.png)（修复前结果；修复后 735 实体相同）
- [泉州车库、门窗和柱](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/after-fix/res_057-p11/garage-comparison.png)
- [Southern Farmhouse 竖向尺寸](D:/programs/Image-to-CAD/image-to-cad/instrumented-e03/local-artifacts/product-fullpage-20261012/after-fix/res_025-p5/vertical-dimension-comparison.png)

实际五份 DXF 总计 14,464,012 字节。保留的两个 trace.npz 共 156,539,017 字节，本轮目录总计约 177.8 MB（文件大小，不是磁盘释放量）。自动审批拒绝删除本轮生成缓存及未采用预览，返回 blocked by policy；未删除这些文件。
未改原始素材、模型、94/50 冻结数据和 P3B 状态；未提交或发布。已停止本轮工作。
