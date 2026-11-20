# 检查点

## 当前：#41单一清理入口与v8.4边界

#41包含#40，按当前授权检查并正常合并；实际main和分支状态以GitHub记录及[G1收口记录](G1_CLOSEOUT_20261120.md)为准。下方“未合并/main不变”仅是当时快照。私有v8.4已完成整区域执行及GUI样例，完整内容仍LOCAL_NO_GO；G2将代码迁入持续研发分支，Q1—Q5处理质量与试用。


## 历史快照：2026-11-20清理第二阶段（当时未合并）

基底为 PR #40 `f2ad95703cf1ccb0284137bfe7fbc39b137f3217`，main 仍 `5b2a76b716a568bd6dad0a1e1e2a5f80145f0395`。7 条远端分支已删除，#38/#39 关闭且保留恢复说明；独立分支 `chore/native-object-cleanup-20261120` 删除 11 个重复/空文件，约 15.68 MiB。三条源码末端、两条 sync 分支、15 个旧归档标签与保护基线保留；全部原 SHA 与文件 blob 见 [执行账本](CLEANUP_EXECUTED_20261120.md)。没有 main 强推、历史重写、生产合并或 Release。

运行入口诚实标明保留基线，GUI 默认 DXF，开发/NO_GO 版本无法正式发布。新完整对象算法尚未接入公开入口，整体继续 LOCAL_NO_GO。实际测试以清理 Draft PR 的对应提交 CI 和随附验证记录为准，不能继承旧 CI 当作本次通过。

## 2026-11-16：PR #36 兼容主体与来源账本补充

独立兼容分支基底 `d5c0564`，六项主体提交保存至 `593b23e1330588ca67040506982147c6caf1d518`，完整来源账本补充保存至 `57719e0fd5e05164e003d20fabcfb757dbe66979`。最终支持环境 Python 3.11.18 / pytest 8.4.2：unit 1,728 PASS / 26 SKIP、未变 drafting 代码的 88 PASS 保持有效，EXACT/Ruff/mypy/compileall/卫生检查通过；296 文件运行前后相同，inventory `08197e42eedfc8c9fa85aa7f31550c0b805da72d5482f47d954f3300ff2b97aa`。实际启动为 `593b23e` 加未提交同字节补充，不误标启动提交。原 Python 3.12 / PySide6 6.11.3 的 True-ref 失败未被宣称修复。

三份旧 baseline 字节不变；15 条 contour 的有限迁移保留 55,476 个边缘原黑像素及 63 个退化 run 源格。结构身份仅保护其实际 payload，完整 LINE 来源另以 ledger 锁定，合同 SHA `48b7636501cf61e433101f61897b7d57286a722368cab13198999eee20d0aa76`，独立 15 项变异和 3 项缺字段均拒绝。八份历史报告按固定 d5c0564 提交及 SHA 恢复。详见 [兼容证据](PR36_COMPATIBILITY_20261116.md)。独立精度检查点 `210817bb43f711d9985acba992cfde66e329f137` 保留；没有新 GUI/DWG 或精度验收，线上结果以 PR #36 实际 CI 为准。

以下历史检查点原样保留。

---

2026-10-25：真实来源接入阶段 CLOSED，入口 main `e333dc4`。新增只读 `verified-source-carriers-v1`；0.1.1 原规则、引擎、报告和旧基线未改。
W02 三行同文件比较：7 PASS / 5 ABSTAIN → 7 PASS / 1 FAIL / 4 ABSTAIN；中文源核残留已可判，未修生产。既有同页“施工图”干净对照的 585 个源像素验证退出 PASS。
71 项包测试、113 项相关旧回归和 EXACT 保真检查通过；完整证据见 [本轮报告](../../tools/drafting_rules/SOURCE_ADAPTER_ZH.md)。GUI/DWG/真人净收益仍 NOT_RUN。

2026-10-25：从 main `ce89a8d` 复核原型，更新到 0.1.1。GB/T 10609.1-2008 官方 5 页公开正文已读，§3.1 登记正式依据候选；字体标准仅核实官方元数据。
修正表线 OCS/WCS 误判；同一镜像 DXF 由旧版 6 PASS 变为新版 5 PASS / 1 FAIL；非世界 XY 平面弃判。
49 项包测试、113 项相关旧回归、EXACT 保真检查通过。W02 真实单元格仍 7 PASS / 5 ABSTAIN；未接生产、未训练、未进行真人 CAD UAT。

2026-10-25：首个独立制图规则包 `cn-sheet-text-table@0.1.0`。基础 main `900511b5a884421bc372a39fc7f59ded18639ac9`；不改生产链。
真实 W02 双语单元格已运行：3 TEXT，正常编辑 7 PASS / 5 ABSTAIN；超长文字反例 1 FAIL；另加无关轮廓移位 2 FAIL。
正式条文尚未取得；国标候选不可执行。具体命令、最终测试与失败清单见 [规则包报告](../../tools/drafting_rules/REPORT_ZH.md)。

2026-10-24：SOURCE_CANDIDATE。原 main 76b4c8c，原文档检查点 8f78f13。恢复根与归属见 SOURCE_SYNC_RESULT_20261024.md。候选源码保存不表示新的产品验收。

见 [同步结果](SOURCE_SYNC_RESULT_20261024.md)。
