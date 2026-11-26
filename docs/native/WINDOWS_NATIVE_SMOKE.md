# Windows 开发包的原生转换检查

本检查只验证同版本打包程序能运行当前原生流程；生成的小测试图不代表真实工程图精度通过。产品保持 `0.3.0-dev / LOCAL_NO_GO`。

## 当前实际结果：Windows #696（2026-11-26）

[Windows #696](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45755563007) 的十组 source／实际隔离 EXE 普通入口、恢复、字体和安装／启动／卸载通过。第十组实际触发三条完整短划、两旧承接线到一条完整接收线的替换、有限末端绑定，并保护真实双线和白缝；五对象各移动／删除一次，source 与 EXE 共 **20 份实际 Windows 保存副本**已下载后冷读通过。完整交付包 **`CADPhotoToDXF-0.3.0-dev-f988424-Windows-Complete.zip`** 已实际下载：**418173918 B**，SHA-256 **`e2dece2dee14ac32e7381f41aa8ac4d98da75def600d0a633347511a9ef484b4`**；1478 个程序文件和 98 份随包 Python 源码逐字节核验，其中 80 份属于 native-build 声明资源。

主图执行提交 **`6a27c0f031f2e2d26ebdf4b485d85d7a42262ee0`**，Windows 执行提交 **`f988424b9dcf697d42fac8244acb96abce2b4fc7`**；两者完整 Git tree 均为 **`761e9a41b76120161c0ce01d61927946959467ff`**。这是相同源码树的两个提交。[PR #54](https://github.com/ryoumiyahayato/image-to-cad/pull/54) 已正常合入 main **`bb165884e16ac61a08ad46c337cb317d63445e8c`**，合并树也与该执行树相同。后续文档提交不替代出图／构建锚点。

当前 `scripts/windows_native_smoke.py` 保留前九组输入，并新增第十组短划／承接线输入。各组分别通过源码和实际 EXE 的普通 `native-objects` 入口建立新任务；初始原始观察缓存为零，不传采用候选、答案或白名单。EXE 阶段移开应用源码目录，使用干净用户资料目录、仅包含 Windows 系统目录的 PATH，实际 worker 也是随包 EXE。

第十组保存后逐对象核对三个完整 LINE 的端点、与完整独立曲线的交叉责任、两条旧接收线的撤回、一条完整有限承接 LINE 及实际曲线绑定，同时保护真实双线和圆／线白缝。五对象各做整移和整删；source 与 EXE 合计 20 份实际 Windows 保存副本已下载后重开核对，邻居、REVIEW 和图块保持。

本次还实际验证了新目录恢复、缺卷和损坏分卷、已有不同文件保护、重复执行、EXE 启动、CAD 字体准备与重启状态，以及安装／启动／卸载。所选完整便携交付、native evidence 与 CAD delivery evidence 已实际下载并按 GitHub 大小／SHA-256 核对；另两份普通 portable／installer artifact 未重复下载，安装器执行由实际 job 日志证明。

完整主图与 Windows 程序的对应、产物指纹和限制见[本批记录](LAUNDRY_CROSS_STROKES_20261126.md)；用户无需运行这些检查脚本，直接按[一页说明](WINDOWS_CAD_QUICKSTART_ZH.md)准备字体并打开结果。Windows 私有真实主图桌面 GUI 仍 NOT_RUN，既有格式和旧跨平台来源限制继续保留。

<details>
<summary>历史：2026-11-22 普通入口、资源与原子发布失败记录</summary>

> 以下“最新／本轮／实际执行范围”属于当时的单输入检查；当前十组覆盖与下载结果以上文为准。原成功与失败证据保持其执行版本。

## 历史实际结果（2026-11-22，4bf6554）


实际构建／执行提交 **`4bf6554526e9f247060a1a3a493bb4717c4c9ad5`** 的 7 项适用 CI 全部成功；[Windows run 45004687721](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45004687721) 为 **2235 passed、8 skipped**，实际 portable EXE 普通原生转换、安装器生成、安装／启动／卸载均通过。源码和实际 EXE 各保存 5 LINE＋1 TEXT `ROOM 17`，各有 2 次真实独立模型调用；下载后再次冷读，两份 DXF 均为 0 错误／0 修补，正式几何与内容相同。

最新四分之一区域主图实际执行提交是 `6225980503c3627f8f5fab3fe82eab78e10c2922`。它与 `4bf6554` 只差 Windows 测试夹具的访问常量及注释；实际包内 60 个生产源码文件已逐一对照两个提交，生产 Git 内容完全相同，Windows CRLF 检出差异另列。**这是同生产代码的两个实际执行提交，不能写为同一 Git 提交。** 本轮代码单一合入入口是 [PR #45](https://github.com/ryoumiyahayato/image-to-cad/pull/45)，最新 HEAD、适用 CI 和实际合入关系以 PR 及远端核对为准。

已取得的 [安装器 artifact 14747522700](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45004687721/artifacts/14747522700) ZIP 为 305,007,408 字节；内部实际 Setup.exe 为 **305,473,507 字节**，SHA-256 `0f969e96bef2912a55579cbe9bf27a799392c3515382cacb41a1b2cdf37022e3`。[便携包 14747258390](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45004687721/artifacts/14747258390) 为 414,850,224 字节；[实际原生证据 14747871770](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45004687721/artifacts/14747871770) 为 4,331,365 字节。证据内的实际 `native-build.json` 绑定 `4bf6554`，原生任务自身仍为 `COMPLETED_WITH_ISSUES`，小图通过不等于真实工程图质量通过。

## 实际执行范围

Windows 工作流继续运行原 legacy 转换和安装器启动检查，同时由 `scripts/windows_smoke.ps1` 调用新增的原生检查：

1. 用已经用于 native CLI 的受控生成图（矩形、独立横线、`ROOM 17`）运行同提交源码的普通 `native-objects` 入口。字符仅绘入输入图片，预期内容只在保存后检查，不传给识别器。
2. 复制已构建的完整便携包到临时目录；核对包内原生源码审核资源与当前源码的 SHA-256，记录构建提交和依赖版本。
3. 临时移走原应用源码目录，在新的用户资料目录、仅包含 Windows 系统目录的 PATH 中执行 **实际 `CADPhotoToDXF.exe`**。测试结束或失败均恢复原源码目录。
4. 两次运行均经过任务管理、独立 worker、Tesseract 原始观察、独立模型初始化、正式导出和来源冷审。检查实际保存的 **5 个 LINE 和完整可编辑 `ROOM 17` 文字**，逐实体比较源码与 EXE 的几何、文字及图块成员，拒绝只得到非空文件的假成功。
5. 核实 EXE 采用的 OCR 程序、模型及导出字体都位于复制后的包内；不继承旧观察缓存或采用白名单。

成功报告为 `native-smoke.json`；失败保留 `native-smoke-failure.json`、实际任务状态、worker 日志和已有输出。源码与 EXE 的 DXF 字节可能因生成标识不同而不同，因此比较实际内容，同时分别保存文件哈希。

## 随包资源与构建获取

构建步骤显式获取并校验资源。应用运行时不下载资源。

| 资源 | 固定来源与身份 |
| --- | --- |
| Windows Tesseract | [上游 5.5.0 发布附件](https://github.com/tesseract-ocr/tesseract/releases/tag/5.5.0)，`tesseract-ocr-w64-setup-5.5.0.20241111.exe`；21,381,872 字节；SHA-256 `f3fc4236425b690c8be756f35793f77394ee004be0a6460a440c754d892f68bc` |
| 英语数据 | [tessdata_fast 4.1.0](https://github.com/tesseract-ocr/tessdata_fast/tree/4.1.0)，4,113,088 字节；SHA-256 `7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2` |
| 字体 | 现有 `prepare_native_font.py` 的官方 DejaVu Sans 2.37 字体和原许可，保持原固定哈希 |
| 独立识别模型 | 随 RapidOCR 分发的 `PP-OCRv6_rec_small.onnx`，运行时继续验证既有 SHA-256 `6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884` |

`prepare_windows_native_runtime.py` 在确认安装包字节后使用 7-Zip 解包，不安装系统 OCR、不依赖作者机器上的已有安装。保留原运行 DLL、说明与许可，另放入固定英语数据及两份上游 Apache 2.0 许可。生成的 `native-ocr.lock.json` 逐文件记录字节数和哈希；原生入口在运行前校验随包资源。

PyInstaller 保留现有 GUI、任务管理和安装器结构，并在 `_internal` 中携带原生生产者所需的精确源码字节，供既有来源审核读取。这些审核资源随程序一起交付，不要求用户持有作者源码目录。`_internal/resources/native-build.json` 记录真实构建提交、源码哈希和构建环境实际 Python 包版本。正式失败证据不会因打包而绕过。

## 产物与判定

- `CADPhotoToDXF-Windows-Portable-<version>`：完整便携目录，内部构建清单绑定具体提交；成功构建后，即使后续检查失败也保留。
- `CADPhotoToDXF-Windows-Installer-<version>`：单个 `CADPhotoToDXF-<version>-Setup.exe` 安装器，按安装器实际构建结果独立上传，便于单独下载。开发工作流将它与便携包分开，避免组合附件超过下载渠道的 512 MiB 单文件上限。
- `Windows-native-smoke-evidence-<checkout SHA>`：实际小图、源码／EXE 输出、任务和冷读结果；检查失败也保存。另保存从实际包内复制的 `native-build.json`、`native-ocr.lock.json` 和 `product_status.generated.json`；成功报告记录这三份文件的 SHA-256，可直接冷读核验提交、资源与产品状态。
- **构建成功、EXE 原生转换成功、真实四分之一区域质量通过是三个独立结论。** 只按工作流及实际文件记录已经发生的结果，不由本说明提前登记成功。

真实图纸、受控工程资料和完整实验包不进入 Windows 自动测试或公开仓库。

## 2026-11-22 原子发布失败与验证边界（历史原件保留）

后续文档提交 `b082905b357b5cdce7af09dbddb58d539d788b8f` 的 [Windows run 45001918716](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45001918716) 实际失败：回归、构建和源码转换已通过，打包 EXE 也已生成并冷审其 staging DXF（5 LINE＋1 TEXT、0 错误／0 修补、来源门通过），但该提交 `native_worker.py` 的 `os.rename(staging, published)` 返回 `PermissionError [WinError 5]`。CLI 退出 2，结果保留在 staging、没有发布；**不能把这一运行登记为 PASS**。

实际包内 60 个应用源码哈希和 11 个安装依赖版本均与已成功的 `2adc3ee` 包一致。具体持锁者仍未知；不能把并发目录扫描的可能性当成已经证实的原因，也不能以新一次运行成功覆盖原失败。[原始失败证据](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45001918716/artifacts/14746736237) 为 3,067,664 字节，SHA-256 `9612d4f43fdce6943cb7de61b5fb6fdd3c5b74db43834a55ec0cd3b0858683e9`。原主 DXF 和已取得开发安装器的实际成功来源仍绑定 `2adc3ee`。

本次发布修复的范围限定为 Windows 的 `winerror` 5／32／33：以 50ms 短步、最多 2 秒且不超过原任务 wall 预算，重试同一个原子 `os.rename`；每次检查取消／资源停止，目标已存在（包括断链符号链接）立即失败。不得复制或覆盖目标、重跑识别，或放宽来源与冷审。其验收须包含 Windows 真实持句柄导致 rename 失败、释放后成功的回归，以及实际打包 EXE 的普通原生转换；Linux 模拟或源码测试不能替代该 Windows 执行证据，新修复结论按其实际提交与 CI 单独记录。

### 6225980 的实际夹具失败与 4bf6554 验证

`6225980` 的 [Windows run 45003368042](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45003368042) 为 **2234 passed、8 skipped、1 failed**，构建和 EXE 均未运行。真实句柄测试使用仅 `FILE_READ_ATTRIBUTES`（`0x80`）的目录句柄，没有制造实际 rename 冲突，因此 `actual_errors=[]` 触发原有非空断言。它是实际失败的测试夹具，不能记作发布重试通过或发布重试耗尽。

`4bf6554` 仅将这一测试的访问权限改为 `GENERIC_READ`（`0x80000000`）并更新注释，仍不共享 DELETE；没有修改生产代码、删除测试或放宽实际错误／重试断言。该测试只在非 win32 跳过；在本次 Windows 全套 2235 项通过中，真实 `CreateFileW` 句柄造成 `os.rename` 拒绝、释放后原子成功、`rename_attempts > 1`、原载荷完整与重试事件均通过。每个成功测试的具体错误码没有单独输出，不能补写一个未记录的 WinError 数值。

实际源码和 EXE 两次 smoke 的 `atomic_publication.rename_attempts` 均为 **1**，没有重试或耗尽事件。真实拒绝／释放／重试由专门 Windows 回归证明，不能把 EXE 本次正常发布说成再次复现并查明了历史锁。**b082905 的具体持锁者继续为 UNKNOWN。** `2adc3ee` 的原成功、`b082905` 的真实发布失败和 `6225980` 的夹具失败均保留其原日志、文件和提交绑定。

</details>
