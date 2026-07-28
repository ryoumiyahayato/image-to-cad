# 阶段三：26 阶段可观测性与调试包规范

## 范围

本阶段只增加旁路观察接口、调试包生成器和像素查询工具，不修改结构线检测参数、连接规则、对象分类阈值或 OCR 判定。`observation_sink=None` 是生产默认值；旁路关闭时不生成诊断图，算法输出必须与阶段一基线保持相同 `structure_id`。

旧的全页 `2x1/1x2 MORPH_CLOSE` 不会为了调试重新执行。阶段 05 以 `status=not_executed` 明确记录它已离开生产路径，并保留历史引入 commit；这比伪造一张“旧结果图”更能说明当前像素没有经过闭运算。

## 一键生成

从 `cad_photo_to_dxf` 目录运行：

```powershell
.\.venv\Scripts\python.exe scripts\capture_debug_bundle.py `
  tests\real_regression\assets\test.jpg `
  --output output\debug\test-page
```

命令默认启用 OCR，以便 14–16 阶段具有实际产物。PDF 可指定页码和 DPI：

```powershell
.\.venv\Scripts\python.exe scripts\capture_debug_bundle.py `
  C:\documents\drawing.pdf `
  --page-index 2 `
  --dpi 300 `
  --output output\debug\drawing-page-003
```

只有明确需要验证 OCR 关闭路径时才使用 `--disable-ocr`；此时 OCR 三个阶段仍存在于 manifest，但状态为 `not_executed`。

输出目录必须为空。输入缺失、阶段缺失、`FinalStructure` 缺失、预览/导出结构不一致、DXF 读取失败或 DXF 审计出错时，命令返回非零。

## 目录与命名

```text
debug-bundle/
├── manifest.json
├── final/
│   └── final-structure.dxf
└── artifacts/
    ├── 01-original-page/
    │   ├── artifact-001.png
    │   ├── artifact-001.png.metadata.json
    │   ├── data.json
    │   └── metadata.json
    ├── ...
    └── 26-actual-dxf-render/
        ├── artifact-001.svg
        ├── artifact-001.svg.metadata.json
        ├── data.json
        └── metadata.json
```

命名规则：

- 阶段目录：`NN-英文短名`，`NN` 固定为两位顺序号；
- 图像或渲染文件：`artifact-NNN.<ext>`，同一阶段可有多个产物；
- 每个产物紧邻一份 `<文件名>.metadata.json`；
- 每个阶段有 `data.json` 保存向量、bbox、ROI、连接决定和拒绝原因，有 `metadata.json` 汇总该阶段；
- `manifest.json` 是唯一入口，引用全部 26 个阶段、像素归属图和最终 DXF。

PNG mask 保持源页面像素坐标，不缩放。阶段 26 是从保存后的实际 DXF 重新读取并通过 `ezdxf` drawing backend 生成的 SVG，不是 GUI 预览截图。

## 固定阶段表

| 序号 | stage key | 内容 |
| ---: | --- | --- |
| 01 | `original_page` | 原始页面 |
| 02 | `original_gray` | 原始灰度图 |
| 03 | `normalized_background` | 归一化背景图 |
| 04 | `binary_foreground` | 二值前景图 |
| 05 | `legacy_closing` | 旧闭运算状态；当前生产路径明确为未执行 |
| 06 | `structural_roi` | ROI mask、来源线、交点、bbox、类型和置信度 |
| 07 | `raw_line_candidates` | 检测器原始直线候选及向量 |
| 08 | `line_candidates_text_filtered` | 轴向、源支持、文字和扫描伪影过滤后的候选 |
| 09 | `candidate_endpoints` | 候选端点像素与坐标 |
| 10 | `approved_connections` | 实际选中的连接、ROI、连通域前后数量 |
| 11 | `rejected_connections` | 被拒连接、拒绝原因、保护区/连通域证据 |
| 12 | `endpoint_snap` | 吸附前后；当前生产结构重建的 `snap_distance=0`，两图相同并明确标为禁用 |
| 13 | `intersection_extension` | 交点延伸前后直线 |
| 14 | `ocr_raw_tiles` | OCR 原始 tile 或 overview 页 |
| 15 | `ocr_rule_removed_tiles` | OCR 去表格线视图；小页 overview 下只作诊断，不改变 OCR 输入 |
| 16 | `ocr_text_boxes` | OCR 文本框、内容、置信度和状态 |
| 17 | `text_candidate_mask` | 文字候选与最终归属 mask |
| 18 | `logo_candidate_mask` | Logo 候选与最终归属 mask |
| 19 | `signature_candidate_mask` | 签名候选与最终归属 mask |
| 20 | `structural_line_candidate_mask` | 结构线候选与最终归属 mask |
| 21 | `conflict_mask` | 多个候选重叠的冲突像素 |
| 22 | `residual_mask` | residual mask 和逐像素最终归属编码图 |
| 23 | `final_structural_layer` | 最终导出的结构 LINE 层 |
| 24 | `final_text_layer` | 最终文字层及文字对象数据 |
| 25 | `final_outline_layer` | 最终导出的轮廓源 |
| 26 | `actual_dxf_render` | 从实际 DXF 读取后渲染的 SVG |

## 元数据合同

每个阶段元数据和每个产物 sidecar 至少包含：

- `input_file_sha256`；
- `page_index`；
- `dpi`；
- `algorithm_version`；
- `application_source_digest`；
- `git_commit` 和 `git_worktree_dirty`；
- `configuration_summary` 与 `configuration_digest`；
- `structure_id`；
- `stage_id`、`stage_key`、`stage_name`；
- `generated_at`；
- `upstream_stage_ids`。

提交未落地时，`git_commit` 只能指向当前父提交，因此 `git_worktree_dirty=true`；此时 `application_source_digest` 才是本次实际运行代码的精确标识。提交后只要应用源码未变，源码摘要保持一致。

连接和对象归属数据不只保存在图上：`data.json` 保存候选坐标、ROI 置信度、批准/拒绝结果、拒绝原因、连通域数量、文字框和最终对象统计。PNG 负责像素坐标证据，JSON 负责决策证据。

## 任意像素追踪

调试包中的阶段 22 额外保存无损的逐像素归属编码：

| 编码 | 最终归属 |
| ---: | --- |
| 0 | background |
| 1 | structural_line |
| 2 | text |
| 3 | logo_or_graphic |
| 4 | signature |
| 5 | residual |

查询任意源坐标：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_debug_pixel.py `
  output\debug\test-page `
  100 100 `
  --output output\debug\test-page\pixel-100-100.json
```

查询结果包含输入哈希、`structure_id`、最终归属，以及该坐标在全部 26 阶段各产物中的值。OCR tile 会根据其 `region` 自动把页面坐标换算为 tile 局部坐标。

## GUI 与 DXF 的单一数据源

GUI 在 `app/gui_exact_release.py:210-215` 将追踪结果转换为一个 `FinalStructure`，并调用 `render_final_structure_preview(structure)`；缓存恢复在 `app/gui_exact_release.py:234-242` 读取同一个结构。单页 DXF 入口 `app/trace_single_export.py:242-276` 直接消费 `FinalStructure` 并返回同一 `structure_id`。多页入口在 `app/trace_document_export.py:123-135` 优先从 `DocumentPage.final_structure` 取得轮廓、直线、文字和签名。

因此 GUI 预览与 DXF 的合同是：

```text
trace_image_optimized
        │
        ▼
immutable FinalStructure (one structure_id)
        ├──► render_final_structure_preview ──► GUI
        ├──► trace cache
        └──► export_final_structure_dxf / document export ──► DXF
```

调试包 manifest 也保存这份合同、`structure_id`、DXF 实体数和审计结果。

## 阶段三保存样本

版本库样本位于：

`cad_photo_to_dxf/validation/observability/phase3-sample/`

它使用真实回归页 `test.jpg`、OCR 开启配置，保存 26 个阶段、31 份 PNG、实际 DXF 和 DXF SVG 渲染。输入 SHA-256 为 `526e0d7fd9a5cdeb1d25764b93ce9c655688364eb762f47898d850aded14b8af`，`structure_id` 为 `2001fd68149510e152da9c0ee66e85c1e786a0a15f62c8ef9bfda65ad9c7ff26`，DXF 审计错误为 0。
