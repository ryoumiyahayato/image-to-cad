# Issue #61：协调复核接收与同树整合交接（2026-11-27）

## 当前结论

已按[协调者独立复核评论](https://github.com/ryoumiyahayato/image-to-cad/issues/61#issuecomment-7221928443)取回实际复核包，完成全包身份、完整成员及关键回执核对。本批 A → B → C 按 **`PASS_ZERO_ADOPTED_PRESERVED_BASELINE`** 收口：**436 个旧完整正式对象、48 REVIEW、55 命名块及资源保持；4 候选、0 新采用。** Issue #61 保持开放，接续 #63 最终冻结后的同树整合。

普通出图与 A/B/C 的执行身份仍为 [`15dccde58ede8eb77e875f05750b47dd59328096`](https://github.com/ryoumiyahayato/image-to-cad/commit/15dccde58ede8eb77e875f05750b47dd59328096)，tree `9b350bf805f88bd75292c51e92c384708ab1601b`。作者完成报告提交 `2123f4897681efc58956d7536961f3c6a3560b55` 和本文的文档提交均不替代该执行身份。

本次新增工作是接收材料核验、实际回执对照及接口交接核查。协调者已独立运行的三个阶段保留其执行身份；本次没有将它们重记为又一次普通出图。

## 新复核材料核验

实际读取 `COORDINATOR_ISSUE61_COMPLETED_REVIEW_20261127.zip`：**11426328 B**，SHA-256：

`aaf53cc2f748b8b9b72735549759313e8650e304ac971006ba7706591cec324c`

本次逐成员读取 **72 个 ZIP 成员＝71 个声明 payload＋FILE_MANIFEST.json**。全部 CRC、声明大小、SHA-256 和完整成员集合通过；缺失、额外及重复成员均为 0。读取前后外层字节不变。包内包含实际普通 DXF、原有效基线、原 TIFF、代码检查、新进程回执和完整作者结果对照；私人内容继续保存在受控交付材料中。

| 已核对的材料 | 接收结果与范围 |
| --- | --- |
| 完整检查点新进程回执 | `PASS_FULL_CHECKPOINT_VERIFICATION`；7518 声明成员＋manifest，7418 份复用证据；完整上游投影、历史证明、环境与绑定资源进入正式验证 |
| 实际计划原图重放 | `PASS_JOINT_V3_SOURCE_PLAN_REPLAY`；`source_graph=None` 独立重建，全部差异类别为 0；结果字节与作者 `joint-replay.json` 一致 |
| 实际保存共同验收 | `PASS_ZERO_ADOPTED_PRESERVED_BASELINE`；436 完整对象和 436 顶层对象精确保持，新增／缺失／完整变化／未验证依赖均 0 |
| 当前阶段及来源续算 | `EXECUTED / CURRENT_JOINT_V3`；436 上游对象、1483 历史证明、1367 当前原图采样；4 候选、0 采用 |
| 定向代码检查 | 协调者实际 JSON 保存字节／双向隔离及五项篡改拒绝共 6/6 通过；作者原 30 项仍保留原执行身份 |

共同回执原件区分如下，均不可重新标记为另一轮执行：

| 原件 | SHA-256 |
| --- | --- |
| 作者共同回执 | `ca26740e15a4da5cbdfcd83a237eecf56704b2791bf2b4a1d24608a2c4549ba3` |
| 协调者新共同回执 | `f7bdfbcafed4ba8e90f5c7fe29edb1a57c642dfc5907492de79862c0468132ac` |
| 两轮逐字节相同的数值结果 | `d178c54a6993588847a91c198eecc4528592be72483dc712662f8939424577ef` |
| 实际普通 DXF，199885 B | `b842c72bab8ed8e579a1cc7f8f04b315c231d98c2d78ea90aed9fbc368bf87db` |
| 完整检查点 manifest | `728b60fd8d81ec0fb97ee545a3dad4539c9f7d5108eade63cd4225ce998c829e` |

本次另外将包内原件与作者本地原件实际重做对照：数值结果 731327 B 逐字节一致；协调者共同回执为 12226526 B，作者共同回执保持原 SHA。只映射明示的物理路径及 11 对实际输出回执 SHA 后，唯一剩余差异是数值重放实际耗时 `32.81951707299595 → 30.09552836399962` 秒。几何、ID、判断、证据字段和原输入哈希没有舍入或替换。本次45项材料／身份核对无失败；它们不是新算法测试或新的 A/B/C 运行。

## #63 最新接口和整合状态

本次远端快照为 [`a0f8dc73f2a457abe9edd58d741da10bc81adc90`](https://github.com/ryoumiyahayato/image-to-cad/commit/a0f8dc73f2a457abe9edd58d741da10bc81adc90)，tree `325286309bad13ea89609ed55ecf2d76f1b6597c`，分支 `experiment/issue63-bounded-source`。这是当前检查点，不是带完整实证的最终交付声明。

旧中断评论中的“组件缺失、planner 仍为 v3”已不代表该快照。当前代码及[接口说明](https://github.com/ryoumiyahayato/image-to-cad/blob/a0f8dc73f2a457abe9edd58d741da10bc81adc90/docs/native/ISSUE63_COMPLETE_BOUND_SOURCE_INTEGRATION_20261127.md)已包含：

| 接口 | 当前身份及整合要求 |
| --- | --- |
| Planner / adoption | `source-attached-stroke-graph-plan-v4-bounded-source` / `source-attached-stroke-adoption-v4-bounded-source`；额外显式绑定 `circle_source_objects` |
| 完整组件 | `source-finite-component-responsibility-v2-bounded-field`；保存审核须传入实际保存的 prior 几何，不能回退成保存前几何 |
| 独立保存 reader | `source_model="v2"`；默认 v1 保留原历史入口，生产者重放与独立原墨接受分别留证 |
| 活跃宽度家族 | 模块名保留 `bounded_stroke_field_v2.py`，实际 schema 是 `source-bounded-continuous-squared-width-field-v3-independent-knots`，不能仅凭文件名判断模型版本 |

阶段 A 已公开回报最小接点保存／另进程冷读；最新 [README](https://github.com/ryoumiyahayato/image-to-cad/blob/a0f8dc73f2a457abe9edd58d741da10bc81adc90/experiments/issue63_bounded_source/README.md)另外记录六个小型保存上下文检查。该 README 明确：真实四分之一图 source-stage 与原八探针尚须在同一冻结树串行执行，小检查不提供真实采用数。本次不把这些作者进展记录写成本轮独立复跑。

依据 [#63 最新协调同步](https://github.com/ryoumiyahayato/image-to-cad/issues/63#issuecomment-7221946982)，同树整合接收条件为：

1. #63 回传确切最终 commit/tree、与 `15dccde` 的 planner／adoption／reader／数值重放／保存入口对照及需要共同整合的补丁。
2. 同一版本的新模型能力／拒绝边界、原八探针、真实组件 source-stage 和实际保存独立审核均交实际回执；候选、实际采用、未决及未执行逐项区分。
3. 新共享顶点、宽度场、有限端口和圆的 exact 证据按新合同严格复核，不加入旧 87 项派生诊断兼容白名单。
4. 相关 producer、validator、依赖或 schema 改变后，按正式检查点身份／失效规则建立并验证对应检查点；旧 manifest 和 PASS 不转授新树。
5. 在最终同一源码树重新运行普通出图及实际保存共同验收，严格保护全部旧对象和资源。实际有新采用才执行其独立整删、整移和新进程冷读。

### 当前审核器的具体适配点

已直接检查 `15dccde` 对应的代码：[`independent_stage_binding.py`](https://github.com/ryoumiyahayato/image-to-cad/blob/15dccde58ede8eb77e875f05750b47dd59328096/cad_photo_to_dxf/app/native_objects/independent_stage_binding.py) 的 `CURRENT_JOINT_V3` 分支要求 producer 集合恰为 graph、ink、contacts、numeric 四个模块；[`source_proof_continuation.py`](https://github.com/ryoumiyahayato/image-to-cad/blob/15dccde58ede8eb77e875f05750b47dd59328096/cad_photo_to_dxf/app/native_objects/source_proof_continuation.py) 同时固定 v3 adoption schema 和对应额外 producer 集合。新组件声明必须与 plan、adoption、stage receipt、独立 checker 和来源续算审核器共同适配。

[`source_stage_checkpoint.py`](https://github.com/ryoumiyahayato/image-to-cad/blob/15dccde58ede8eb77e875f05750b47dd59328096/cad_photo_to_dxf/app/native_objects/source_stage_checkpoint.py) 的 `producer_closure()` 只遍历历史 producer 清单及指定补充文件，不会自动发现所有新增模块。因此不能把“旧包验证器没有看见新模块”解释为新合同兼容。`verify_checkpoint()` 另行严格绑定 validator、完整 executor 文件和 proof reviewer；reviewer 字节变更会触发 `SOURCE_STAGE_PROOF_REVIEWER_CHANGED`，即使 pipeline 上游 AST 不变，完整 executor 字节变化仍会使旧包失效。

若仅下游执行／审核绑定变化且可复用上游闭包严格一致，可从原完整证据调用正式 `build_checkpoint()` 制备新目录，再完整验证和捕获；不得只替换旧 manifest 中的 SHA。若复用上游 producer 或其 AST 已变，重新封包也会被拒绝，需要相应的新上游状态与证明或明确的新兼容合同。最终可复用性由最终树上的正式验证决定。

## 保留的失败与边界

原 fresh 回执仍 `source_gate_pass=false`，26 条失败，66 条重复记录中 49 条在 fresh 路径未认证；独立来源续算确认全部 66 条为同 owner，未证明／跨 owner 为 0。fresh 原件未改，无缓存重新拟合漂移没有被宣称修复。

四候选仍 `SOURCE_UNRESOLVED`，独立完整原墨模型审核为 `NOT_RUN_PENDING_PARTNER_CONTRACT`，新对象编辑为 `NOT_APPLICABLE_ZERO_ADOPTED`。数值结论仍 `CERTIFIED_DIAGNOSTICS_ONLY`。GUI、Windows 实际 EXE、工程师 UAT 均 `NOT_RUN`，产品 `LOCAL_NO_GO`。

本次仅更新 #61 的接收与交接文档，保留原实验分支。main 观察值仍 `a2aec1596e82b3a92c7b76f89e9e46e068029e90`；未整合 #63 开发中快照，未合 main。实际出图与详细材料仍见[原完成结果](ISSUE61_CONTINUATION_COMPLETED_RESULTS_20261127.md)。
