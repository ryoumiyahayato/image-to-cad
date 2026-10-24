# 2026-10-24 源码保全与同步候选（历史过程记录）

状态：`SOURCE_CANDIDATE / DRAFT_PENDING_FINAL_CI_AND_PRIVATE_EVIDENCE`。上传、合并和产品验收分别记录。

后续更新：用户已授权自审后合入 main；保存合同的受控比较、修复及私人测试边界处置见 [PR #35 审查记录](PR35_REVIEW_20261024.md)。以下 Draft/CI 阻塞描述记录同步当时的状态，不是后续合并状态。最终结果以 PR #35 为准。

## 本地保全

| 工作树 | 现场 HEAD | 状态记录数（展开未跟踪文件） | 快照文件 | 新目录逐字节恢复 |
|---|---|---:|---:|---|
| parent | `c566d5f59391` | 102 | 1129 | PASS |
| instrumented-e03 | `e5b80f9cbf9f` | 340 | 57011 | PASS |
| p20c-text-export-20261019 | `4cc1f96e150c` | 0 | 1584 | PASS |
| p20d-native-stroke-20261019 | `fe2b11476719` | 10 | 1599 | PASS |
| p18d-w02-completion | `e57d884e8dd9` | 0 | 1599 | PASS |

父树状态使用备份目录中的独立 HEAD 参考索引；原暂存意图 UNKNOWN。其他树读取自身索引。共用 Git 目录、原索引、refs、reflogs 和对象已复制；完整 all-refs.bundle 通过 Git 内置验证并在新目录克隆。工作文件另外保存 ZIP、二进制差异和路径清单，不能用 bundle 替代。

本地恢复根：`D:/programs/Image-to-CAD-baseline-backups/SYNC-20261024/`。各树下的 restored 是实际异地解压结果；inventory.json 与 file-paths.json 记录范围。排除可再生的 .venv、字节码及常见工具缓存；保存过程中存在于其他命名 runtime 目录的文件也可能进入本地快照。没有清理原件。真实资料和完整本地历史不进入公开分支。

未晋级活动成果另存本地 `recovery/instrumented-e03-unpromoted-20261024`；P20-D 另存 `recovery/p20d-native-stroke-20261019-unpromoted-20261024`。提交与 bundle 回执见恢复根的 private-recovery-branches.json。这些分支只在私人恢复克隆，不推送到公开仓库。

恢复步骤：先在新目录 clone all-refs.bundle；按 inventory 的 HEAD 建分支；从相应 ZIP 解压工作文件到另一新目录；用保存的 tracked 路径、差异和原索引副本核对。不要覆盖原工作树，不把父树 HEAD 参考索引解释为丢失的暂存区。

## 产品归属

候选以远端 `8f78f1368b99d3b19407196e3d99d104ec801e17` 为父提交。原 main 为 `76b4c8c3ce27daec0d49796ba7737b6197a4c849`。没有并入本地旧提交链。新提交仅包含逐文件白名单。

产品源码依据 P21-A 实验前保存的 baseline-runtime。114 个受跟踪应用/资源/入口文件与 e5b80f9 忽略换行后逐项相同，另含三个当时已有的 OCR 依赖。候选保持同一运行基准，另作静态格式及测试接口兼容整理。[模块及内容清单](RUNTIME_CONTENTS_20261024.json)列出每个路径和大小。

| 产品阶段 | 纳入的已有机制或历史结论 | 归属 |
|---|---|---|
| P11-B / P13-B | 来源规则线责任、单字显示范围 | 已有有界产品实现 |
| P13-E/F/I | 同快照文字复核、可持久修订、来源建议与布局确认 | 已有产品实现；外部编辑器完整往返未通过 |
| P14-B | 完整孤立扫描曲线来源保留 | 已有有界产品实现 |
| P15-A | 保存页 CAD 独立检查器 | 已有检查工具，不是自动修复 |
| P16-C | 不一致 TEXT 拒绝原子发布 | 已有出口保护 |
| P16-D/E、P17 | 局部源分量保留、来源行显示及保护 | 继承基准中的开发实现；历史部分结果与未解决缺陷保留，不作阶段整体验收 |
| P18-A | 原生面积与可携带 DXF 表达 | 已有有界实现；P18-B 数字输入候选未晋级 |
| P19-A/B/E | 手动文字重建、异步复核、有限来源组替换 | 已有有界实现；P19-E 为 PARTIAL |
| P20-A | 真实闭合简单直线多边形面积资格 | IMPLEMENTED_SINGLE_SOURCE，不宣称第二来源完整重跑 |
| P20-C | literal caret 可逆写盘 | 已有源码与合成出口测试；兄弟树原报告已核对 |
| P20-B/D/E/F/G/H | 几何、极性、数值或布局诊断 | 报告索引；P20-D 未提交候选不进入产品 |
| P21-A/B/C/D | 显示、分数、笔画支持研究 | 未晋级；活动 P21-A 两处入口改动及新模块保存在私人恢复分支 |

start-stable 原脚本仅按活动目录启动，并不证明稳定。公开脚本现在明确加载当前独立检出的 cad_photo_to_dxf，Python 由 -Python 指定或从 PATH 解析。当前版本仍为 0.3.0-dev，schema4/cache11；没有发布。

## 研究与证据

Goal01—22 原始报告均已在本地回核，未发现晚于 Goal22 的独立研究目录或阶段报告。逐文件范围与未同步源码见 [SYNC_SELECTION](SYNC_SELECTION_20261024.json)。研究程序在 experiments，与生产入口隔离。只保存旧代码与已有原创样例，没有训练、重跑真实转换或开始新 Goal。

| Goal | 结论或限制 |
|---|---|
| 01 | 来源 PATH 虚线编辑单元原型；无生产替换权限 |
| 02 | 来源辅助选择未证明降低本次操作负担，停止扩建 |
| 03—04 | 有界可见笔画恢复与重复控制；独立 C 未就绪，生产 NO_GO |
| 05 | 人工复核未完成；LibreCAD 往返失宽，不能作为保宽验收 |
| 06 | 两种标准替代表达在本机 LibreCAD 均失宽；停止低成本变体 |
| 07 | QCAD Trial 有界保宽成立；整份 CAD 完整往返未验收 |
| 08—10 | 数值来源核对、局部表示与输入保留诊断；没有自动安全修复 |
| 11 | 冻结公式模型能力诊断；没有正常 CAD 收益 |
| 12—13 | 取样与方向敏感性；局部收益伴随保护失败，停止替换路线 |
| 14—16 | 八角色任务、合成拟合与拟合诊断；不是真实产品精度 |
| 17—20 | 冻结迁移、身份监督、角色组合与配对干预；真实净收益未建立 |
| 21 | 同裁片 OCR 15/17、新读取器 8/17；新增正确 0、损失 7；停止新读取器 |
| 22 | 10 个正常父框；定位 16/17、绑定 12/17、有效数字证据 10/17；核查 31 区域；正式 CAD 改善 0、生产 NO_GO |

Goal12/13/21/22 使用原有技术汇总版；详细真实逐项报告不公开。Goal22 的 7 个原创机制例只同步 JSON 几何、历史读数与 v1/v2，来源全部为 SYNTHETIC_DIAGNOSTIC，不含真实图像/数组。失败和歧义原样保留。其他 Goal 的代码是技术源码保存，完整复现仍需要私人材料、旧模型和各自依赖；部分真实资料编排程序因公开边界未同步。

## 检查与合并边界

202 项相关产品检查最终通过，首次失败为旧测试替身缺少 source_structure_id，已补齐接口，断言未删改。改变文件的 Ruff 通过；格式化前后 AST 直接比较一致。保留 Qt 对象生存期，显式登记跨文件 fixture，移除无用导入并重命名歧义局部变量。生产模块导入及启动器 --version 通过。仓库现有卫生检查通过，finding_count=0；182 个选定 Python 文件完成内存编译检查，Goal22 保存合成比较返回 DIGIT_VALUE_EQUAL 且无自动写回权限。检查记录位于本轮独立工作目录；最终 SHA 的 CI 从 PR checks 读取，不能用文档检查点的 CI 代替。

仍有公开边界阻塞：14 份依赖真实来源或含逐项真实几何的产品测试，以及 3 份未晋级活动测试留在私人恢复副本；新的真实区域 PNG、真实几何 JSON、完整 local-artifacts、详细报告、私人评审、权重及环境均未上传。保留远端已有合法字体、测试素材和历史证据合同，没有删除既有受跟踪文件。未取得私人材料的公开许可或等价检查条件前，Draft 不因上传成功而解除。

本轮没有新算法、真实 OCR/整页转换、训练、GUI 验收、Release/tag 或下一阶段研发。最终远端 SHA、CI 结果和 main 是否更新由 PR 收口记录给出。

## 首次源码 SHA 的 CI 与兼容修正

首次源码候选 1036f82a9242aa5f46702b54e82293bee5b7daa2 的 Linux CI 为 942 passed、3 failed、8 skipped。三个失败分别是：P10-A preservation-current-p10a.json 的 algorithm_version 与当前运行基准不一致；残余层校对已传 native_fills，但 RasterTraceResult 尚无对应字段；旧缓存测试仅 removesuffix，当前算法身份又追加了后续阶段标记。

后两项作为同步接口兼容修正：RasterTraceResult 补原生面积可选载荷，FinalStructure 适配器继续转交；缓存测试使用本地既有 replace 写法，保留“不相等”断言。17 项相关现有检查通过，涉及文件 Ruff 通过。公开测试只纳入该缓存断言兼容片段，不公开同文件的其他本地真实来源改动。

P10-A 保存基线及 preservation_check.py 没有修改。未新建替代保存基线、删断言、放宽算法身份检查或增加跳过。该历史合同与当前算法身份尚未完成审查，继续阻塞合并。最终 SHA 的现有 CI 仍须按 PR 读回；首次源码 SHA 的结果不能代表后续提交。

## 后续 SHA 检查与 Windows 退出码

6e5660a193b695778ad55c00eb7032445b4b8e57 的 Linux CI 为 944 passed、1 failed、8 skipped，唯一失败仍是 P10-A algorithm_version 合同。该 SHA 的仓库卫生与 FreeCAD workflow 通过。未把 Linux 因前序失败而跳过的后续步骤记为通过。

只读核对发现 Windows 现有 regression/static 步骤串行执行 pytest、Ruff、mypy、compileall，但没有逐条检查原生命令退出码。本轮为每条既有命令补失败即退出，不增加新检查，不改测试条件。最终 Windows workflow 的结果因此能够保留前序失败。最后提交的 SHA 与四项 workflow 结果见 PR #35 收口回执。

Windows 在 48b0ac6932669bbff9e40e7b4e07d5a8d99e5e31 实际返回 943 passed、2 failed、8 skipped；失败分别为同一 P10-A 合同，以及临时目录保存保护。后者的目标路径已 resolve，缓存目录却未 resolve；本轮把缓存目录也解析后再做原有 is_relative_to 拒绝比较。既有 source/temporary overwrite 检查在本机通过，文件 Ruff 通过；没有删改断言或放宽路径保护。最终 Windows 结果继续按最后 SHA 读取。
