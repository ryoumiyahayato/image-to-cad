# 云端源码同步记录｜2026-11-16

## 本次同步的来源

- GitHub 旧默认分支入口：`81f364fbe4eee1df00dadefabaef0d1a72993e6e`（2026-10-25）。
- 私有工作集：`c8f31bbaa4ebbf9c41256b6d302d21e67b8b3ec0` 导出快照，逐序应用 online-r2 至 online-r12 代码补丁。
- 用户实际本地已接入 r12 的提交：`92b71cf62902668f14d56b1d8447782a672e7962`。这条本地 Git 提交**没有被冒充为本远程提交的祖先**；本次为源码内容同步提交。
- online-r13 开放笔段候选仍等待真实 LibreCAD 验收，**不在本次 GitHub 同步范围**。

## 同步范围和边界

与旧 GitHub 版比较，只更新 `cad_photo_to_dxf/app/`、相关 `cad_photo_to_dxf/tests/`、`cad_photo_to_dxf/main.py`、`cad_photo_to_dxf/requirements.txt` 和 `experiments/goal27_28/` 中实际发生变化的 UTF-8 代码或测试材料，共 132 项。文件级 Git Blob SHA 与重建源码清单逐项匹配。

其他 GitHub 文件与先前项目文档保留，不把本地研究工作树的临时报告、旧照片、私有扫描素材或重建的实验档案直接公开。原 GitHub 中六项字体资源与原许可文件保留，未上传任何本地新字体文件。历史旧提交不删除、不强推。

## 仍然未通过的产品门槛

来源 XDATA 在外部 LibreCAD 另存时丢失；部分图层关闭状态、IMAGE flags、HATCH 表达仍会改写。独立外框在 r11 实测可编辑并保持笔宽。r12 改善文件配套和对照证据，但来源历史身份仍为 NOT_PROVEN。A2 仍有约 18,151 个未决栅格实体。完整网络、共享笔迹、复杂尺寸、陌生来源泛化、完整人工劳动量与 Windows 常规启动仍未达成最终要求。

同步 GitHub 不代表算法已产品化，不代表 r13 已验收，也不改变 `AGENTS.md`、`docs/project/PRODUCT_INTENT_AND_KNOWLEDGE_PACKS_ZH.md` 等产品约束。

## 后续做法

在线云端先完成研究、反例、整页核验，只有目标软件 GUI 行为无法在线验证时才要求本地操作。后续本地 r13 验收通过后再单独同步其源码，不覆盖此次 r12 的可追溯状态。
