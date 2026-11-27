# 图像转 CAD 应用目录

使用、CLI 参数、构建和边界说明见仓库根目录 [README](../README.md)。

从本目录启动桌面：`python main.py`。普通转换：

```bash
python main.py --input drawing.pdf --output output/drawing.dxf
```

默认入口 `app/core/conversion.py` 由桌面、命令行和实际程序验证共用。无需 ROI、任务目录、来源检查点或重放材料。
