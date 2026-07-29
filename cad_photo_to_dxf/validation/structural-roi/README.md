# 阶段六：结构 ROI 生成与约束验证

## 结论

阶段六仅收紧结构 ROI、连接保护和证据输出，没有增加识别类型、页面专用规则、OCR 词义规则、固定坐标、页面百分比或识别阈值补丁。

生产连接判定现在同时执行以下硬约束：

1. 候选的起点和终点必须位于同一个已验证 `StructuralRoi`；
2. 完整连接笔画必须位于该 ROI 的局部修复走廊，而不是只位于网络外接矩形；
3. 连接不得穿过 OCR 文本、Logo、签名或 ROI 内非结构源墨迹；
4. 连接不得合并多个无关结构连通域；
5. ROI 右边界和下边界采用数组一致的半开区间，边界外像素不能因取整被接受。

阶段六固定标签为 `baseline/phase6-structural-roi-2026-07-29`。

## ROI 来源和保护证据

真实页验证得到 50 个局部结构网络：

- 38 个表格线网络；
- 12 个闭合框架网络；
- 每个 ROI 均保存源直线索引、交点、置信度、线宽统计、方向统计、扩张距离和端点走廊；
- ROI mask 是源结构线带及有限端点扩张的并集，不再是整块外接矩形。

保护类别和当前机制：

| 类别 | 保护机制 |
| --- | --- |
| 高置信度文字 | 已接受 OCR 候选的源区域 |
| Logo | 独立 Logo 候选区域 |
| 签名 | 独立签名候选区域 |
| 工程符号、箭头 | ROI 内不属于结构线的源墨迹 |
| 尺寸数字、引线标注 | OCR 区域或 ROI 内非结构源墨迹 |

这些保护只判断连接安全性，不改变对象归属或对象类型。

## 前后证据

| 指标 | 修改前 | 修改后 |
| --- | ---: | ---: |
| 真实页 | 10 | 10 |
| ROI 数量 | 50 | 50 |
| ROI mask 像素 | 12,290,035 | 733,561 |
| ROI 内端点证据 | 0 | 1,532 |
| ROI 元数据缺失 | 50 | 0 |
| 批准连接 | 852 | 852 |
| ROI 外拒绝 | 678 | 678 |
| 批准连接越出 ROI | 0 | 0 |
| 批准连接穿过保护 mask | 无法证明 | 0 |

ROI mask 面积下降 94.031%，但 10 个已有页面的 `structure_id` 与阶段五基线逐一相同。阶段六因此收紧了允许区域和审计证据，没有通过调阈值改变既有识别结果。

完整数据：

- `phase6-before.json`：阶段五提交上的缺口记录；
- `phase6-after.json`：OCR 开启的 10 页 ROI 和连接逐项审计；
- `phase6-real-regression.json`：12 次完整 OCR、结构分析、预览、DXF 导出和内容审计；
- `phase6-pytest.xml`：完整单元测试结果；
- `phase6-verification.json`：阶段验收摘要和文件哈希。

## 复现命令

从真实回归 manifest 准备 10 个比较输入：

```powershell
.\.venv\Scripts\python.exe scripts\run_topology_comparison.py prepare `
  --manifest tests\real_regression\manifest.json `
  --output-dir output\ci\phase6-comparison-inputs `
  --minimum-pages 10
```

运行强制 ROI 验收：

```powershell
.\.venv\Scripts\python.exe scripts\run_roi_validation.py `
  --input-manifest output\ci\phase6-comparison-inputs\input-manifest.json `
  --output output\ci\phase6-roi-validation.json `
  --enable-ocr `
  --enforce
```

运行完整单元测试和真实回归：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_real_document_regression.py `
  --output output\ci\phase6-real-regression.json `
  --artifacts output\ci\phase6-real-regression-artifacts
```

验收命令以非零状态拒绝缺少 ROI 元数据、缺少保护类别、ROI 外批准连接、保护区穿越或少于 10 页的输入。
