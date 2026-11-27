# 图像转 CAD 应用目录

完整产品红线、三层架构定位、运行依赖、CLI 参数与当前已知缺口说明，请先阅读仓库根目录 [README.md](../README.md) 与 [三层架构蓝图](../docs/project/ARCHITECTURE_AND_ROADMAP_ZH.md)。

本目录共用唯一转换入口 `app/core/conversion.py`（桌面与命令行一致）：

```powershell
# 启动桌面程序
python main.py

# 命令行转换扫描图或 PDF
python main.py --input scan.png --dpi 300 --output output/scan.dxf
python main.py --input drawing.pdf --output output/drawing.dxf
```

具体可用参数见 `python main.py --help`。严禁恢复任何单裁片检查点或特定样图规则账本。
