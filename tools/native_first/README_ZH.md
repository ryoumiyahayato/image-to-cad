# PDF 原生导入

此命令行工具调用与桌面程序相同的 `app.core.pdf_conversion`。普通用户可直接从桌面或 `cad_photo_to_dxf/main.py` 打开 PDF，由统一入口逐页选择原生提取或扫描识别。

```bash
python -m tools.native_first.import_pdf input.pdf --page 1 --inspect
python -m tools.native_first.import_pdf input.pdf --page 1 --output output/page.dxf
```

`--page` 从1开始，已有输出默认保留，显式 `--overwrite` 才覆盖。输出使用 PDF 纸面毫米，不猜工程比例。默认黑白图层；`--color` 保留源颜色。

原始直线、矩形、折线、曲线填充直接写出原生 DXF。符合圆弧条件的曲线写为 ARC/CIRCLE，其他三次曲线保留为精确控制点 SPLINE。可见 Unicode 文字保留为完整 TEXT，嵌入图像保留独立 IMAGE 及原透明度。隐藏 OCR 层不会再次绘制到扫描页面上。旋转页按页面实际方向变换。

DXF 旁的 `fonts/` 和 `<图名>_images/` 是交付的一部分，移动图纸时保留这些目录。中文字体为随程序准备的 Noto CJK；LibreCAD 使用随程序安装的 `wqy-unicode` 字体。文字轮廓型 PDF 没有可提取的 Unicode，原轮廓仍作为原生路径保留，报告明确指出需要 OCR 恢复文字。

纯扫描页由统一入口送至扫描预处理、基础几何和中英文 OCR，不由此原生提取工具伪装成可编辑路径。复杂裁剪、特殊混合组和 PDF 注释仍需查看报告及实际输出；不会用一次小例验证代表任意 PDF 支持。
