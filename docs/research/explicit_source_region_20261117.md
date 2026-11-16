# 显式完整原扫分量的 source-region 入口

本文登记一个独立、默认关闭的实验入口：调用方通过内容绑定的 selection manifest 选择一个完整原扫黑色连通分量，正常 raster 管线验证来源和当前责任后，把所选分量、其父源残余及完整父源备份输出为原生 HATCH。它沿用现有 `FinalStructure`、缓存、共享 DXF writer 和实际 DXF 预览，不另建脱离正常输出的示意图。

**阶段状态：代码切片与部分专项验证已完成；exporter 验证、完整 G1 和真实保存文件 G2 正在进行，最终结果在本文末尾另行登记。** 本文的入口和字段说明不是完整产品或本地 CAD 验收结论。

## 1. 适用范围与默认行为

第一版仅接受 aligned raster 输入、已验证的原始 bitonal TIFF、一个显式 selection、一个完整 native 8-connected 且 4-connected 的成员 M，以及非空的父源残余 R。它不搜索整页候选，不判断历史笔画身份，不识别整工程对象，也不增加原 24 个自动恢复对象的采用数量。

未提供 `--experimental-native-source-region-manifest` 时，配置字段保持 `None`，不读取 manifest、不计算本功能的整图来源 hash、不运行新来源适配器，不增加新 config/cache payload 字段或新 CLI report 字段。默认 geometry、OCR、已有 r13/frame/open-stroke、Logo 和签名继续走既有路径。

本入口有独立版本：

| 范围 | 版本或标记 |
| --- | --- |
| 显式选择 manifest | `explicit-native-source-region-selection-v1` |
| source-region 输出合同 | `explicit-native-source-region-v1`，并绑定合同 SHA256 |
| enclosure record | `native_source_region_partition=True`、`kind=explicit_native_source_region` |
| 来源声明 | `EXPLICIT_COMPLETE_NATIVE_SOURCE_COMPONENT`、`automatic_selection=False` |
| 语义限制 | `historical_identity=NOT_PROVEN`、`electrical_semantics=NOT_INFERRED`、`full_object_movable=False` |

它不复用现有 compound LINE 合同，也不改写旧独立 HATCH study 合同。第一版拒绝与 `--experimental-compound-strokes` 同时开启，拒绝 PDF/native-PDF 路径。显式选择违反条件时抛出错误，不静默回退为“已成功采用”。

## 2. CLI 用法

在 `cad_photo_to_dxf` 目录，参数形态如下。这里的文件名是通用占位；`100` 仅演示参数形式，必须换成 working source 的真实 DPI。`original.tiff` 的内嵌 DPI、尺寸、像素和配准必须与实际输入吻合。

```bash
python main.py --headless \
  --input source.png \
  --source-dpi 100 \
  --original-scan original.tiff \
  --experimental-native-source-region-manifest selection.json \
  --ocr \
  --output output/selected-region.dxf \
  --preview output/selected-region.png \
  --report output/selected-region.json
```

这不是已执行的样例命令。研究环境中的实际执行仍使用项目既有离线 runtime 包装、关闭遥测并保存精确命令与结果。`--ocr` 按原任务需求使用；新入口不会把已有文字责任改授给 HATCH。

如果使用 `--crop`，其四个 half-open full-working 坐标必须与 manifest 的 `crop_work_px` 完全相同。未使用 `--crop` 时，manifest 仍写完整输入范围。DPI 及 source registration 来自真实数据，不能靠输出 extent 或想要的工程比例反推。

当前没有交互式选择器或自动生成 selection 的 CLI。manifest 必须由实际来源、当前 prepared window 和明确选择生成并核对。下面只说明 schema，不给出含伪 hash 或省略字段、却看似可以运行的 JSON。

## 3. Manifest 字段及坐标约定

所有字段均必需；未知或重复 JSON 字段、非有限数值、bool 冒充整数、非规范 runs、越界数据以及超预算输入都会被拒绝。parser 返回新的规范化数据树；配置持有 canonical JSON 字符串，调用方修改返回 payload 不会改变已保存的配置。

| 字段 | 内容及身份意义 |
| --- | --- |
| `version` | 必须为 manifest 版本 `explicit-native-source-region-selection-v1`。 |
| `input.pixels_sha256` | 完整加载后、crop/预处理之前的二维 working uint8 像素，按 C 连续行顺序计算原始字节 SHA256；不是 PNG/TIFF 文件压缩字节的 hash。 |
| `input.shape_yx` | 完整 working image 的 `[height,width]`。 |
| `input.dtype` | 固定 `uint8`；开启功能的服务入口拒绝三通道等其他形状。 |
| `input.dpi` | 完整 working image 的真实 DPI，正且有限。 |
| `original.pixels_sha256` | 完整 registered original 的二维 uint8 原始像素字节 SHA256。验证覆盖整幅原扫，不仅选中 tile。 |
| `original.shape_yx` | 原扫 `[height,width]`，必须对应 working shape 乘整数采样比。 |
| `original.dtype` | 固定 `uint8`，实际源必须为仅 0/255 的 bitonal 像素。 |
| `original.dpi` | 原扫实际 DPI，与 working DPI 和整数采样比满足既有注册契约。 |
| `crop_work_px` | `[left,top,right,bottom]`，完整 working image 内的 half-open 裁剪范围；不是 tile-local 坐标。 |
| `native_scale` | 每个 working 轴方向上的整数 native/working 比，第一版范围 2–16。 |
| `prepared_window.origin_work_px` | `[ox,oy]`，bounded window 左上角在 trace crop 内的 working 坐标。crop origin 不在这里重复相加。 |
| `prepared_window.shape_yx` | bounded prepared window 的 `[height,width]`。 |
| `prepared_window.pixels_sha256` | 当前真实 prepared gray window 的二维 uint8 原始像素字节 SHA256。预处理或窗口内容改变时，旧选择不能静默复用。 |
| `prepared_window.dtype` | 固定 `uint8`。 |
| `selection.id` | 显式选择的短标识；其作用是审计与 entity binding，不代替来源证明。 |
| `selection.working_parent_runs_y_x0_x1` | 完整 working parent W 的规范 runs，坐标相对 prepared window；前景定义为实际 `prepared.gray < 254`。 |
| `selection.native_member_runs_y_x0_x1` | 所选 native 成员 M 的规范 runs，坐标相对同一 window 的 native grid；其尺寸为 prepared window shape 乘 `native_scale`。 |

每条 run 为 `[y,x0,x1]`，表示本行 `[x0,x1)` 的全部源格。runs 按行和起点排序、互不重叠；同行相邻区间必须合并，不能通过重复或拆分同一 run 改变来源计数。计数从实际集合重算。连通分量 label 序号、文件名、bbox 或某个样例坐标都不是授权身份。

当前 manifest 字节上限为 1 MiB，working window 最多 100,000 像素，native window 最多 1,000,000 像素，working parent 最多 8,192 像素，runs 另有上限。writer 还限制合计 runs、边界边、顶点、环和 metadata 大小。触发预算时拒绝该选择，不放宽几何或来源条件。

## 4. Whole-parent 来源与责任守卫

设完整原扫黑格集合为 B，working parent 为 W，采样比为 r。先从实际数据重建父源：

`P = repeat(W,r,r) ∩ B`，`R = P \ M`。

M 必须非空且是 P 的 proper subset，R 必须非空，`M ∩ R` 为空且 `M ∪ R = P`。所有 native source 都必须是原扫真实黑格，不能从拟合线或人工预计的形状生成。

管线挂点在已有 source ownership、文字/Logo/签名、frame/open-stroke 处理之后，最终 residual contour tracing 之前。清除整个 W 之前逐项检查：

1. 完整 input/native hash、dtype、shape、DPI、ratio、crop 与 manifest 相符，prepared window hash 与本次真实处理相符。
2. W 是当前 `prepared.gray < 254` 中的完整内部 8-connected component；W 的完整邻域不得遗漏相连源，不接受碰到 window/crop 未知边界的截断分量。
3. W 的全部源在 `prepared.binary` 中仍有效，在当前 `contour_binary` 中仍未被认领。仅检查 M 不足以允许移交整个 parent。
4. W 与 `ownership.line/text/logo/signature`、可编辑文字源、隐藏文字源备份、未确认文字轮廓，以及实际 Logo/签名源 masks 均无交叠。
5. native window 与 prepared source 满足原扫注册关系。M 是完整原扫黑图中的一个完整 8-connected component，同时也是 4-connected；corner-only 连接不在第一版表达范围内。
6. 用完整原扫坐标读取 M 的完整一格 8-neighbor halo，证明没有遗漏相连 native 黑格。仅在 P 内或裁下的 tile 内计算 CC 不能代替此证明。
7. writer 的 exact-cell ledger、边界和坐标 preflight 全部通过，才创建复制后的 residual mask 并清除 W。任一失败不改变传入源图或 mask。

此选择声明只能指明“要验证哪个完整原扫分量”，不能绕过现有文字或其他 source ownership。已经由 r13、文字或其他成员领取的 parent 不会因为显式选择而被抢回。

## 5. 实际输出：M、R、P 三个角色

每个接受的 selection 通过 `engineering_enclosures` 占用一个明确的 final contour slot；该 slot 的旧普通轮廓不再重复输出，新 record 的 native cell union 是实际来源几何。

| 角色 | 实体与默认状态 | 表达范围 |
| --- | --- | --- |
| M / member | 一个可见、独立原生 HATCH | 用户显式选择的完整 native source component，包含其真实孔洞。 |
| R / residual | 一个可见、保持原位的原生 HATCH | `P−M` 的全部源；可含多个外环与孔洞。 |
| P / backup | 一个默认 off、frozen、locked 的原生 HATCH | 完整 parent native source 的恢复依据。 |

HATCH 使用封闭直边 polyline loops，保留 exact source-cell 并集、白隙和孔洞；只消除严格共线的冗余顶点，不进行拟合、平滑或桥接。成员、残余和备份使用独立角色与来源绑定；文档内 metadata 记录规范化 manifest、source ledger、角色和变换身份。

非目标源 F 不在此处重画为背景 HATCH。真实文字继续由原文字责任输出为 TEXT/MTEXT，Logo、签名、其他线条与轮廓继续由既有管线输出。实际保存文件的非目标比较必须逐实体、逐文字、逐来源验证，不能仅凭总数或整层排除宣称保持。

完整 P backup 不等于已交付一个 GUI“恢复”动作。目标 CAD 的可选性、MOVE、Undo、保存重开和 backup 的人工操作仍需分项验证；本入口不借隐藏备份掩盖可见残余缺失。

## 6. 正式坐标与正常预览

native source-cell 边界坐标记为 `(u,v)`，window 的 working-local origin 为 `(ox,oy)`，采样比为 r。writer 使用：

```text
x_work_edge = ox + u / r
y_work_edge = oy + v / r
(x_cad, y_cad) = frame.edge(x_work_edge, y_work_edge)
```

`frame.edge` 由现有 `raster_to_cad` 提供，处理正式纸面比例、crop 在整图中的位置、完整页面高度、Y 翻转及已有 export frame。crop 不在 record 和 frame 中重复相加；旧独立研究的 tile-local 毫米原点不进入本合同。

这里明确使用格边 `edge`。有 paper calibration 时现有 `frame.center` 会加半像素，无 calibration 的 unitless preview 则采用既有不同约定；把固定 `−0.5` 移位后总调用 center 会造成两条路径不一致。新 writer 直接使用 edge，避免把中心坐标约定误用于 source-cell 边界。

GUI/预览仍从同一个 `FinalStructure` 导出实际 DXF，再读取 emitted entities 绘制，不能拿原图覆盖结果代替输出验证。共享 writer 能供现有单页/文档导出调用，不因此提前宣称多页混合输入或目标 CAD 已验收。

## 7. 配置、缓存与 provenance

`ProductionProcessingConfig.experimental_native_source_region_manifest` 保存经过验证的 canonical JSON 字符串。开启时才新增以下 processing payload 键：

- `experimental_native_source_region_manifest`：规范化数据对象。
- `native_source_region_selection_sha256`：canonical JSON 的 SHA256。
- `native_source_region_version`：selection schema/version。

既有 processing cache key 包含 config payload，因此不同 selection/source binding 不会共用同一个开启态处理身份；JSON 排版差异不会改变规范化身份。关闭态不添加这些键。

接受的 record 在 `FinalStructure.provenance["engineering_enclosures"]` 中保存完整源账本，并进入已有 structure fingerprint；缓存保存和恢复同一 provenance。`explicit_source_region_recovery` 保存接受结果与计数，CLI 仅在显式开启时把此 summary 和 `source_structure_id` 加入报告。

writer 在任何 source-region 实体创建或普通 contour 排除前预检 record、唯一有效的 `contour_index`、完整 partition 和全部坐标。遇已有不支持改写的 frozen draftsman/contour binding 时拒绝，不把新 HATCH 冒充旧 LWPOLYLINE source ref。未知或矛盾的 source-region marker 不能落入通用 enclosure 分支。

## 8. 本轮已完成的验证

2026-11-17（Asia/Shanghai）更新。以下是已执行的自动化事实；目标 CAD 交互独立保留。

| 检查 | 实际结果 |
| --- | --- |
| 新增专项 | 79 项通过：来源选择与守卫 38、精确 HATCH/正式 frame/缓存及失败清理 25、配置/CLI/shared writer 16。 |
| 完整应用单测 | Python 3.11.18 / pytest 8.4.2：1,866 PASS / 26 SKIP / 0 FAIL / 0 ERROR。18 个跳过缺 TrueType 测试字体，8 个缺 P2C 候选资源；不是测试失败。 |
| 制图规则 | 88 PASS / 0 SKIP。 |
| 默认行为保留 | 代表行为 EXACT；另对新关闭态实际整页与此前正常页进行不改写结构 ID 的比较，36,558 个实体、原始 XDATA、表/块、图片和字体均一致。 |
| 静态与卫生 | 规定 Ruff、四文件 mypy、compileall 通过；仓库卫生 0 findings。 |
| 实际完整页 | 同输入、同模型和环境，关闭/开启各一次且串行；均退出 0，分别约 290.525 / 316.949 秒。539 项绑定运行前后不变。 |
| 保存 DXF 差异 | 36,558 → 36,554 个实体；仅退出精确识别的 7 个旧目标 LWPOLYLINE，新增 M/R/隐藏 P 三个 HATCH。无非目标新增或删除。 |
| 原生文字与旧恢复 | 199 个 TEXT、48 个旧 r13 来源成员完整保持；非目标相对绘制顺序、实际图片和使用字体保持。 |
| 完整 source ledger | P=1,360 格，M=68 格，R=1,292 格，互斥并集精确相等；残余 5 个孔、孤立格、全部 native 白格与白缝保持。未把研究 F context 重画进正式图纸。 |
| 实际文件读回 | 两份 DXF 均 0 audit errors / 0 fixes，read-save-read 语义保持。正式 DXF 与最终预览使用同一实际 FinalStructure。 |
| LibreCAD 点选/MOVE/GUI Undo/另存后冷启动重开 | **NOT_RUN**。 |
| DWG、陌生来源泛化、真人净省时 | **NOT_RUN**。 |

整个 working parent 的当前/已认领/九项保护 mask 在本次运行中重新检查，均无冲突；实际只移交 454 个目标工作像素，全部非目标可见 mask 保持，原输入 mask 未修改。实例是此前已经暴露的显式选择，不是盲测，也不增加原 24 个相接父件的自动恢复计数。

### 源码与审计证据

源码/检查配置 503 项清单 SHA-256 为 `919e627d2673c8220f812750198fff4013fc0d67163c5524e1a4e447a5e00199`；G1 执行冻结为 `cc590e2b3efba2270cff39c6f01cc8cd0ea8c27e63cebd3966fd4209b17b23d0`。实际整页运行冻结为 `4152be635ee7435869023f421c905b6b9b796e3296704c3fe85c1a2b3c1eec14`。生产方法和原始输入没有因审计结果改动或重跑。

G2 独立报告 SHA-256 为 `c2238ea3d36accf7e1a539149308c2d39db6a6165c3772fbb8860a45554e545c`。每条保存边首先严格匹配正式二进制浮点 frame 的唯一格线，再回到 native 整数格检验完整边界、孔与全格奇偶；没有坐标 epsilon 或输出舍入。非目标只允许经实际观察证明的 `P16_LINE_SOURCE.source.structure_id` 更新，其他来源字段均比较；没有整层、类型或 bbox 豁免。

保留两类修正历史。冻结前的故障注入曾暴露 hard-owned 字典/XRECORD 清理顺序问题，修复后创建前/后异常均清理新增资源。首次真实只读审计误把内部 review-layout 的临时文字 display 状态也当成最终结构，原 FAIL 保留。审计器 v2 按冻结调用链证明临时状态只改变 display_quad；完整非 display 成员、mask、来源 ID 相同，正式文件与最终预览完整 ID 严格相同。13 个既有来源/几何/非目标检查函数 AST 未变，原 observer 的过强聚合布尔也未改写。该纠正没有改生产方法或任何实际 DXF。

本节记录本地云端环境的已执行结果；后续 PR 的 Linux/Windows/FreeCAD 工作流须按实际 head 与日志另行登记，不能以旧 PR38 结果替代。私有输入、选择数据和实际文件未进入公开仓库。

## 9. 下一步

把完整解压后的候选整页交给目标 CAD，定位唯一青色 M，核对单个 HATCH 点选、精确移动、其他内容不随动、真正 GUI Undo、另存后退出并冷启动重开。隐藏 P 备份不等于 Undo 历史。本轮没有新增正常入口的恢复按钮，R 与 P 保持说明中的默认状态。

后续若修改来源、恢复算法或 HATCH 合同，应同步提升配置采用的选择/feature 版本，使缓存失效；不能只修改内部实现而继续复用旧处理身份。
