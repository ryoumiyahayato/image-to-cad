# 历史快照：仓库清理第二阶段（2026-11-20）

> 以下是当时的执行状态，含“main未改、Draft未合并、分支保留”。当前收口及恢复检查见[G1记录](G1_CLOSEOUT_20261120.md)；正常main前进不改写这里的历史结论。

**远端实际删除 7 条分支，关闭 PR #38／#39，清理分支实际移除 11 个 tracked 文件，共 16,445,839 字节（15.68 MiB）。** main 未改、历史未重写、15 个原归档标签原 SHA 保留。产品继续 0.3.0-dev / LOCAL_NO_GO。

基底：main 5b2a76b716a568bd6dad0a1e1e2a5f80145f0395；PR #40 f2ad95703cf1ccb0284137bfe7fbc39b137f3217。独立工作分支为 chore/native-object-cleanup-20261120。

## 1. 删除前后远端分支

GitHub API 和本地完整提交图双重核实 14 个分支；7 条安全删除后剩 7 条，创建本轮独立清理分支后实际为 8 条。以下 SHA 是清理开始时快照；本轮清理分支的最终提交和 CI 以清理 Draft PR 的 HEAD 为准。机器可读账本见 [manifest.json](cleanup_20261120/manifest.json)。

| 执行前分支 | 原 HEAD | 执行后 | 恢复位置／保留原因 |
| --- | --- | --- | --- |
| accuracy/compound-source-partitions-20261116 | 3ab1311eaabfd6a391b36c681d0d4204f6dcc52f | 已删除 | accuracy/native-grid-compound-parts-20261116 @ 2cba247dc9582485a74d696c2c49e83a558fa1a1 |
| accuracy/explicit-source-region-adapter-20261117 | d6d26c142f2d1998ef69ac181b18718dddb6d2d1 | 已删除 | accuracy/shared-core-directional-tracks-20261117 @ 775492497a1207c3ef7dae1af4f3a302aa78af39 |
| accuracy/native-grid-compound-parts-20261116 | 2cba247dc9582485a74d696c2c49e83a558fa1a1 | 保留 | 原 SHA 不变；唯一研究末端 |
| accuracy/shared-core-directional-tracks-20261117 | 775492497a1207c3ef7dae1af4f3a302aa78af39 | 保留 | 原 SHA 不变；唯一研究末端 |
| delivery/w02-glyph-source-boundary | c0671df319be467582c00354f1307a52c0116a3f | 已删除 | delivery/w02-librecad-handoff @ ebe4823522a12e6275c3b0dd72d62bb7b78e1e0e |
| delivery/w02-librecad-handoff | ebe4823522a12e6275c3b0dd72d62bb7b78e1e0e | 保留 | 原 SHA 不变；唯一研究末端 |
| delivery/w02-member-lifecycle-rebuilt | ece85a401a93f12743e493ac050929bbfd5a8da5 | 已删除 | delivery/w02-librecad-handoff @ ebe4823522a12e6275c3b0dd72d62bb7b78e1e0e |
| delivery/w02-weak-edge-source | 98de5e4e63371a5ddfb98c86a61f691f203e0fab | 已删除 | delivery/w02-librecad-handoff @ ebe4823522a12e6275c3b0dd72d62bb7b78e1e0e |
| docs/native-object-product-rebaseline-20261120 | f2ad95703cf1ccb0284137bfe7fbc39b137f3217 | 保留 | 原 SHA 不变；开放 Draft PR #40 |
| fix/py312-singleton-validation-20261116 | 05424c491fa8be0d8ef87cb6c1a96f351731e31b | 已删除 | main @ 5b2a76b716a568bd6dad0a1e1e2a5f80145f0395 |
| integration/compound-source-with-main-20261116 | 98b9cff608cd6aa4367a69a7a467c1fe22f5831a | 已删除 | accuracy/shared-core-directional-tracks-20261117 @ 775492497a1207c3ef7dae1af4f3a302aa78af39 |
| main | 5b2a76b716a568bd6dad0a1e1e2a5f80145f0395 | 保留 | 原 SHA 不变；main 基线 |
| sync/verified-online-r12-20261116 | e0f09e0674efc90ec0abb3d9e626f4efaaec5b5b | 保留 | 原 SHA 不变；独有资产待核对 |
| sync/20261116-recovered-progress | e398d6c99534142f17dfa71382d2405ab4a64899 | 保留 | 原 SHA 不变；独有资产待核对 |

新增 chore/native-object-cleanup-20261120，起点为 PR #40；用于可审核的文件清理及入口最小修正，不合并 main。

每个已删除祖先到恢复末端的 merge-base 均为原祖先 SHA，独有于恢复末端的提交数为 0。逐分支 main 外提交名单见 [unique_commits_before.json](cleanup_20261120/unique_commits_before.json)。grid 与 shared-core 不互相包含，分别保留；W02 末端也单独保留。

分支保护 API 标志为 false，唯一 main ruleset 当时 disabled；仍按用户要求保护 main 与旧标签，未改安全规则。Git 命令行写入缺凭据，分支删除通过已登录 GitHub 的正常 Delete/Restore 界面执行，删除后独立复核远端。

## 2. 关闭的旧提案

- [PR #38](https://github.com/ryoumiyahayato/image-to-cad/pull/38#issuecomment-7039600485)：局部短笔画加残余 HATCH，没有完整对象编辑证明；已说明由 #40 产品目标替代并关闭。
- [PR #39](https://github.com/ryoumiyahayato/image-to-cad/pull/39#issuecomment-7039601383)：显式人工选区 manifest 加 M/R/P HATCH，不是自动完整对象恢复；已说明来源绑定、预检和回滚价值并关闭。
- 两者均未合并，原 HEAD 与全部祖先在 shared-core 末端可达；旧 CI 成功不改记为新产品通过。

## 3. 已从 Git 跟踪删除的文件

删除前核对精确路径、目录别名、导入、测试、构建和文档引用。7 PNG 与保留 fixture blob 完全相同，3 日志为空，1 报告与仍被引用报告字节相同。

| 删除文件 | Git blob SHA | 字节 | 保留副本／原因 |
| --- | --- | ---: | --- |
| cad_photo_to_dxf/tmp/pdfs/actual-pdf-baseline/environment-page-003.png | d8f53b6ac0b5e5bb13251bab101ad68762724380 | 3834343 | cad_photo_to_dxf/tests/real_regression/assets/environment-page-003.png |
| cad_photo_to_dxf/tmp/pdfs/actual-pdf-baseline/warehouse-page-001.png | 391ca7de1e9d056c6ae983136a9a9b0bcf001590 | 166363 | cad_photo_to_dxf/tests/real_regression/assets/warehouse-page-001.png |
| cad_photo_to_dxf/tmp/pdfs/low-quality-regression/environment-01.png | 0323714daf4562b285bf0747c01a484754ccd7b4 | 2561729 | cad_photo_to_dxf/tests/real_regression/assets/environment-scan-page-01-120dpi.png |
| cad_photo_to_dxf/tmp/pdfs/low-quality-regression/environment-02.png | 639f1ea1d8cb13fdb57f8b4a9f2f08b68b5de2a2 | 2422514 | cad_photo_to_dxf/tests/real_regression/assets/environment-scan-page-02-120dpi.png |
| cad_photo_to_dxf/tmp/pdfs/low-quality-regression/environment-04.png | e2aa7fe9b445179272bb00f6de30a695a01ac632 | 2525132 | cad_photo_to_dxf/tests/real_regression/assets/environment-scan-page-04-120dpi.png |
| cad_photo_to_dxf/tmp/pdfs/low-quality-regression/environment-08.png | ee51470e51f7d612130bc2d3d66f3815cec07d37 | 2366635 | cad_photo_to_dxf/tests/real_regression/assets/environment-scan-page-08-120dpi.png |
| cad_photo_to_dxf/tmp/pdfs/low-quality-regression/environment-14.png | b25bbd4dcd056f1623e84be93c4e4e7bda6bb5a4 | 2534642 | cad_photo_to_dxf/tests/real_regression/assets/environment-scan-page-14-120dpi.png |
| cad_photo_to_dxf/tmp/v16.stderr.log | e69de29bb2d1d6434b8b29ae775ad8c2e48c5391 | 0 | 空日志，无引用 |
| cad_photo_to_dxf/tmp/v16.stdout.log | e69de29bb2d1d6434b8b29ae775ad8c2e48c5391 | 0 | 空日志，无引用 |
| cad_photo_to_dxf/tmp/warehouse-v16.stderr.log | e69de29bb2d1d6434b8b29ae775ad8c2e48c5391 | 0 | 空日志，无引用 |
| docs/refactor/preservation-final.json | 816ce48560e721dae6f9e42c1969daecbb220127 | 34481 | docs/refactor/closeout-preservation.json |

原文件均可从清理前提交 f2ad95703cf1ccb0284137bfe7fbc39b137f3217 恢复。账本另列 SHA-256、mode 和恢复命令。需要研究时建立独立恢复分支：

```bash
git fetch origin main
# 原f2ad957提交由包含#40的正常合并main或经验证归档保持可达
git switch -c recovery/cleanup-20261120 f2ad95703cf1ccb0284137bfe7fbc39b137f3217
# 或只恢复指定文件：git restore --source=<上面的原提交> -- <原路径>
```

删除减少当前树/检出的重复内容，**不减少已有 Git 历史对象**。本轮没有历史瘦身、强推或删除唯一恢复点。

## 4. 明确保留的项目

- 两个 sync 分支：一条有 3 个独有规范提交；另一条有 9 个历史 Git bundle，内部唯一对象尚未完整核对。
- 三个研究末端保留可复用源码、失败和回归，不直接合产品主线。
- 其余 39 个临时文件没有同字节的保留副本，尚不能排除唯一诊断价值。
- 字体 ZIP 的 AUTHORS／许可证元数据、sample fixture、实验局部导入、冻结快照和 phase12 基线保留；未证明废弃的入口不删。
- 既有真实 fixture 有内部使用／禁止再分发说明，需要独立权利处置。本轮不新增图纸或重复公开，也不删除必要 fixture 破坏基线；这不构成再分发许可判断。

## 5. 入口和默认构建

GUI/CLI 仍运行保留的 ProductionProcessingService 基线。新增状态说明和报告元数据，GUI 保存默认 DXF，DWG 只显式选择；spec 携带产品基准，开发或非 GO 版本不能正式发布。旧几何、OCR、serializer、来源掩膜和验收阈值不变。私有完整对象算法未接入，仍是后续功能整合任务。

## 6. 验证与局限

已冻结 173 个生产核心、真实 fixture、baseline、phase12 文件的路径、mode 和 blob。清单摘要 SHA-256：4a84e744eeb1338bea06e323fae831b7785a7c2544d936b5406c6e7c4eead3f7。

复核删除、保留副本、权限、生产基线与远端引用：

```bash
python maintenance/verify_cleanup_20261120.py --remote
cd cad_photo_to_dxf
QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_product_baseline_entry.py tests/test_cli.py tests/test_gui_page_export.py tests/test_gui_architecture.py tests/test_gui_guard.py tests/test_exact_ui_reduction.py tests/test_release_workflow.py tests/test_portable_font_bundle.py
python ../maintenance/preservation_check.py
python scripts/check_repository_hygiene.py --repository-root ..
```

实际本地回归和本次 Draft PR 的 CI 结果逐项记录；未执行即 NOT_RUN，初始缺依赖与候选失败分开。清理不证明算法、Windows/Android 包、目标 CAD 全类型往返或工程师人工收益通过。

### 本地已执行结果

- 8 个受影响测试文件：40 passed（3.01 秒），包括实际 CLI DXF 写出／冷读、Qt 导出选择、GUI 结构和既有 Release 合同。
- 原有 preservation 检查：3 个代表 case 完全匹配 2026-11-16 受保护基线，包含真实 sample-test 的 229 LINE、145 contour 及实际 DXF 冷读；保留 P10-A 来源义务。初次因缺 Qt 未启动，补齐运行依赖后才得到该结果，初始错误日志保留。
- 仓库卫生：0 findings；173 个冻结文件、7 条祖先恢复关系及 15 个原归档标签核查通过。
- 48 个变更 Markdown 相对路径链接目标存在；已跟踪文本的凭据特征检查未发现命中。特征扫描不等于保证不存在所有敏感内容。
- 本地环境为 Python 3.12.14、pytest 8.4.2、PySide6-Essentials 6.11.3；本地结果不替代 GitHub Python 3.11／Windows／FreeCAD CI。正式 Release 未运行。

清理 Draft PR 的实际 CI、提交 SHA 和后续失败记录以该 PR 的 checks 与结项评论为准，不能把上述本地结果写成远端 CI 成功。
