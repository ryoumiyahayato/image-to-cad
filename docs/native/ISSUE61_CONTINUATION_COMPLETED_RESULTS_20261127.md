# Issue #61：新检查点、普通续算出图及共同验收完成（2026-11-27）

## 本轮结论

按 [协调接续要求](https://github.com/ryoumiyahayato/image-to-cad/issues/61#issuecomment-7218448006)，本轮实际完成检查点 A → 普通出图 B → 独立验收 C。最终共同入口为 **`PASS_ZERO_ADOPTED_PRESERVED_BASELINE`**。

**436 个旧完整正式对象精确保持；48 REVIEW、55 命名块及关联资源保持；4 条完整候选实际重新执行，0 条新采用。** 这是已验证来源阶段的稳定续算结果。候选原墨仍 `SOURCE_UNRESOLVED`，完整独立候选模型待 #63 合同；本轮没有授权四笔新采用。

实际普通 DXF：`ISSUE61_15dccde_ORDINARY.dxf`，**199885 B**，SHA-256：

`b842c72bab8ed8e579a1cc7f8f04b315c231d98c2d78ea90aed9fbc368bf87db`

该文件来自真实 `main.py --headless --mode native-objects --source-stage-checkpoint`，退出码 0，任务状态 `COMPLETED_WITH_ISSUES`。未用旧 DXF 实体构造新图。新增上游拟合、OCR、模型推理均为 0；当前来源图、附着、接触、数值合同、保存、冷读、渲染及当前输入质量检查实际执行。

## 执行身份与修改

- 执行提交：[`15dccde58ede8eb77e875f05750b47dd59328096`](https://github.com/ryoumiyahayato/image-to-cad/commit/15dccde58ede8eb77e875f05750b47dd59328096)。
- 完整 Git tree：`9b350bf805f88bd75292c51e92c384708ab1601b`；A、B、C 均在该干净工作树完成。
- 父提交：`f22b837df8a1465e09ff5cd51945c144e8af712a`；分支仍为 `exploration/issue61-stable-joint`。
- 本文是后续文档记录，不替代实际执行提交。

本次源码修改仅减少检查点投影的冗余分配：在原字典位置直接深复制筛选后的完整 objects，保持键顺序；完成投影后释放不再使用的外层 plan/adoption。完整文件集、大小、SHA、生产来源、原图参数、依赖资源、完整状态等值和历史证明校验均保留。

新增测试将旧投影与新投影**实际保存成 JSON 后逐字节比较**，并验证双向嵌套修改隔离。受影响检查点套件 **30 passed**，Ruff 与 diff check 通过。此前203项测试及协调者19项/真实矛盾行复核保持各自历史身份，不相加为本轮新测试数量。

## A：当前代码正式检查点

正式 create 与新进程完整 `verify_checkpoint` 均退出0。创建时按原 export 核验 **7495 个旧 A 成员（7488 包内＋7 旁置）**；manifest 的 `historical_export_members_verified_at_creation` 字段只计其中7488个包内成员。

- 新 packet：**7519文件＝manifest＋7518声明成员**。
- 复用证据：**7418份**；按阶段边界完整移除旧4个附着采用对象。
- 新 manifest SHA-256：`728b60fd8d81ec0fb97ee545a3dad4539c9f7d5108eade63cd4225ce998c829e`。
- 完整上游状态 canonical SHA-256：`d54aef9469bfaf2bf632062a19b0910a927812031180c1d0b0fc13bc7de02ce0`，与历史有效完整来源状态一致。
- 当前字体资源17份按记录SHA核验；历史源码、请求、环境和完整保存证明在 packet 内保留。

检查点创建后先完成 ZIP 全成员集合、CRC、SHA 及原文件未变核验并保存，再启动 B。日志不进入受完整成员校验的 checkpoint 目录。

## B 与 C：实际新文件的结果

| 实际检查 | 本轮观察到的结果 |
| --- | --- |
| 普通入口 | 退出0，完整实际导出；包内7485成员＋7个旁置导出文件 |
| 附着阶段 | `EXECUTED / CURRENT_JOINT_V3`；4条完整候选、0采用；未复用旧附着结果 |
| 独立保存冷读 | 436完整旧对象与436顶层精确保持；新增、缺失、完整改动均0；依赖错误0 |
| 完整资源保护 | 48 REVIEW、55命名块、样式、图层、线型、单位精确保持；可携字体资源记录及实际文件校验通过 |
| 实际v3计划原图冷重放 | `PASS_JOINT_V3_SOURCE_PLAN_REPLAY`；真正以 `source_graph=None` 从原 TIFF 重建；全部差异、严格变化、证书差异、原始诊断越界、作用域失败及歧义门均0 |
| 共同入口 | `PASS_ZERO_ADOPTED_PRESERVED_BASELINE`；当前阶段、来源、请求、实际导出及数值回执完整绑定；执行完成、输入未变 |
| 完整来源续算 | 独立绑定PASS：436上游对象、1483历史来源证明、1367项当前原图采样 |
| 候选来源与编辑 | 候选仍 `SOURCE_UNRESOLVED`；`combined_adoption_authorized=false`；新对象实际删移为 `NOT_APPLICABLE_ZERO_ADOPTED` |

实际保存 plan **文件字节** SHA 为 `39fa95ca6aac092cbe7bd2d7590770091dcf146e61ef05fb601b7cfdf6025401`；其 canonical 摘要为 `317264af491f67e89463e8ea5addaa453d4475a4a51ff77a05ae168320b95184`，两者口径不同，均由执行回执明确记录。

数值回执仍是 `CERTIFIED_DIAGNOSTICS_ONLY`。数值通过不能授权原墨，也不能替代实际保存内容检查；共同入口没有把生产者 PASS 当作独立来源结论。

## fresh 失败继续保留

新普通文件的原始 `cold_audit.json` 继续为 **`source_gate_pass=false`，26条来源检查失败；66条重复记录中49条未在 fresh 审核认证**。本次 fresh 原件 SHA-256 为：

`bb627d7f3c74507e5681c0a220c156a08bac65c7f6be1952cb616ed93bb0f22e`

独立的 `SOURCE_CHECKPOINT_PROOF_CONTINUATION` 使用完整旧证明、当前保存成员、原始证据和当前原图采样，认证实际66条同一owner重复，未证明／跨owner重复为0，得到有效来源门通过。共同入口也检查了该全量匹配。**fresh 文件未改写；这一续算通过不声称无缓存上游重算漂移已修复。**

首次失败草稿、原 #59 的430完整保持/5旧ID缺失/5意外新增/1门成员变化，以及旧87项数值诊断的严格失败仍保留。协调者补完的首次草稿局部诊断继续绑定其原始材料；本轮没有为凑数量再次执行它。历史 #59/A440 小回执已按原输入SHA和6个未变审核模块复核可复用，不重标为新普通图结果。

## 资源与可恢复材料

先逐项校验并释放可恢复重复副本，再串行运行。清理保存了完整回执，所有唯一文件、原图、有效基线和保留归档均保持。旧 exit137 的具体机制仍未由本次成功推定。

| 步骤 | 监控时长 | 采样峰值进程树RSS |
| --- | ---: | ---: |
| A正式创建 | 42.014秒 | 734826496 B |
| A独立完整验证 | 20.007秒 | 751312896 B |
| B普通出图与完整导出 | 546.006秒 | 2009694208 B |
| C独立保存比较 | 2.007秒 | 56164352 B |
| C原图数值重放 | 35.008秒（核心32.820秒） | 598376448 B |
| C共同验收 | 43.035秒 | 1078726656 B |

A、B、C各自归档后均完成完整成员集/CRC/SHA/输入未变核验，并在后续长运行前保存。私人扫描、OCR、字体和源坐标没有加入公开仓库。

| 私有材料 | 文件数（含包内清单） | 字节 | SHA-256 |
| --- | ---: | ---: | --- |
| `ISSUE61_CHECKPOINT_A_15dccde_20261127.zip` | 7561 | 140962095 | `659547595763bfd7091ac3c5fae4edd3256cdab9a20b455526e1148cafd68224` |
| `ISSUE61_ORDINARY_B_15dccde_20261127.zip` | 22526 | 365165734 | `0b04220a41670eee20919c430c2cccb19fb6cad3c06a601494367bd173608acd` |
| `ISSUE61_ACCEPTANCE_C_15dccde_20261127.zip` | 45 | 6957718 | `a0b3d6620b8ade8b97bbc8d79ff55dcb9bf0a41530dd76b6fdee272952fe771d` |

关键共同验收原始回执 `COMMON_ACCEPTANCE.json`：9820379 B，SHA-256 `ca26740e15a4da5cbdfcd83a237eecf56704b2791bf2b4a1d24608a2c4549ba3`。实际数值冷重放结果 SHA-256 `d178c54a6993588847a91c198eecc4528592be72483dc712662f8939424577ef`；其执行回执 SHA-256 `03f1f372d1a1df42bbb5e3d98eb2151e57b65f60383feb16b7b5cefdd5093d50`。

## 尚未完成与后续边界

1. 四条候选的完整独立原墨责任继续由 #63 按冻结接口接续；不能将本轮零采用保护通过当作四笔补全。
2. 无缓存上游重新拟合的历史原生几何／ID漂移仍未宣称修复；本轮使用显式、完整、经验证的来源阶段续算。
3. 本轮 GUI、Windows实际EXE、工程师修图工时均 `NOT_RUN`，产品仍 `LOCAL_NO_GO`；工程比例仍未验证。
4. 本分支没有自行合 main，没有集成 #63 未冻结接口。当前观察到 main 为 `a2aec1596e82b3a92c7b76f89e9e46e068029e90`；执行方法提交查询到0个远端Actions运行，不宣称远端CI通过。
5. 由协调者基于本轮实际输出、A/B/C材料与 #63 最终冻结结果安排同树整合及后续GUI/Windows验证。
