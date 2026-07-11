# CAD Photo to DXF v1.1

将打印图纸照片中的直线提取为可独立编辑的 DXF `LINE` 实体。

本项目当前定位是：

> 需要人工确认和尺寸校准的纸面直线矢量化辅助工具。

它不是原始 DWG/CAD 模型恢复器，也不保证自动恢复工程设计尺寸、拓扑闭合、圆弧、文字、尺寸标注或建筑语义。任何用于制造、施工或尺寸交付的结果都必须由具备相应资质的人员复核。

项目源码位于 [`cad_photo_to_dxf/`](cad_photo_to_dxf/README.md)。从仓库根目录运行：

```powershell
Set-Location .\cad_photo_to_dxf
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

当前坐标模式分为：

- `pixel_units`：未校准的无单位像素坐标；
- `paper_mm`：打印纸面毫米坐标，不是工程模型尺寸；
- `model_mm`：使用已知设计尺寸校准后的模型毫米坐标，仍需独立尺寸复核。

自动纸张识别采用保守阈值。低置信度或不符合纸张外观的候选会失败并要求手动确认四角，不再静默把原图当作已校正图。

每次 DXF 导出会生成机器可读验证结果，检查 DXF 审计错误、非法或零长度实体、重复实体和悬空端点。验证通过只证明文件结构和这些几何不变量满足要求，不证明恢复结果与原始 CAD 一致。

完整使用方法、技术边界、测试规范和 Windows 构建流程见 [`cad_photo_to_dxf/README.md`](cad_photo_to_dxf/README.md)。
