# 图像转 CAD

将 PDF 或扫描图转换成可编辑 DXF。当前开发版本 **0.4.0-dev**。

## 普通使用流程

桌面启动后选择文件，设置输出位置，点击“转换并保存 DXF”。支持 PDF、PNG、JPG、TIFF、BMP；多页 PDF/TIFF 默认逐页输出。窗口可切换原图与从已保存 DXF 重新读取的预览，并选择结果页。

| 输入/内容 | 处理方式 | DXF 输出 |
| --- | --- | --- |
| 矢量 PDF | 直接读取原生路径与可见文字，不降为整页图片 | LINE、LWPOLYLINE、ARC、CIRCLE、SPLINE、HATCH、TEXT |
| 扫描图/扫描 PDF | 去阴影和局部污渍、可选透视校正、中心线和基础几何拟合 | 直线、多段线、圆、圆弧 |
| 中英文印刷文字 | RapidOCR 按整行识别，保留文字内容和位置 | 可编辑 TEXT |
| 签章、Logo、未拟合墨迹 | 独立透明图片保留 | IMAGE 及同名资源目录 |

黑白手写或 Logo 未自动识别为保护图形时，可在“原图”页点击“框选保护签章/Logo”，拖出矩形后转换当前页。选区以独立透明 IMAGE 保留，不进行 OCR 替换；切换输入、页码或 DPI 会清空选区。

输出使用黑白图层。黑色线条采用 CAD 的 ACI 7 以适应黑/白画布；扫描签章保留为黑色透明图像。PDF 图片保留原图及透明度。

默认尺寸为纸面毫米。扫描 DPI 应与来源一致；图纸注明 1:100 时，在“图纸比例 1:”中输入 `100`。照片透视校正改善形状，不能自动得出真实工程尺寸。未知比例应根据已知长度另行校准。

**保存、传送 DXF 时保留旁边的 `fonts/` 和图片目录：扫描输出使用 `<文件名>_assets/`，原生 PDF 使用 `<文件名>_images/`。**打开其他 CAD 前，可点击“准备 CAD 中文字体”：为当前用户安装 Noto CJK，并准备 LibreCAD 的文泉驿 LFF。安装后完全重启 CAD。

## 从源码运行

需要 Python 3.11+。在仓库根目录执行：

```bash
cd cad_photo_to_dxf
python -m venv .venv
# 激活 .venv 后：
python -m pip install -r requirements.txt
python scripts/prepare_cad_fonts.py
python scripts/prepare_ocr_models.py
python main.py
```

字体与 OCR 模型仅在准备阶段下载；完整打包程序可离线转换，不调用外部识别 API。

命令行与桌面共用相同入口：

```bash
# 矢量/扫描 PDF 自动分流；默认转换全部页
python main.py --input drawing.pdf --output output/drawing.dxf

# 只处理第 2 页，纸面比例 1:100
python main.py --input drawing.pdf --page 2 --scale 100 --output output/page2.dxf

# 照片透视校正与中英文 OCR
python main.py --input photo.jpg --perspective --dpi 300 --output output/photo.dxf

# 手动保留扫描中的 Logo 区域，坐标为源图像素 x0 y0 x1 y1
python main.py --input scan.png --preserve-region 100 200 450 350 --output output/scan.dxf

# 当前用户中文字体准备，与桌面按钮执行同一功能
python main.py --install-cad-fonts
```

多页输出命名为 `drawing-p001.dxf`、`drawing-p002.dxf` 等。转换同时保存每页实际 DXF 预览和一份结果 JSON。已有输出默认拒绝覆盖；确认需要替换时增加 `--overwrite`。`--no-ocr` 可关闭扫描文字识别。`--verbose` 显示进度。

仅使用原生 PDF 单页工具时，也可在仓库根目录运行：

```bash
python tools/native_first/import_pdf.py --help
```

## Windows 交付与验证

`Windows product build` 工作流构建完整便携 ZIP 和 Inno Setup 安装包。ZIP 应整体解压后运行 `CADPhotoToDXF.exe`。流程使用解压后的实际 EXE 做中英文扫描、两页原生 PDF、保存编辑重读、字体准备及桌面启动检查，再执行安装、转换和卸载。成功包在该次 Actions 运行的 artifacts 中；是否已通过以实际运行结果为准。

本地构建：安装 `requirements-dev.txt`，准备字体/模型，然后执行 `python -m PyInstaller --noconfirm cad_photo_to_dxf.spec`。Windows 安装包脚本位于 `installer/`。

常规验证：

```bash
cd cad_photo_to_dxf
python -m pip install -r requirements-test.txt
python -m pytest tests ../tools/native_first/tests -q
python -m ruff check app tests scripts main.py
python scripts/product_smoke.py --source-main main.py --work /path/to/new-smoke-output
```

## 已知边界

- 原生 PDF 只有文字轮廓而没有 Unicode 时，会保留路径并提示 `NO_NATIVE_TEXT`，不会把轮廓虚报为可编辑文字。
- 复杂裁剪、特殊混合组和 PDF 注释的完整等价转换尚未验证；报告会提示相关限制。
- 扫描 OCR 可能错字，细线可能断段、锯齿或拟合不准。低置信文字和未拟合墨迹尽量保留在图片图层，仍需人工复核。置信分数不等于正确率。
- 当前可编辑内容是基础图线、文字和独立图片；未承诺所有墙、门、设备或接线自动恢复成工程语义对象，也未完成工程师节时量化验收。

## 代码结构

`app/core/conversion.py` 负责统一输入和页面分流；`pdf_conversion.py` 与 `scan_conversion.py` 负责两条转换路径。`geometry/` 保存实际使用的通用算法，`ocr/line_recognition.py` 负责整行 OCR，`export/product_fonts.py` 负责完整字体资源，`gui/window.py` 提供桌面入口。历史实验与审计账本已从产品工作树移除，旧提交仍可通过 Git 历史及归档恢复。
