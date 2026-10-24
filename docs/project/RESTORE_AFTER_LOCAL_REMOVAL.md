# 本地删除后的恢复边界

用户在 2026-10-24 报告已删除本地相关程序，`D:/programs` 位置仍可使用。
本次未访问该 Windows 机器，不能断言旧工作区、完整 ZIP 或 `Image-to-CAD-baseline-backups` 仍存在。

## 可确定恢复的部分

- 当前公开代码、文档、跟踪的测试材料：克隆 main。
- 旧远端分支的提交历史：`archive/20261024/<原分支名>` 标签及其祖先。
- 本次 B 的原始私有结果：使用已经交付的私有 Library ZIP；它不是 GitHub 的组成部分。
- 先前研究数据/检查点：按已存在的私人网盘各阶段归档定向恢复，先核对清单，不下载整套分卷。

## 不得假定可恢复的部分

先前 570,588 字节技术包只含公开源码增量 bundle、未晋级活动/P20-D 模块及恢复元数据。
它不包含完整真实资料、详细报告、私人评审、真实输入与预测、全部模型或环境。
本地唯一且未上传的文件若也被删除，当前没有足够证据保证可以找回。不要把旧“本地备份已完成”记录当作备份今天仍存在的证明。

## 恢复到原目录布局

确认目标子目录不存在或为空后，在 Windows PowerShell 执行：

```powershell
Set-Location D:\programs
New-Item -ItemType Directory -Force Image-to-CAD | Out-Null
Set-Location Image-to-CAD
git clone https://github.com/ryoumiyahayato/image-to-cad.git image-to-cad
Set-Location image-to-cad
git log -1 --oneline
git fetch --tags origin
```

已有非空目录时不覆盖，不 `reset --hard`、不 `clean`。
新工具使用独立 `.venv-native`，见 `tools/native_first/README_ZH.md`；旧 GUI 环境按 `cad_photo_to_dxf/requirements.txt` 重建。
这些是恢复命令，不是已在用户机器完成的恢复。

## 取回旧分支

先查 `BRANCH_ARCHIVE_20261024.json` 的确切标签与 SHA，再在新的工作树中检出：

```powershell
git worktree add --detach ..\restored-old "archive/20261024/fix/non-destructive-editable-text"
```

不要把旧工作树覆盖到 main，不把未晋级候选自动投入运行。归档标签本身不证明其代码优于当前 main。
API 密钥只从用户本机环境变量读取；不要在 GitHub、聊天、归档或诊断日志中发布密钥。
