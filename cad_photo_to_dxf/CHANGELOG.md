# Changelog

## 1.1.0

- 增加稳健四角排序、空白图拒绝、纸张真实长宽比和纸张边界比例推导。
- 增加 GUI 后台任务、合作式取消、进度显示和结果版本失效保护。
- 增加逐算子预处理预览和 CLI 调试目录。
- 默认保护单像素水平、垂直和斜向长线。
- 改进粗线宽度估计、端点吸附、最终交点保持和重复/共线合并谱系。
- 增加 HATCH 多证据评分、封闭边界近似和 `HATCH_CANDIDATE` 图层。
- 增加完整源线到最终实体 JSON 谱系和阶段级几何报告。
- 增加圆、矩形符号和可选 OCR 辅助候选。
- 增加严格 CLI 退出码、原子 DXF/JSON 写入和逐阶段进度。
- 增加 PyInstaller、Inno Setup、Windows Runner 和安装/卸载冒烟配置。
- 增加核心回归测试。

## 1.3.0-preview.1

- Added scan-faithful multi-page PDF export to one DXF/DWG document.
- Added one paper-space layout per PDF page plus a model-space page stack.
- Replaced table-only layer review with direct visual selection, re-layering, and deletion.
- Removed the separate circle confirmation step from the normal workflow.
- Added contrast-preserving level-of-detail rendering for zoomed-out large sheets.
- Strengthened text-region suppression and kept the original scan as the visual source of truth.
- Collapsed normal-mode algorithm parameters and made preprocessing implicit in vectorization.
- Kept the build as an internal preview; vector reconstruction accuracy is not claimed as 95-98%.
