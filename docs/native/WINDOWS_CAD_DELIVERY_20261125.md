# Windows 字体准备与程序恢复交付（2026-11-25）

本轮只改交付和使用链，不新增识别对象，不重新 OCR。继续使用 `QUARTER_shortcodes_2fd4373.dxf`、既有 6 条新增完整 TEXT 和 423 个正式对象；主图原件字节保持。

## 用户入口

应用启动页与文件菜单都有“打开已有 DXF / 准备 CAD 字体…”。用户选择真实结果，软件检查实际使用样式及完整字符，查找 LibreCAD；找不到时可直接选择 `LibreCAD.exe`。准备、重新检查和在 CAD 中打开共用一个服务，界面工作线程不阻塞主窗口。

状态分别为未准备、已准备可打开、需要重新打开 CAD、准备失败。复制完成不声称运行中的 CAD 已加载字体；先启动的 CAD 进程必须退出后重开。资源身份、路径、版本探测及失败详情写入轮转日志。

## 固定目标与资源

目标固定为 **LibreCAD 2.2.1.6**，官方源码提交 `29179cdc09fbec439a1cb0931d92e67f4c0f6622`。

- `rs_system.cpp` 的 `getDirectoryList` 在 Windows 首先使用 Qt `DocumentsLocation/librecad/fonts`，包含系统文档目录重定向；配置中的 `/Paths/Fonts` 是追加路径。应用使用前者，不修改 CAD 配置。
- `rs_fontlist.cpp`、`rs_font.cpp` 按 LFF/CXF 基名解析并缓存字体。不存在时回退 standard，因此只确认 TTF 在磁盘上不能保证正确显示。
- `rs_filterdxfrw.cpp` 的 `writeTextstyles` 在普通保存时把样式名同时写入 `STYLE.name` 和 `STYLE.font`。应用已接受两个明确的保存别名，继续执行原字体、许可、LFF 和字符覆盖校验，保证用户编辑副本可从相同入口重新检查。

来源、版本、许可和 SHA 随资源绑定。已有其他字体和设置不被覆盖；同名不同资源先拒绝，匹配资源重复执行不改 mtime。主图结果包同时附带固定 TTF、source-row LFF 和主图对应的预生成 native LFF，准备过程无需下载字体。

普通 DejaVu 字形转为 LibreCAD LFF 保留原轮廓，但 LFF 的全局字距不能保留所有 TrueType 字距。真实主图展开的 50 条正式文字检查未新增邻接接触；LAUNDRY 宽度较固定 TTF 增加约 0.3344 mm，2LP-6,8 约 0.1008 mm，近 F 圆的来源行字体几何一致。不得把这项记录写成任意文字排版完全相同。

## 恢复入口

完整 ZIP 直接解压启动。分卷使用同版 `Restore-Windows-portable.cmd`，自动核对每卷、合并后总大小/SHA、全部 ZIP 成员、解压及 EXE 启动。只对子 PowerShell 进程使用执行参数，不永久修改系统执行策略。

缺卷、坏卷、已有不同 ZIP 或不同程序目录时停止并保留原件。先校验全部输入，再在自己的临时路径生成，完成后发布；重复同版恢复保留用户额外文件。恢复清单和包内 `native-build.json` 共同绑定源码提交、版本与 EXE。

## 实际验证分类

本地字体/界面/恢复相关 53 项测试通过，使用真实固定字体。真实主图的 6 条新增 TEXT 各改成 TEST-A7,03 和整条删除，另有一次无编辑保存；13 份输出由新 Python 进程冷读。每次编辑其余 470 个模型空间实体、47 个命名 BLOCK、样式及登记独立邻居精确保持。原主图 SHA 保持 `03230595b5d26d2a1796d110e4b73337961389d0e44e363695aea7d988d309c1`。

Windows 真实主图 GUI 为 **NOT_RUN**。本会话仅提供 Linux/Xfce 桌面控制；现有 Windows 环境是可执行进程和文件检查的 CI runner，没有交互桌面控制入口。公开 workflow 只使用受控输入，不上传私人主图。Windows 进程启动、LibreCAD dxf2pdf、ezdxf 改字文件检查、Linux GUI 和 Qt offscreen 均不得替代 Windows 主图人工改字/删除/普通保存/退出重开。

既有 XDATA、INSERT zscale=0、LibreCAD 目标字高/宽度舍入与其他严格保存限制继续 LIMITED。编辑后的 TEST-A7,03 不继承原扫描文字来源批准。历史 strict-three 和跨平台来源重放失败继续保留；产品仍 0.3.0-dev / LOCAL_NO_GO，工程师工时 NOT_RUN。

## 本轮保留的失败

Windows #686 / `62d604c` 在新恢复检查的坏分卷负例失败：子 Windows PowerShell 无 Get-FileHash，导致 UNEXPECTED_ERROR。原件保护保持；该次尚未执行正向恢复和字体服务。后续修复使用 .NET SHA256 流式读取，保持原大小、SHA 和冲突保护，不删除负例，也不把旧失败改为通过。

## 已验证的构建与下载版本

代码提交 `943c72115c32cce3e1d65d8e6a80529a9c1a64c4` 已经 [PR #50](https://github.com/ryoumiyahayato/image-to-cad/pull/50) 正常合入 main，合并提交 `97c0fb2b6d6c5c25a62df017d4c7e7d37cb712f1`；合并整树与构建源码整树相同，tree `6480cc45858336015792f214710c64fec9cf5015`。后续交付文档提交不改变该 EXE 的实际构建锚点。

[Windows #687 / run 45556214597](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45556214597) 全部成功：3102 passed / 8 skipped / 1 warning；便携程序、安装器安装/启动/卸载、实际恢复与字体服务检查通过。其他五项适用 workflow 同样成功。

| 实际文件 | 身份 |
| --- | --- |
| 完整便携 ZIP | `CADPhotoToDXF-0.3.0-dev-943c72115c32-Windows-portable.zip`，417683910 B |
| ZIP SHA-256 | `640b95587646858e3d390aebb64d0fa128b1ec5d5652d2cc12c5617097b93326` |
| 恢复后 EXE SHA-256 | `0a2c26973159a01147b222034e6832731da099c64d520f8286878a5b832f5869` |
| 恢复逐文件检查 | 1473 个程序文件，实际新 Windows 目录执行 CMD、解压和 EXE 启动 PASS |
| 字体初始条件 | 本轮两种字体未准备，另有无关字体和设置保护标记 |
| 字体实际状态链 | NOT_PREPARED → 运行中准备 REOPEN_REQUIRED → 退出后 PREPARED → 请求打开成功 |
| 恢复反例 | 缺卷、坏卷、已有不同 ZIP、已有不同程序文件均正确拒绝且原件保持；重复执行保留额外用户文件 |
| 实际下载 | GitHub 精确验证包下载后大小/SHA/内部 CRC/EXE 与构建元数据通过；最终完整程序下载入口又在新目录取回，ZIP 字节与 Windows 实测包精确一致 |

Windows 受控实际输出 `PX-17,29` 与文件级改字 `TEST-A7,03` 的 LibreCAD 输出完整可读。独立字体 probe 使用默认线宽，PDF 笔段过细，PNG 几乎不可见；其前后路径数量和哈希变化只能证明渲染变化，不能单独作为视觉验收。这一限制不影响已经实测的资源准备/恢复状态结论，也不取代仍未验的真实主图 Windows GUI。

完整程序包已成功交付，不必下载分卷。已验证的恢复脚本及清单仍随验收/恢复资料保留，分卷边界和 SHA 仍与 Windows #687 的实跑回执对应。

## 官方依据

- https://github.com/LibreCAD/LibreCAD/blob/29179cdc09fbec439a1cb0931d92e67f4c0f6622/librecad/src/lib/engine/rs_system.cpp
- https://github.com/LibreCAD/LibreCAD/blob/29179cdc09fbec439a1cb0931d92e67f4c0f6622/librecad/src/lib/engine/rs_fontlist.cpp
- https://github.com/LibreCAD/LibreCAD/blob/29179cdc09fbec439a1cb0931d92e67f4c0f6622/librecad/src/lib/engine/rs_font.cpp
- https://github.com/LibreCAD/LibreCAD/blob/29179cdc09fbec439a1cb0931d92e67f4c0f6622/librecad/src/lib/filters/rs_filterdxfrw.cpp

用户步骤见 [Windows 一页说明](WINDOWS_CAD_QUICKSTART_ZH.md)。程序构建、主线集成及下载包身份见本次交付 VERSION_MAP 和 Windows 原始回执；图纸生成版本保持 2fd4373。
