# CAD Photo / Scan PDF to CAD v1.3.0（内部预览）

将纸质图纸照片、扫描图片和图片型多页 PDF 转换为“扫描保真底图 + 可编辑结构线”的 DXF/DWG 辅助工具。

多页 PDF 会作为一个文档载入并合并导出：每页建立 `PAGE-###` 布局，模型空间同时纵向排列，并为每页保留独立扫描底图。人工复核已改为直接在图纸上框选、改层和删除错误线段。

> 当前仍是内部预览。扫描底图用于保留原始视觉内容；自动矢量线只是辅助结果，不能视为原始 DWG 恢复，也不承诺 95% 或 98% 的全矢量重建率。

项目源码与完整说明位于 [`cad_photo_to_dxf/`](cad_photo_to_dxf/README.md)。

```powershell
Set-Location .\cad_photo_to_dxf
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

支持的坐标模式：

- `paper_mm`：PDF 或打印纸面毫米；
- `model_mm`：通过已知实际尺寸独立校准后的模型坐标；
- `pixel`：尚未校准的图像坐标。

历史审计整改状态见 [`docs/AUDIT_REMEDIATION.md`](docs/AUDIT_REMEDIATION.md)。
