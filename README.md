# 纸质 CAD 图纸照片转可编辑 DXF — MVP

这是一个电脑端 Python MVP：导入手机拍摄的黑白打印 CAD 图纸照片，完成纸张透视校正、去阴影、二值化、线段检测、基础几何修正、启发式图层分类，并导出可在 AutoCAD、中望 CAD、浩辰 CAD中打开和编辑的 DXF R2010 文件。

导出的主体是独立 `LINE` 实体，不是嵌入图片，因此可以在 CAD 软件中单独选择、删除、移动和继续绘制。

## 1. 环境要求

- Windows 10/11、macOS 或 Linux
- Python 3.11 或更高版本
- 建议使用虚拟环境

## 2. 安装依赖

在项目根目录执行：

```bash
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

macOS / Linux：

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 3. 启动 GUI

```bash
python main.py
```

主流程：

1. 点击“导入图片”，选择 JPG、JPEG 或 PNG 图纸照片。
2. 点击“自动识别纸张并校正”。
3. 自动识别失败时，点击“手动点击四角并校正”。
4. 点击“图像预处理”，生成去阴影后的黑白图。
5. 点击“识别并清理线条”，查看识别线条预览。
6. 可点击“点击两点校准比例”，输入对应的实际毫米长度。
7. 点击“导出可编辑 DXF”。

鼠标滚轮可以缩放图像；非选点状态下可拖动画面。

## 4. 手动选择四个角点

1. 点击“手动点击四角并校正”。
2. 在“原图”页中点击纸张的四个角。
3. 四点顺序不限，程序会自动排序为左上、右上、右下、左下。
4. 第四个点点击完成后，程序自动执行透视变换并切换到校正图。
5. 方向不正确时，可使用旋转 90°、180°、270°按钮。

角点应尽量落在纸张外边缘，而不是图框内边缘。

## 5. 图像预处理

预处理包含：

- 灰度化
- 中值去噪
- 形态学背景估计与去阴影
- 局部对比度增强
- 自适应阈值二值化
- 小噪点清理

“二值化强度”越大，通常保留的浅色线条越少；如果细线消失，可适当减小。如果阴影和灰底残留较多，可适当增大。

## 6. 线条识别与几何修正

MVP 同时使用概率霍夫变换和 LSD 线段检测，并执行：

- 过短线段过滤
- 接近水平/垂直的线条正交化
- 相近端点吸附
- 小间隔断线连接
- 共线线段合并
- 近重复线删除

参数建议：

- 最小线段长度：图纸分辨率较高时增大，细节较多时减小。
- 最大断线连接距离：过大会跨越真实开口，过小则断线无法连接。
- 端点吸附距离：用于合并非常接近的交点。
- 水平/垂直角度容差：建议 2°–5°。明显斜线不会被强行拉直。
- 保留填充线：取消后，会丢弃被判断为 HATCH 的密集平行线。

## 7. 比例校准

1. 点击“点击两点校准比例”。
2. 在校正图上点击两个已知点，例如一条标注尺寸线的两个端点。
3. 输入实际长度，例如 `12000` mm。
4. 软件计算 `mm/px` 比例，并在导出时应用到所有线段。

如果不进行比例校准，程序会提示“未校准真实尺寸”，并按 `1 像素 = 1 毫米图形单位` 导出。此时结构仍可编辑，但尺寸不代表真实工程尺寸。

## 8. DXF 图层

输出至少包含以下图层：

- `OUTLINE`：较粗的主要外轮廓
- `WALL_OR_FRAME`：墙体、房间边界、框架线
- `GRID_OR_AXIS`：较长的轴网线、参考线
- `HATCH`：局部密集平行填充线
- `DETAIL`：其他细节线

图层分类为启发式结果，设计目标是降低填充线对主体编辑的干扰，而不是保证建筑语义完全正确。

## 9. 命令行无界面运行

用于批处理或快速验收：

```bash
python main.py --headless --input samples/test.jpg --output output/output.dxf --preview output/preview.png
```

可选参数：

```bash
python main.py --headless \
  --input samples/test.jpg \
  --output output/output.dxf \
  --preview output/preview.png \
  --min-line-length 35 \
  --threshold-strength 12
```

加入 `--no-hatch` 可丢弃疑似填充线。

## 10. 输出文件

默认输出目录：

```text
output/
  output.dxf
  preview.png
```

`output.dxf` 使用 DXF R2010，图形单位设置为毫米。每条识别线段均导出为独立 `LINE` 实体。

## 11. 当前 MVP 限制

- 不能 100% 还原原始 DWG，也不尝试猜测原始 CAD 的全部对象类型和图层。
- 小文字、尺寸标注、引线、箭头暂不保证识别；第一版未启用 OCR。
- 模糊、弯曲、反光、阴影严重或纸张折叠明显的照片需要人工选择角点并调节参数。
- 图层分类为启发式，不保证完全准确。
- 双线墙体会以多条独立 LINE 表示，暂不自动转成建筑墙对象。
- 圆、圆弧、样条曲线目前可能被拆成短线段或遗漏。
- 门窗、楼梯、柱子等建筑符号尚未做专门语义识别。
- 未校准比例时，DXF 的真实尺寸不准确。

## 12. 拍照建议

- 尽量让整张纸完整入镜，四角清晰。
- 镜头尽量垂直于纸面，减少强透视。
- 使用均匀照明，避免手臂、手机或顶灯形成大块阴影。
- 不要使用过度压缩或聊天软件二次压缩后的图片。
- 黑白打印线条越清晰，主体结构还原效果越稳定。

## 13. 项目结构

```text
cad_photo_to_dxf/
  main.py
  requirements.txt
  README.md
  app/
    __init__.py
    gui.py
    image_loader.py
    perspective.py
    preprocess.py
    line_detect.py
    geometry_cleaner.py
    layer_classifier.py
    scale_calibrator.py
    dxf_exporter.py
    pipeline.py
  samples/
    test.jpg
  output/
    output.dxf
    preview.png
```
