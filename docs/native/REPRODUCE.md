# 从 Git 提交运行原生重建

当前正式入口默认使用 **`native-objects`**。CLI 与 GUI 都经
`NativeJobManager → main.py --native-worker → ProductionProcessingService.process_native_objects`
进入实际源码。候选保存、来源审核和发布目录检查完成后才导出 DXF。
这证明入口接通，不等于完整内容、目标 CAD 或工程师省时验收通过；产品保持
`0.3.0-dev / LOCAL_NO_GO`。

## 1. 检出明确提交并建立独立环境

在目标研发 PR 中选定实际提交，正常检出后记录 `git rev-parse HEAD`。
不要把作者的旧目录、旧虚拟环境、旧采用名单或实验 ZIP 当作运行前提。

```bash
git switch --detach <SOURCE_COMMIT>
git status --short
python3.12 -m venv .venv-native
.venv-native/bin/python -m pip install -r cad_photo_to_dxf/requirements-native.lock
.venv-native/bin/python -m pip check
```

原生锁定环境为 **CPython 3.12.14、Linux x86_64**；锁文件包含 11 项直接依赖的
32 项运行依赖闭包，未冻结开发机上的其他包，也不启用 `--system-site-packages`。
`requirements-native.txt` 只转引同一锁文件。此次实际安装的全新环境已通过
`pip check`、完整原生模块导入、GUI 默认原生工作区启动/关闭与下面的严格资源检查；
环境检查没有对图纸做 OCR。

主要版本如下；完整精确版本以锁文件为准：

| 用途 | 实测版本 |
| --- | --- |
| Python | 3.12.14 |
| numpy / scipy | 2.3.5 / 1.17.0 |
| opencv-python / Pillow | 4.13.0.92 / 13.0.0 |
| ezdxf / PyMuPDF | 1.4.5 / 1.26.6 |
| RapidOCR / ONNX Runtime | 3.9.2 / 1.29.0 |
| PySide6 / pypdfium2 | 6.11.3 / 5.13.0 |
| psutil | 7.2.2 |

原 `cad_photo_to_dxf/requirements.txt` 和 legacy 处理逻辑保留。
两份环境的 PyMuPDF、Pillow 等版本要求并不相同，不应混装后声称等价。
Windows 构建仍有既有 legacy 烟测；它已明确传入 `--mode legacy`，
**不是最新原生引擎在干净 Windows 上的通过证据**。Windows native EXE、Android、DWG
往返仍需各自实测。

## 2. 提供 Tesseract、英语数据和字体

Python 锁文件不安装 Tesseract 可执行文件、系统字体或语言包。
按 [Tesseract 官方安装说明](https://tesseract-ocr.github.io/tessdoc/Installation.html)
安装引擎及英语数据，或者提供受控本地安装路径。
Linux 发行版通常分别提供 `tesseract-ocr`、`tesseract-ocr-eng` 和
`fonts-dejavu-core`；安装后仍须检查实际版本与字节，不能假定仓库版本就是本文的版本。
若发行版不含 5.5.0，可按官方
[5.5.0 源码发布](https://github.com/tesseract-ocr/tesseract/releases/tag/5.5.0)
构建并自行提供该引擎。

```bash
# 非默认安装时才设置；这里的路径由运行者实际提供。
export I2CAD_TESSERACT=/controlled/tesseract-5.5.0/bin/tesseract
export TESSDATA_PREFIX=/controlled/tessdata
"$I2CAD_TESSERACT" --version
"$I2CAD_TESSERACT" --list-langs
```

不设置 `I2CAD_TESSERACT` 时使用 PATH 中的 `tesseract`。
`--list-langs` 必须列出 `eng`。英语模型可从发行版语言包或官方
[tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) 获取；
随后核对以下实测字节。其他 `eng.traineddata` 不能仅因同名就视为同一模型。

| 资源 | 大小（bytes） | SHA-256 |
| --- | ---: | --- |
| Tesseract 5.5.0 可执行文件，本文 Linux 构建 | 51,536 | `74b76a5b994adcc18be362bf64ed5118082b2401d5d9a35242e92fc4c62e2b4b` |
| `eng.traineddata` | 4,113,088 | `7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2` |
| `DejaVuSans.ttf` | 759,720 | `57f73e11f51999432bf7ab22ce55b6f945d5eca1bf824404cfa9ec2e3718c84e` |

Tesseract 可执行文件哈希依赖平台和构建，不应与跨平台模型哈希混为一谈。
默认资源检查要求引擎版本和英语数据一致，并单列不同的二进制构建；
`--strict-platform-binaries` 还要求上表的引擎字节以及本次字体许可证文件字节完全一致。
动态库和操作系统仍是环境组成部分，这张哈希表不等于可移植整机镜像。

字体使用 [DejaVu 官方字体](https://dejavu-fonts.github.io/) 的受许可副本。
原生导出依次查找：

1. `cad_photo_to_dxf/resources/fonts/DejaVuSans.ttf` 及同目录
   `DejaVuSans.LICENSE.txt`；
2. Linux 的 `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` 及
   `/usr/share/doc/fonts-dejavu-core/copyright`。

字体和许可证必须同时存在。导出副本带上 `DejaVuSans.ttf` 与
`FONT_LICENSE_DejaVu.txt`。公开仓库只存资源清单，不提交模型、语言数据或字体二进制。

## 3. RapidOCR 模型与嵌入字典

安装锁文件中的 [RapidOCR 3.9.2 wheel](https://pypi.org/project/rapidocr/3.9.2/)
会获得本次核验的三个模型。正式独立识别器使用 recognition 模型；检测、方向分类
两个文件是 wheel 中的资源，不能因为它们存在就声称当前流程用了这些能力。
独立识别器用 CPU、单线程，只加载本地固定哈希的模型，不在运行时下载模型。

| wheel 内相对路径 | 大小（bytes） | SHA-256 |
| --- | ---: | --- |
| `models/PP-OCRv6_rec_small.onnx` | 21,234,383 | `6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884` |
| `models/PP-OCRv6_det_small.onnx` | 9,929,594 | `090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f` |
| `models/ch_ppocr_mobile_v2.0_cls_mobile.onnx` | 585,532 | `e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c` |

识别字典来自 recognition ONNX 的 `character` metadata，按 UTF-8 原样编码后
SHA-256 为 `f7aa897ca828a4c7c9e2739c30f9161a33306d532f020bcdb91dcfb664a5507e`；
加上 CTC blank 与空格后有 18,710 个解码项。它不是人工填入的期望答案列表。

统一检查：

```bash
.venv-native/bin/python maintenance/check_native_resources.py
# 在复现本文同一 Linux 二进制与许可证副本时加严格模式：
.venv-native/bin/python maintenance/check_native_resources.py --strict-platform-binaries
```

检查器只读包版本、文件哈希、Tesseract 版本/语言信息和 ONNX 字典元数据，
不下载文件、不安装依赖、不执行图纸识别。可以用 `--output /fresh/path/resources.json`
保存本次结果；已有文件不会被覆盖。完整机器可读基准见
[resource_manifest.json](resource_manifest.json)。失败应按实际缺少或不匹配的项目解决，
不能通过删掉校验项来取得通过。

### 3.1 ONNX Runtime 初始化前关闭遥测

本次锁定的 ONNX Runtime 1.29.0 官方 Linux wheel 含默认启用的 1DS 遥测。
其随包 `Privacy.md` 与 [官方隐私说明](https://github.com/microsoft/onnxruntime/blob/main/docs/Privacy.md)
要求在原生运行库初始化前设置 `ORT_DISABLE_TELEMETRY=1`，以阻止 uploader、事件和
持久设备标识创建。只在导入后调用 `disable_telemetry_events()` 可能来不及阻止最初的
初始化事件，因此不能把“模型在本机运行”当成依赖没有联网的证明。

本项目的正式 CLI/GUI、manager 子进程环境、独立识别器和资源检查入口会先强制设置
该环境变量，再导入 ONNX Runtime，并在创建本项目 session 前调用官方
`disable_telemetry_events()`。保留的 RapidOCR 入口也先经过同一初始化守卫。
如果进程已经在守卫之前加载过 ONNX Runtime，运行会明确拒绝；应从正式入口启动
新进程，不在旧解释器中补设变量后声称初始化已经受控。

任务状态、worker 回执、模型身份与 `evidence/runtime_privacy.json` 记录实际配置，
资源检查也输出 `runtime_privacy`。这些是初始化与 API 配置证据；系统级零联网需要
另行保存实际网络调用跟踪。`remote_service_calls=0` 仅表示应用没有调用远程识别服务，
不代表所有依赖和整个进程都已经实测零联网。上述措施使用运行库自身的 opt-out，
不修改网络隔离、审批控制或端点白名单。已有中断与审批拒绝记录应保留。

## 4. 在干净任务目录运行正式入口

将合法受控输入放在 Git 外，确定实际像素范围和 DPI。下面使用项目已经冻结的
区域作为配置示例；不是识别器中的页面答案、坐标白名单或自动猜测。

```bash
mkdir -p /controlled/run-001
.venv-native/bin/python cad_photo_to_dxf/main.py \
  --headless \
  --input /controlled/A2-SG-008.tiff \
  --roi 1400 1000 5000 3411 \
  --dpi 200 \
  --output /controlled/run-001/region.dxf \
  --jobs-dir /controlled/run-001/jobs \
  --verbose
```

未传 `--mode` 时就是 `native-objects`。运行者可在任意工作目录使用绝对脚本路径；
输入会复制到该任务目录并校验 SHA-256，处理从原始文件读取，预览图不作为识别输入。
多页 PDF 必须显式提供 `--page`，多帧 TIFF 必须提供 `--frame`，均从 1 开始。
`--roi` 为选择页/帧在旋转前的半开像素范围；`--orientation` 支持顺时针
0、90、180、270 度。DPI 目前须为正整数，`200.0` 可用，不能用任意小数值隐式舍入。

GUI 启动命令为：

```bash
.venv-native/bin/python cad_photo_to_dxf/main.py
```

默认页签和窗口标题显示 `native-objects`。选择文件、页/帧、DPI、区域，核对预览后开始。
新任务的 CPU/时间/内存/任务文件预算可见可配；旧任务恢复继续使用原合同。
显式 `--mode legacy` 或选择“兼容工具 · legacy”才进入保留基线。
菜单导入/导出跟随当前引擎，native 中不启用 legacy 校对项目菜单。

默认完整区域合同为 CPU 7,200 秒、墙钟 7,200 秒、worker+OCR 进程树 3,072 MiB、
全部任务文件 8,192 MiB；OCR/数值线程限制为 1。CLI 可用
`--cpu-seconds`、`--wall-seconds`、`--rss-mib`、`--temporary-mib` 显式设定。
恢复仍扣除已用 CPU 与时间，不因重启自动获得新预算。任务文件量包括捕获的输入和
保留的尝试，不仅是某个临时子目录。超限保存停止状态和检查点，不把未跑完当成算法否决。

每个新任务默认创建自己的空原始观察缓存，按实际灰度像素、padding、PSM/DPI 和
引擎/模型身份复用已经完成的 raw TSV 或 raw CTC；同一输入配置不产生额外一致性票数。
CLI 不接受采用名单或作者 evidence/temp 目录。
`--native-cache`、`--evidence-dir`、`--temp-dir` 等旧实验参数会明确拒绝，并指向
持久任务目录及受校验的恢复接口；不会静默忽略或回退 legacy。
同一已完成任务应从历史打开/导出；中断后使用 GUI 的任务恢复。
换版本复用历史原始观察使用下述显式导入；不能复用旧采用结论。

### 4.1 导入可移动的原始观察（不恢复旧采用结论）

首次受控输入运行不需要任何旧缓存。已有有效实验原始观察时，可以在 Git 外建立
独立观察目录，避免对相同输入再次识别。导入器只读取原始 TSV、模型 raw CTC、
其 PNG/metadata、发布文件摘要和来源 receipt；不读取旧对象采用名单、旧 DXF 或旧审核结论。

```bash
.venv-native/bin/python maintenance/import_native_raw_observations.py \
  --source /controlled/A2-SG-008.tiff \
  --published /controlled/v84/final_published_result \
  --receipt /controlled/v84/run_records/quarter_layout_final/jobs/v8-layout-final/imports/revision/receipt.json \
  --resource-evidence /controlled/v84/delivery_verification/REPRODUCE.md \
  --producer-source /controlled/v84/source/cad_photo_to_dxf \
  --source-audit /controlled/v84/audits/revision_import/audit_final_v8_4.json \
  --output /controlled/raw-observations \
  --allow-historical-tesseract

I2CAD_RAW_OBSERVATION_CACHE=/controlled/raw-observations \
  .venv-native/bin/python cad_photo_to_dxf/main.py \
  --headless --input /controlled/A2-SG-008.tiff \
  --roi 1400 1000 5000 3411 --dpi 200 --frame 1 \
  --output /controlled/run-002/region.dxf --jobs-dir /controlled/run-002/jobs --verbose
```

导入器逐项核对原文件 SHA、选定页/帧/方向和完整解码像素、实际裁剪像素、原始
PNG/TSV/metadata 的文件摘要、PSM/DPI、原 producer 源码摘要和资源证据。PP 还核对
模型、字典、runtime、模型输入 tensor 及 raw CTC tokens。它只打开 ONNX 元数据，
不调用识别推理。`import_report.json` 列出每项是否导入；缺失或矛盾的证据不导入。

v8.4 receipt 中 Tesseract 的 `current_*` 哈希是后来导入环境的测量；原识别调用的
`historical_executable_sha256`、`historical_model_sha256` 为 `null`，
`historical_model_byte_identity_proven=false`。因此这 814 条 TSV 只能进入显式允许的
`historical-tesseract-tsv` 命名空间，不能冒充当前精确引擎字节命中。该命名空间还要求
本次任务的整个原文件 SHA 相同。省略 `--allow-historical-tesseract` 会准确记录这些条目
未导入；不会用当前安装的二进制哈希填补历史空白。

现行真实调用从执行时捕获 Tesseract executable/eng 字节哈希；PP 按原始 crop、
实际模型 tensor、model/dictionary、ONNX Runtime 和解码策略寻址。新输入或配置变化
会正常识别一次。历史匹配只提供原始观察，当前的来源归属、歧义裁决、对象生成和
保存审核均重新执行。原有 checkpoint/resume producer 守卫保持生效。

任务记录缓存根目录、manifest 摘要及启动 inventory 摘要；worker 校验后继承该目录。
发布证据中的 `raw_observation_usage.json` 列明每条命中/新计算、原 producer、原始
资源边界及已复制的证明文件。旧 raw 输出中的耗时保留原值，不计作本次推理耗时；
本次真实总资源由 manager/worker 单独计量。相同观察不会被包装成独立引擎的新票数。

## 5. 实际产物与绑定方式

成功导出包括：

- `region.dxf`、`region.objects.json` 和 `region.export.json`；
- `region.native/` 中的保存结果、原图区域、质量/来源材料、entry trace、模型/运行记录；
- 字体与许可副本；
- `jobs/<job-id>/state.json`、各次执行的 request/outcome、资源与错误记录。

CLI 成功退出只说明该候选经保存与审核绑定检查后已导出，退出码 2 表示任务未完成
并保留证据。错误不得用空 DXF 或 legacy 结果替代。
可额外指定 `--preview`、`--report`、`--resource-report` 复制对应产物到新的路径。

算法指纹包括原生源码、入口、manager/worker、`processing.py` 与 `main.py` 的文件哈希；
同时自动记录实际 Git HEAD 和工作树 dirty 状态，不把作者填入的提交字符串当证据。
没有 Git 元数据的源码归档/冻结程序明确记录 unavailable，并保留文件或可执行文件哈希。
正式本轮结果应使用干净检出生成；工作树有变化时不得说成完全等于 HEAD。

当前坐标单位为**纸面毫米**。继续按建筑实际墙长、门宽设计，需要图纸比例或可靠已知尺寸标定；
DPI 不能直接代表建筑实际比例。对象删移、文字修改、CAD 保存重开和工程师修图时间
仍按同一完整区域另行验证；没有工程师参与时记录 `NOT_RUN`。

## 6. CI 中的来源与兼容入口合同

原 legacy 侧栏检查通过显式 `processing_mode="legacy"` 进入其页签，仍检查侧栏至少
500 像素、无横向滚动和无弃用文案。默认 native 页签、引擎标识及兼容工具显式选择
仍由独立入口测试检查。原 FreeCAD legacy/full-trace 样例验证显式使用 `--mode legacy`；
正式默认入口保持 native，并由 Native Linux CI 的真实受控转换验证。

源像素和几何连接禁止形态学封口。现有 `_frames` 的一个固定 3×3 closing 只作用于
独立候选发现图，目的是提出断裂矩形框的待验证候选。测试对全 `app` 扫描，只允许
`native_objects/text_regions.py::_frames` 内这一处、这一参数形状的 AST 调用；其他
legacy/native 模块和 native connections 继续全部受禁令约束，没有按目录豁免。

该唯一例外另有行为测试：不可写原图、ink 和 glyph labels 保持逐像素不变；原白缝
仍在，实际 OCR 输入只能是原 crop 加外部白边；候选的 `edge_support` 必须采样原 ink。
即使候选发现图人为给出完整封口，原图缺边达不到支持门槛仍被拒绝。候选始终标记
`source_frame_continuity_proven=false`、`geometry_must_verify_original_four_sides=true`，
不能把候选图中的补口用作完整闭合来源证据。
