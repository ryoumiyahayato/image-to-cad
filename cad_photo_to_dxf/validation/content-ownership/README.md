# 阶段八：统一对象归属与冲突仲裁

## 结论

阶段八把结构线、OCR 文字、Logo、签名和普通图形的候选证据分开保存，
再由一个统一仲裁器决定最终像素归属和可导出的对象。生产链不再先删除
Logo 或签名像素后再检测直线，也不允许某个识别模块直接改写另一个模块
的候选类型。

固定基线标签为 `baseline/phase8-content-ownership-2026-07-30`。

## 仲裁合同

候选模块只提供独立证据：

- 直线候选：源像素支持的中心线、线宽和检测置信度；
- 文字候选：OCR 源区域、OCR 置信度和可安全替换状态；
- Logo 候选：精确视觉 mask 和结构证据；
- 签名候选：精确视觉 mask；
- 普通图形：没有语义候选认领的源轮廓像素。

仲裁器保存每类候选数量、像素数和置信度范围。每个冲突对象保存候选
类别、每类置信度、重叠像素、冲突原因、仲裁规则、最终类别、residual
像素和降级原因。

当前显式规则为：

1. 只有同时具备独立源端点的强结构线，才能在纯“直线/文字”冲突中保留
   结构线；对应文字降级为保留源轮廓。
2. 没有独立结构端点的字符横画或竖画归文字，弱直线候选不导出。
3. Logo、签名或多类语义证据互相冲突时，不按类型优先级吞并；精确冲突
   像素进入 `residual`。
4. 任一导出对象只保留最终归属于自身类别的精确源像素；不能完整拥有源
   像素的对象被裁剪或降级，并记录原因。
5. 没有语义候选的源像素进入显式 `graphic` 轮廓，不再把 `residual`
   当作默认容器。

## 前后证据

十个唯一真实页面的统一像素审计结果：

| 指标 | 阶段七 | 阶段八 |
| --- | ---: | ---: |
| 源前景像素 | 3,104,606 | 3,104,606 |
| 恰有一个最终归属的像素 | 3,104,606 | 3,104,606 |
| 背景误归属像素 | 0 | 0 |
| 冲突像素 | 1,169 | 1,056 |
| 有完整解释的冲突对象 | 0 | 75 |
| residual 像素 | 1,985,913 | 39 |
| 显式普通图形像素 | 不可用 | 1,990,153 |
| 有完整原因的对象降级 | 不可用 | 42 |

75 个冲突对象的最终类别为：结构线 34、文字 37、未决 residual 4。
39 个 residual 像素全部来自未决语义冲突；普通无分类轮廓不再混入
residual。

连接安全复核仍为零批准、零错误桥接、零保护区穿越、零 ROI 外批准。
三个已标注真实断点仍未修复，没有为了提高召回率放宽阶段七门槛。

## 证据文件

- `phase8-before.json`：阶段七基线上的对象归属缺口；
- `phase8-after.json`：十页逐像素候选、冲突、降级和最终归属审计；
- `phase8-connectivity-guard.json`：第5–7阶段连接与 ROI 约束复核；
- `phase8-real-regression.json`：12次完整 OCR、结构分析、预览、DXF 和内容审计；
- `phase8-pytest.xml`：236项全量单元测试；
- `phase8-verification.json`：阶段验收摘要与证据哈希。

## 复现命令

从 `cad_photo_to_dxf` 目录运行：

```powershell
.\.venv\Scripts\python.exe scripts\run_topology_comparison.py prepare `
  --manifest tests\real_regression\manifest.json `
  --output-dir output\ci\phase8-inputs `
  --minimum-pages 10

.\.venv\Scripts\python.exe scripts\run_ownership_validation.py `
  --input-manifest output\ci\phase8-inputs\input-manifest.json `
  --output output\ci\phase8-ownership.json `
  --enable-ocr `
  --enforce

.\.venv\Scripts\python.exe scripts\run_roi_validation.py `
  --input-manifest output\ci\phase8-inputs\input-manifest.json `
  --output output\ci\phase8-connectivity-guard.json `
  --enable-ocr `
  --enforce

.\.venv\Scripts\python.exe scripts\run_real_document_regression.py `
  --manifest tests\real_regression\manifest.json `
  --output output\ci\phase8-real-regression.json `
  --artifacts output\ci\phase8-real-regression-artifacts

.\.venv\Scripts\python.exe -m pytest -q
```

以上命令在 fixture 缺失、像素未归属、背景被归属、候选置信度缺失、
冲突或降级说明不完整、residual 含非冲突像素、连接越界或真实回归变化时
返回非零状态。
