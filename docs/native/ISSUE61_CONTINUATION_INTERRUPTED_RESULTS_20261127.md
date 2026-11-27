# Issue #61 接续结果：审核补强已保存，普通出图因执行环境中断待完成

## 本轮结论

**状态：PARTIAL_IMPLEMENTED_AND_VALIDATED / EXECUTION_ENVIRONMENT_BLOCKED。**

本轮从已公开的执行中版本 `0a12b73341c2a6df97b127508099761a8d7601da` 接续，
没有重启 #59，也没有将 #62/#63 的未决原墨模型改写为通过。

已修复两类实际可复现的审核漏检，重新执行原 #59 实际文件与历史 A440 的共同验收，
复现两项上游局部漂移，并完成相关测试。随后建立新来源检查点的进程以 **137**
退出，执行环境报告 unavailable；未产生可确认完成的新 manifest，新的普通整区
任务尚未启动，**本轮没有新的普通 DXF、没有最终联合通过、没有合并 main**。

原有效主图仍为 **436 正式对象／48 REVIEW／55 命名块**。
来源仍按 #59 的保守门执行，不借审核修复授权四笔新采用。
上一轮第一份草稿的 fresh 来源 FAIL 和拒绝发布结论继续保留。

## 源码身份

| 身份 | 值 |
| --- | --- |
| 本轮父提交 | `0a12b73341c2a6df97b127508099761a8d7601da` |
| 本地冻结提交，随后用于新检查点建立尝试 | `c22de675280428db0ad5d939f476647952f9b7c2` |
| 已公开同树方法提交 | [`9d102cfe6064cf8d68fc03099ea9ef457650fce6`](https://github.com/ryoumiyahayato/image-to-cad/commit/9d102cfe6064cf8d68fc03099ea9ef457650fce6) |
| 两者完整 Git tree | `02a93e0637ab15b06bbf718aedba000ea7f4002d` |
| 分支 | `exploration/issue61-stable-joint` |
| 本轮核对的有效 main | `a2aec1596e82b3a92c7b76f89e9e46e068029e90` |

Git 直推因当前环境没有写入凭据失败；随后经已连接的 GitHub 写入能力保存，
使用父提交租约保护分支，并读回提交和分支。GitHub Git-data 读回的 tree 与本地冻结
tree 完全一致。没有强推，没有改动 main，没有覆盖并行 #63。
本报告是后续文档记录，不作为已经运行新普通图的执行锚点。

## 一、修复了什么

### 1. 外层通过不能遮蔽实际采用分支的内层失败

两个原审核器对部分历史子证明仅检查字段存在。用真实 V2 历史冷读行构造
只改变内层字段的诊断副本后，10 个矛盾证明原先都被生产审核和独立审核接受：
包括转写或原始资料读取失败、分区重放失败、已选排版失败、必需组件排版体缺失、
实际图线来源支持失败、必要邻线证明失败、短字观察或排版失败。

修复同时进入：

- `source_proof_continuation.py`：历史完整来源续算审核。
- `independent_source_proof_binding.py`：单独实现的共同来源绑定审核。
- `test_historical_proof_children.py`：具有判别力的矛盾证明与合法替代分支测试。

修复后10个真实行派生反例均被两个审核器拒绝。原历史报告共有1494条来源检查；
按真实旧附着阶段声明移除4个旧采用对象及11条相应检查后，**1483条保留的上游
来源证明全部通过两个审核器**。用于核对的旧 cold SHA-256 为
`2b1bda3d62b8d426fcb663d05e6484f6e1bbe1e394bc9c9db832af72933b21dc`。

合法失败备选仍保留：默认排版失败后采用另一完整排版，以及一个 TEXT 失败后
采用完整 TEXT_GROUP。这没有变成“所有嵌套布尔值必须为真”，也没有重算 OCR。

### 2. 块裁剪依赖不能借不变的 INSERT 标签获得完整保护通过

实际保存的合成 DXF 中，仅改变 XCLIP 的裁剪边界，保持 INSERT 的扩展字典
handle 与块成员标签不变，原完整对象比较返回 PASS。这证明仅记录该 handle
不足以覆盖完整依赖。

`independent_saved_geometry_audit.py` 现在对未获独立验证的扩展字典明确拒绝：
覆盖正式实体、递归块成员、INSERT 属性、块定义、REVIEW 和相关命名资源。
受影响父对象标记 `UNVERIFIED_DEPENDENCY`，从“完整对象精确保留”计数排除；
编辑隔离也不能获得 PASS。这是未支持依赖的保守拒绝，**没有声称实现任意 XCLIP
或扩展字典的完整验证**。

实际有效436基线检查到的这类依赖错误为0，因此该拒绝不会把本次真实旧对象
误标为未知。直接与嵌套裁剪反例均进入测试。原误通过实物和回执保留在本地诊断中。

## 二、真实材料重新执行的结果

| 实际检查 | 本轮结果 | 结论边界 |
| --- | --- | --- |
| 原 #59 失败 DXF＋sidecar＋原 plan/adoption/export/request，经当前共同入口 | `FAIL_PROTECTED_BASELINE`；430完整旧对象保持、431顶层实体保持；5旧ID缺失、5意外新ID、1父对象完整成员变化；阶段目标0，候选4 | 不把5个替换ID当作新恢复对象；`execution_completed=true`，无异常或traceback；8个输入哈希前后相同 |
| 原 A440，经当前共同入口 | 436旧完整对象及资源保持；真实声明和保存目标均为4；历史 `A_V1` 身份保留 | 原墨仍 `SOURCE_UNRESOLVED`，联合采用授权为false；未伪造新的v3数值回执，因此总入口明确 `NOT_RUN_NUMERICAL_REPLAY` |
| 未改 `geometry.extract_lines` 的原图单阶段重放 | 302正式LINE与285预去重候选的ID和几何精确复现原#59 | 对旧A仍为2正式LINE、3候选变化；用完整#59包内实际几何进一步核对，无OCR，41.129秒 |
| 相同门anchor和前5拟合成员调用未改 `retire_door_fragments` | 精确复现原#59有限分区结果 | 保留原失败，不猜CPU/BLAS原因 |
| 旧87项诊断数值兼容，当前联合代码 | `LEGACY_DIAGNOSTIC_COMPATIBILITY_PASS`；87派生差异，严格字段/证书/原值界限错误均为0 | 原严格FAIL继续保留；不许可改变原生坐标、ID或门成员 |
| 实际历史计划原生端点单ULP改动、stroke ID改动 | 分别结构化拒绝 `NUMERIC_CONTRACT_REPLAY_REJECTED` 和 `NUMERIC_CONTRACT_UNRESOLVED` | 不让诊断数值兼容吞掉严格字段变化 |

#59共同入口实际用时10.78秒，A440共同入口8.03秒。历史A的保存保护通过
不授权四笔来源，也不为新输出继承历史编辑通过。

本轮最终合并的相关本地测试清单 **203 passed in 33.08s**；
相关 Ruff 和 `git diff --check` 通过。分代理早先的测试数有重叠，不相加。
新增 XCLIP 测试曾因测试构造时分配不同 handle 而在前置断言失败；
随后保持同一 handle、仅改变裁剪内容后通过，原测试运行记录未被改写。
这些测试不能替代尚未产生的普通新图。

本轮方法提交的 GitHub Actions 查询当时返回0个运行；**没有宣称远端 CI 通过**。

## 三、实际材料身份与恢复完成度

本轮读取并核验原 TIFF、有效基线、#59完整材料、协调复核包和#61已有V2包；
私人图纸、OCR、字体和源坐标没有加入公开仓库。

| 材料 | SHA-256 |
| --- | --- |
| 原 `A2-SG-008.tiff` | `9f6fa325deeff1839d8f6e667215770b19042df617c1f4450a1c6cb0e35cd3cd` |
| 有效436基线 DXF | `e69bfc23af89eb99c68c6ad7bae111c3796b632c80244cb1ce2a6651208c7bca` |
| 原#59失败 DXF | `cef3ce3b8f0f456c4f1cdbbbba8aeec38f80d7b82db5944192d2bf8c9812a318` |
| 历史A440 DXF | `8200b421db8f9b04ce7ae8c48dd181222c4e17c5f6e9255688dfbe140ce68864` |
| `ISSUE59_COMPLETE_EVIDENCE_0824ba6.zip`，351005415 B | `f6a24a29def1f2eaaed16a81ebb1271513601381d14aefbe9bffecb46a964e41` |
| `COORDINATOR_ISSUES59_60_REVIEW_20261127.zip`，16653027 B | `eccf559340d40c2e058d903614c874d28fa7bea287e11acb4ec69a6dca346451` |
| `ISSUE60_COMPLETE_EVIDENCE_20261127.zip`，33125333 B | `e0968470239d7056b4e255d277e871ddd2d40d3a2167896f06c2581803dca6f8` |
| `ISSUE61_SOURCE_CHECKPOINT_V2_87220a6.zip`，111495664 B | `b8ab2b87d121c111177e422a90b2e627cce12cf2ea2273911714677265864f68` |

历史 A 完整导出目录恢复后，**7495/7495声明成员逐项SHA核验通过**：
7488个native包成员和7个旁置导出文件，零缺失。已有检查点中的相同字节只读复用，
缺少的64个原始成员从完整#59包提取，未生成或改写几何。

当前runtime/resource闭包与旧V2包精确相同，上游producer闭包精确相同，
17个实际字体资源已按记录SHA核验。新审核器文件改变，因此必须新建检查点，
不能编辑旧manifest中的哈希冒充复验完成。

## 四、中断事实与不能宣布的结果

新检查点建立调用了正式 `source_stage_checkpoint create`，使用上述完整旧A
导出、原request、旧源码、环境、资源和原图。进程随后返回 **exit137**；
当时输出目录尚未有完成回执，环境接着报告 unavailable。
一次最小恢复检查也明确返回“没有可用执行环境”。

另一路首次失败草稿的原字节恢复仍在进行，未拿到恢复完成回执，
**没有执行首次草稿的 LOCAL_V2_PROOF_DIAGNOSTIC**。
旧草稿 DXF 的 `c3a8aa1d...` 是DXF哈希，不能误称cold JSON哈希。

不能仅凭137推定具体OOM机制、Python逻辑错误或模型否定。
当时工作区磁盘空间紧张，部分恢复输出被放到临时挂载；资源占用的完整测量
尚未取得，应在下一次运行前先核验持久磁盘与内存余量，并串行恢复／出图。
不要复用这个不完整新检查点。

| 尚未完成的目标 | 当前准确状态 |
| --- | --- |
| 新checkpoint建立与独立校验 | `INTERRUPTED_NO_COMPLETED_MANIFEST` |
| 首次失败草稿的V2本地诊断 | `NOT_RUN` |
| 本轮新普通整区DXF | `NOT_RUN` |
| 新普通输出的v3原图数值冷重放 | `NOT_RUN` |
| 新普通输出的共同保存/来源/436保护 | `NOT_RUN` |
| 新采用对象实际删移 | 尚无本轮采用输出；不能记作真实编辑通过 |
| CAD GUI、Windows实际EXE、工程师工时 | `NOT_RUN` |
| 本轮新增私人完整证据包 | 尚未打包保存；工作区新回执的恢复可用性待环境恢复后核验 |

本页只报告中断前已经观察到的实际结果。新原始回执没有在中断前完成私人
持久归档，不能把本页或已存在的旧ZIP称作本轮完整新证据包。

## 五、直接接续步骤

1. 从上述公开方法提交恢复同树源码；保留本页、首次失败记录和旧V2包。
2. 从#59完整包按原export逐字节恢复旧A目录，核验7495个声明成员；
   不改原文件，不从旧DXF生成新对象，不重跑OCR。
3. 核验实际存储空间与内存，给恢复、检查点、任务和输出选择足够的持久磁盘；
   串行执行，保留失败回执。
4. 用当前审核器重新创建检查点并完整验证，不补写本次中断目录：

```bash
PYTHONPATH=cad_photo_to_dxf python -m app.native_objects.source_stage_checkpoint create \
  --evidence OLD_A_EXPORT.native/evidence \
  --request OLD_A_REQUEST.json \
  --previous-source OLD_A_APPLICATION_SOURCE \
  --environment VERIFIED_ENVIRONMENT.json \
  --resources VERIFIED_RESOURCES.json \
  --historical-export OLD_A_EXPORT.export.json \
  --source ORIGINAL_SCAN.tiff \
  --output NEW_CHECKPOINT
```

5. 对首次失败草稿做明确的V2本地来源诊断，旧fresh FAIL不改写；再经普通入口：

```bash
python cad_photo_to_dxf/main.py --headless --mode native-objects \
  --input ORIGINAL_SCAN.tiff --roi X0 Y0 X1 Y1 --dpi INPUT_DPI \
  --jobs-dir NEW_JOBS --job-id NEW_JOB_ID --output NEW_OUTPUT.dxf \
  --source-stage-checkpoint NEW_CHECKPOINT/manifest.json
```

6. 按 [联合实验入口](../../experiments/issue61_joint_contract/README.md) 对实际保存计划
运行独立v3数值冷重放和共同验收，核对完整436、REVIEW、55块及资源；
零采用也要证明附着阶段实际执行和候选保留。
7. 原墨接点／宽度模型继续由#63按冻结接口提供。两路冻结后由协调者统一同树验收，
再集中处理GUI、Windows与交付；本分支不自行合main。
