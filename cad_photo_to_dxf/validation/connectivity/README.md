# 阶段七：连接判定重写与验证

## 结论

阶段七只重写结构连接的审核合同、物理尺度传递和度量证据，没有增加识别类型，没有调整 OCR 或图形识别阈值，也没有加入页面坐标、文件名或页面比例特例。

每个候选连接现在必须同时提供并通过以下证据：

1. 延长方向与来源线方向一致；
2. 两条来源线的物理线宽相近；
3. 两个候选端点都有原始像素支持；
4. 空隙不超过 0.4 mm 的物理预算；
5. 空隙大于“来源线宽 + 一个采样像素”的可分辨下限；
6. 两条线属于同一个已验证结构网络；
7. 完整连接位于局部结构走廊和 ROI 内；
8. 不穿过文字、Logo、签名、符号、箭头、尺寸或引线保护区；
9. 不吸收 ROI 内非结构墨迹；
10. 连接后的连通分量变化符合结构拓扑；
11. 全部硬证据通过后，连接置信度才可严格超过 0.95。

物理参数固定记录为：最大连接距离 0.4 mm、线宽差容差 0.35 mm、保护区额外扩张 0.0 mm。最小可分辨空隙随检测线宽和 DPI 计算，不按页面长边比例放大。150、300、600 DPI 的等物理距离测试均通过。

阶段七基线标签为 `baseline/phase7-connectivity-decision-2026-07-29`。

## 前后对照

| 指标 | 修改前 | 修改后 |
| --- | ---: | ---: |
| 真实审计页面 | 10 | 10 |
| 结构 ROI | 50 | 50 |
| 候选端点 | 15,082 | 15,082 |
| 批准连接 | 852 | 0 |
| 错误连接 | 57 | 0 |
| 正确连接 | 0 | 0 |
| 未修复真断点 | 3 | 3 |
| precision | 0.0 | 1.0 |
| recall | 0.0 | 0.0 |
| F1 | 0.0 | 0.0 |
| 穿越保护区 | 0 | 0 |
| ROI 外批准连接 | 0 | 0 |
| 缺少完整证据的批准连接 | 852 | 0 |
| 未超过置信度阈值的批准连接 | 852 | 0 |

修改后的 precision 为 1.0 是“没有批准任何已标注正误连接”时的零分母约定，不表示召回改善。3 个标注真断点仍未修复，recall 和 F1 均保持 0.0。该结果符合“证据不足时拒绝连接”的验收要求，没有通过误连接换取召回率。

修改前 57 个错误批准全部位于索引表空白单元格标注区。逐项检查显示其物理空隙仅为 0.10–0.36 mm，而检测线宽约为 0.323 mm，属于不可分辨的粗线栅格抖动。修改后这些候选以 `unresolved_structural_gap` 拒绝。最终拒绝原因统计为：

| 拒绝原因 | 数量 |
| --- | ---: |
| `unresolved_structural_gap` | 1,038 |
| `outside_structural_roi` | 477 |
| `line_width_mismatch` | 18 |

合成断框测试同时证明：当两条来源边具有独立原像素端点、空隙可分辨且位于同一结构 ROI 时，双端仍可安全延长到共同交点。

## 回归与证据

- `phase7-before.json`：阶段六提交上的旧连接合同审计；
- `phase7-after.json`：最终连接合同的 10 页逐连接审计；
- `phase7-real-regression.json`：12 次完整 OCR、结构分析、预览、DXF 导出和内容审计；
- `phase7-pytest.xml`：232 项全量测试结果；
- `phase7-verification.json`：验收摘要、物理参数和证据哈希。

真实回归覆盖 10 个唯一页面和 22 个覆盖类别，包含 150、300、600 DPI 的同页变体。12/12 文档通过，所有内容对象、预览和 DXF 契约均与经审查的新基线一致。

## 复现命令

```powershell
.\.venv\Scripts\python.exe scripts\run_roi_validation.py `
  --input-manifest output\ci\phase5-comparison-inputs\input-manifest.json `
  --output output\ci\phase7-roi-validation.json `
  --enable-ocr `
  --enforce

.\.venv\Scripts\python.exe scripts\run_real_document_regression.py `
  --output output\ci\phase7-real-regression.json `
  --artifacts output\ci\phase7-real-regression-artifacts

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests validation main.py
.\.venv\Scripts\python.exe -m compileall -q app tests validation main.py
.\.venv\Scripts\python.exe -m mypy `
  app\resolution.py `
  app\scale_calibrator.py `
  app\reporting.py `
  app\auxiliary_recognition.py
```
