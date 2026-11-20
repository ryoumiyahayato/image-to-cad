# Changelog

以实际合并到 `main` 的代码和发布工件为准。私有研究实验、草稿 PR 和文档重整不等于正式功能发布。

## Unreleased — 2026-11-20（维护收口，不是产品发布）

- G1以#41作为包含#40的单一合并入口；执行协议遵循当前授权，清理复核区分历史快照与当前可恢复性，main正常前进不报成资料损毁。
- 私有v8.4整区域产物和未通过事项按版本单列；R1/R2不重复执行，持续研发迁入及Q1—Q5成为当前任务。
- 第二阶段已实际删除 7 条远端冗余分支并关闭 #38/#39；清理提交移除 11 个重复/空文件，保留原 SHA、祖先关系及恢复清单。当时main和旧归档标签不变；当前main允许经正常PR前进。
- 入口、报告和默认构建明确 LOCAL_NO_GO；GUI 默认 DXF，开发/NO_GO 版本禁止正式 Release。没有迁入尚未审查的私有原生对象算法。
- 新设 [原生可编辑 CAD 对象重建产品契约](docs/project/NATIVE_OBJECT_PRODUCT_BASELINE_20261120.md)，明确完整对象重建、来源追溯和真实编辑的优先级。
- 更新 README、AGENTS、PROJECT_STATUS、CURRENT_TASK、NEXT_TASK 及验收说明；旧产品意图文档标记为历史备忘录。
- 新增 [分支与过时内容清理审计](docs/project/BRANCH_AND_CONTENT_CLEANUP_20261120.md)；保留执行前快照，实际删除另由执行账本及G1记录证明。
- **没有将最近私有原生对象实验源码合并进 main，也没有新增 Windows EXE、APK、DWG 或正式 Release。** 整体产品质量仍 LOCAL_NO_GO。

## 已有历史记录

- 2026-11-16：PR #36、#37 已合并；与原生对象实验无关的兼容与 Qt 检查通过，实际 CI 和运行边界以对应 PR 为准。
- 2026-10-24：PR #35 合入早期历史研究和 Windows 产品基准，详情见 [PROJECT_STATUS.md](docs/project/PROJECT_STATUS.md) 的历史部分。

正式版本发布后再将实际合入、经过真实测试的功能写入已发布版本章节。
