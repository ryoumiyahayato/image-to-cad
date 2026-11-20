# GitHub 分支与内容清理审计（2026-11-20）

> **第二阶段已执行，原审计正文保留。** 7 条远端冗余分支已删除，#38/#39 已关闭；11 个可证明冗余的 tracked 文件由独立清理提交移除。实际前后列表、完整 SHA、恢复位置和保留理由见 [CLEANUP_EXECUTED_20261120.md](CLEANUP_EXECUTED_20261120.md)。下面“未删除／待执行”描述属于执行前快照，不应再次当作当前远端状态。

> 审计基点：公开仓库 `ryoumiyahayato/image-to-cad`，远端 `main=5b2a76b716a568bd6dad0a1e1e2a5f80145f0395`。本文件是**可执行清理清单与条件**，不意味着已删除远端分支。清理前必须重新读取远端 HEAD，并确认开放 PR、保护分支/标签与唯一资产。
>
> 目标：活动仓库只保留正式 main、正在审核的少数功能分支和明确仍有价值的研发分支。历史源码、失败、回归和恢复锚点要有受保护引用，但不应当让十余条祖先分支长期冒充当前设计。

## 1. 已核对的提交继承关系

按 GitHub 比较结果：

- `integration/compound-source-with-main-20261116` → `accuracy/explicit-source-region-adapter-20261117` → `accuracy/shared-core-directional-tracks-20261117`，依次多 9 / 10 / 11 个相对 main 的提交，后者包含前者提交。PR #38、#39 分别处于 Draft/open，且修改范围重叠。末端分支仍**不是**通过验收的产品代码。
- `accuracy/compound-source-partitions-20261116` 是 `accuracy/native-grid-compound-parts-20261116` 的祖先，后者另有4个提交。
- `delivery/w02-member-lifecycle-rebuilt` → `delivery/w02-glyph-source-boundary` → `delivery/w02-weak-edge-source` → `delivery/w02-librecad-handoff`，后一分支持续包含前一分支提交。末端相对 main 仍多4个独有提交，不能无备份清理整条链。
- `fix/py312-singleton-validation-20261116` 相对 main 为 ahead 0 / behind 1，代码已无独有提交；关联 PR #37 已合并。
- `sync/verified-online-r12-20261116` 相对 main ahead 3 / behind 3；`sync/20261116-recovered-progress` ahead 1 / behind 26（含历史 git bundle），两者都还含独有提交或恢复引用，不能按名字删除。

## 2. 按优先级处理

| 类别 | 分支/文件 | 处理 |
| --- | --- | --- |
| **可优先删除** | `fix/py312-singleton-validation-20261116` | 重新核实 ahead=0、无开放 PR 或保护依赖后，删除远端分支；已合并内容由 main 保存 |
| **保留末端后删祖先** | `accuracy/compound-source-partitions-20261116` | 先保证 `accuracy/native-grid-compound-parts-20261116` 的末端受可恢复引用保护；确认无独立外部引用后删祖先 |
| **一条链压缩到一个恢复点** | `integration/compound-source-with-main-20261116`, `accuracy/explicit-source-region-adapter-20261117` | 先核对 #38/#39 并保存提交/补丁，保留 `accuracy/shared-core-directional-tracks-20261117` 的恢复引用，再关闭或更新过时 PR，删除冗余祖先分支 |
| **一条链压缩到一个恢复点** | 三个 `delivery/w02-*` 祖先分支 | 保存/评审末端 `delivery/w02-librecad-handoff` 的独有内容后删除祖先；末端是否也退出活动分支需先确定其代码已经迁移或有不可变存档 |
| **先核对唯一资产** | `accuracy/native-grid-compound-parts-20261116`, `accuracy/shared-core-directional-tracks-20261117`, `delivery/w02-librecad-handoff` | 审计可复用算法、已有回归、关联 PR、最近公开主线变化；不直接合 main；可转不可变归档引用并退出活动分支 |
| **暂不删除** | 两个 `sync/*` 分支 | 特别核对独有的协议/来源报告、恢复 bundle 和是否已有异地存档；未核对前不删 |
| **绝对保留** | `main`、受保护发布标签、合法必要的回归基线与恢复锚点 | 不做强推、不重写历史或清理有唯一副本的真实数据 |

**清理 PR：** PR #38 与 #39 是开放 Draft，不要先无条件 Merge。核对末端代码内容及适用验收后，若已被新的研发路线替代，附明原因和保留证据再关闭；若仍有可用通用基础设施，提取到新的原生对象功能 PR。关闭 PR 与删除头分支分别操作。

## 3. 文件与旧设计清理

按「现行规范 / 可复用实现 / 历史证据 / 可再生垃圾」分类实际文件。

- **覆盖现行设计：** 根 README、AGENTS、PRODUCT_INTENT、PROJECT_STATUS、CURRENT_TASK、NEXT_TASK 与验收说明统一指向 `NATIVE_OBJECT_PRODUCT_BASELINE_20261120.md`。旧设计与新目标冲突时不得继续控制默认流程；旧规范不必要的副本可以删除，有唯一审计价值的保留归档并标记 SUPERSEDED。
- **删真正的垃圾：** 已追踪的 `__pycache__`、构建临时目录、冗余生成截图/日志、导出 DXF、无唯一证据价值的过时输出、重复的实验包；先用 `git ls-files` 查是否真的被追踪，使用 `git rm` 删除并验证工程引用。
- **不得误删：** 测试 fixture、可合法分发的资源、关键失败反例、原始证据哈希、受保护 phase12 基线、不可替代的历史恢复对象。用私有存档承担大体积原始图纸和模型，公开仓库只放代码及能公开的脱敏合规材料。
- **先删引用再删文件：** 全仓搜索文档链接、导入路径、CI、脚本、GitHub Actions、用户入口；依赖关系未清楚时不得仅凭文件名旧就删除。
- **不要重写整个 Git 历史来省空间：** 日常移除文件只影响新提交；如果以后要消除历史中的大对象，需要另立历史迁移任务并核对 fork、标签、归档、PR、供应链风险，绝不顺手 `push --force`。

## 4. 有条件执行远端清理

推荐使用具有足够权限的正常 Git 客户端，单条执行而非批量盲删：

```bash
git fetch --all --prune --tags
git log --oneline origin/main..origin/fix/py312-singleton-validation-20261116
# 预期无输出；还需查 branch protection / PR refs
git push origin --delete fix/py312-singleton-validation-20261116
```

对祖先分支，先用 `git merge-base --is-ancestor origin/<ancestor> origin/<survivor>` 核对；写入不可变的归档 ref/tag 或已验证 bundle，并确认远端能读回，再执行 `git push origin --delete <ancestor>`。标签名应留存原 HEAD、日期和原分支名。不能只因比较接口报告 ahead=0 就在没有检查保护条件时删除。

## 5. 清理完成的定义

1. README 与当前任务都表达新的、唯一的产品目标，不再把 HATCH 分区/像素覆盖包装成主研发路线。
2. 活动分支只保留有明确 owner、下一步验收与正在审查的代码；过期 Draft PR 已作合乎证据的关闭/替换。
3. 每条被删分支均有执行前 SHA、为什么无独有内容或如何存档、实际删除日志、删除后核查。
4. 每个被删文件均列名、引用影响、对应合规历史存放位置或可再生理由。
5. `main` 旧回归和依赖仍通过，秘密、私人扫描来源和无许可二进制没有新泄露；主线生产能力不凭文档更新自动晋级。

## 6. 工作边界

本文件不宣布任何远端分支已经删除。仓库 API 权限支持创建文档变更和 PR，但当前操作入口未提供分支删除动作；实际删除需使用经过认证且授权的 git 客户端或 GitHub 管理界面并记录结果。
