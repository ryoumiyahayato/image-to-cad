# CAD Photo to DXF v1.1.0

将纸质 CAD 图纸照片转换为可编辑 DXF 几何候选的 Windows/Python 辅助工具。

> 当前定位：需要人工确认纸张四角、尺度和几何结果的纸面直线提取工具。它不能恢复原始 DWG/CAD 模型，不能自动推断标注中的设计尺寸，也不能在未经人工复核时用于制造、施工或尺寸交付。

项目源码位于 [`cad_photo_to_dxf/`](cad_photo_to_dxf/README.md)。从仓库根目录运行：

```powershell
Set-Location .\cad_photo_to_dxf
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

坐标模式必须明确区分：

- `paper_mm`：打印纸面毫米坐标；
- `model_mm`：通过图纸比例或已知实际尺寸人工校准后的模型坐标；
- `pixel`：尚未校准的图像坐标。

当前处理链包括严格纸张候选验证、人工四角确认、分辨率归一化预处理、Hough/LSD 候选融合、保守粗线中心化、几何清理、最终去重、交点分割、端点拓扑检查、DXF 导出和统一 JSON 报告。圆、圆弧、文字、尺寸和建筑符号仍属于辅助候选，不应视为已恢复 CAD 语义。

完整使用说明、技术边界、验证工具和发布流程见 [`cad_photo_to_dxf/README.md`](cad_photo_to_dxf/README.md)。审计整改状态见 [`docs/AUDIT_REMEDIATION.md`](docs/AUDIT_REMEDIATION.md)。
