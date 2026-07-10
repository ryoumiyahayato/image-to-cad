# CAD Photo to DXF v1.1

将纸质 CAD 图纸照片转换为可编辑 DXF `LINE` 实体的 Windows/Python 工具。

项目源码位于 [`cad_photo_to_dxf/`](cad_photo_to_dxf/README.md)。从仓库根目录运行前请先进入该目录：

```powershell
Set-Location .\cad_photo_to_dxf
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

v1.1 新增纸张真实比例校正、严格失败保护、后台取消、逐算子预览、处理报告、原始线到最终实体谱系、保守 HATCH 判定、辅助圆/符号/OCR 候选，以及 Windows 构建和安装/卸载冒烟流程。

完整使用说明、命令行参数、技术边界和 Windows 发布流程见 [`cad_photo_to_dxf/README.md`](cad_photo_to_dxf/README.md)。
