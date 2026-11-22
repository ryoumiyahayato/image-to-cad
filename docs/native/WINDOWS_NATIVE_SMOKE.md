# Windows 开发包的原生转换检查

本检查只验证同版本打包程序能运行当前原生流程；生成的小测试图不代表真实工程图精度通过。产品保持 `0.3.0-dev / LOCAL_NO_GO`。

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

## 2026-11-22 原子发布失败与验证边界

后续文档提交 `b082905b357b5cdce7af09dbddb58d539d788b8f` 的 [Windows run 45001918716](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45001918716) 实际失败：回归、构建和源码转换已通过，打包 EXE 也已生成并冷审其 staging DXF（5 LINE＋1 TEXT、0 错误／0 修补、来源门通过），但该提交 `native_worker.py` 的 `os.rename(staging, published)` 返回 `PermissionError [WinError 5]`。CLI 退出 2，结果保留在 staging、没有发布；**不能把这一运行登记为 PASS**。

实际包内 60 个应用源码哈希和 11 个安装依赖版本均与已成功的 `2adc3ee` 包一致。具体持锁者仍未知；不能把并发目录扫描的可能性当成已经证实的原因，也不能以新一次运行成功覆盖原失败。[原始失败证据](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45001918716/artifacts/14746736237) 为 3,067,664 字节，SHA-256 `9612d4f43fdce6943cb7de61b5fb6fdd3c5b74db43834a55ec0cd3b0858683e9`。原主 DXF 和已取得开发安装器的实际成功来源仍绑定 `2adc3ee`。

本次发布修复的范围限定为 Windows 的 `winerror` 5／32／33：以 50ms 短步、最多 2 秒且不超过原任务 wall 预算，重试同一个原子 `os.rename`；每次检查取消／资源停止，目标已存在（包括断链符号链接）立即失败。不得复制或覆盖目标、重跑识别，或放宽来源与冷审。其验收须包含 Windows 真实持句柄导致 rename 失败、释放后成功的回归，以及实际打包 EXE 的普通原生转换；Linux 模拟或源码测试不能替代该 Windows 执行证据，新修复结论按其实际提交与 CI 单独记录。
