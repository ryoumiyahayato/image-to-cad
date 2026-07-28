# 阶段一：当前重构与旧算法双基线

## 状态与范围

本目录是十二阶段顺序核验任务的阶段一交付物，只用于冻结、比较和复现版本。阶段一没有修改识别算法、连接规则、对象归属逻辑或任何阈值，也没有加入针对文件名、页码、固定坐标、页面百分比、OCR 词义或单张图片的分支。

| 基线 | Git commit | 固定标签 | 算法标识 |
| --- | --- | --- | --- |
| 当前重构基线 | `5a1b06585b6f068bb5f61e16fd32b96e4f54275b` | `baseline/current-refactor-2026-07-28` | 应用 `1.3.0`，`FinalStructure` schema `2`，七项系统级重构冻结版本 |
| 旧算法基线 | `6a2aa545a534ea6fd50db8a5ba942a0a5db9e353` | `baseline/old-algorithm-pre-d9fbda7` | 应用 `1.3.0`，尚无 `FinalStructure` schema，自动直线重连进入主流程前的最后版本 |

阶段一证据和复现工具固定在标签 `baseline/phase1-evidence-2026-07-28`。

旧算法基线的选择不是按日期猜测：`6a2aa54` 中不存在 `straight_line_reconstruction.py`，也不存在 `reconstruct_straight_lines` 调用；其 `optimized_trace.py` 在页面准备和可选 OCR 后直接调用 `trace_binary(prepared.binary)`。从 `6a2aa54` 到 `d9fbda763e95c6dd7154934b801b59dbf034e711` 的差异首次加入 `straight_line_reconstruction.py` 并修改 `optimized_trace.py`。可用以下命令复核：

```powershell
git ls-tree -r --name-only 6a2aa545a534ea6fd50db8a5ba942a0a5db9e353 |
  Select-String 'straight_line_reconstruction.py'
git grep -n reconstruct_straight_lines 6a2aa545a534ea6fd50db8a5ba942a0a5db9e353 -- cad_photo_to_dxf/app
git diff --name-status `
  6a2aa545a534ea6fd50db8a5ba942a0a5db9e353 `
  d9fbda763e95c6dd7154934b801b59dbf034e711 `
  -- cad_photo_to_dxf/app/optimized_trace.py `
     cad_photo_to_dxf/app/straight_line_reconstruction.py
```

前两条命令应无匹配；第三条命令应显示一个修改文件和一个新增文件。

## 交付物索引

两套目录具有相同结构：

```text
validation/system-refactor-baselines/
├── current/
│   ├── baseline-result.json
│   ├── config-snapshot.json
│   ├── tests/pytest-junit.xml
│   └── outputs/*.dxf
└── old/
    ├── baseline-result.json
    ├── config-snapshot.json
    ├── tests/pytest-junit.xml
    └── outputs/*.dxf
```

- `config-snapshot.json`：commit、应用和结构版本、默认参数、OCR 参数、Python、依赖、核心源文件哈希和测试摘要。
- `baseline-result.json`：测试状态、输入哈希、结构统计、`structure_id`、DXF 统计、DXF 哈希和 `ezdxf` 审计结果。
- `tests/pytest-junit.xml`：对应冻结 commit 的完整单元测试结果。
- `outputs/*.dxf`：三份现有真实回归页面的实际 DXF 输出。

JSON 中的绝对路径仅记录本次采集来源；输入内容哈希、commit、配置、结构统计和审计结果才是跨目录复现依据。

## 配置与运行环境

两套基线均使用生产默认入口：

- `trace_image_optimized(enable_ocr=False, foreground_threshold=None)`；
- 直线检测默认值：`hough_threshold=35`、`min_line_length=35`、`max_line_gap=10`、`use_lsd=true`、`max_segments=6000`；
- 几何配置快照：`snap_distance=6.0`、`max_bridge_gap=12.0`、`angle_tolerance=3.0`、`collinear_distance=3.0`、`min_line_length=12.0`。旧算法基线虽然能加载这份默认配置，但主追踪路径尚未调用自动直线重连；
- OCR 生产默认关闭；最低置信度 `0.5`，候选上限 `3000`，RapidOCR `max_side_len=4096`、日志级别 `warning`。

采集环境为 CPython `3.14.6`、Windows x64。依赖快照如下：

| 依赖 | 版本 | 依赖 | 版本 |
| --- | --- | --- | --- |
| numpy | 2.5.1 | scipy | 1.18.0 |
| opencv-python | 4.13.0.92 | ezdxf | 1.4.4 |
| PySide6 | 6.11.1 | pypdfium2 | 5.12.1 |
| Pillow | 12.3.0 | rapidocr | 3.9.2 |
| onnxruntime | 1.27.0 | pytest | 8.4.2 |
| ruff | 0.15.22 | mypy | 1.20.2 |

完整值和核心源文件 SHA-256 以两份 `config-snapshot.json` 为准。

## 测试结果

| 基线 | 测试数 | 失败 | 错误 | 跳过 | JUnit 时间 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 当前重构 | 205 | 0 | 0 | 0 | 17.181 s |
| 旧算法 | 156 | 0 | 0 | 0 | 7.011 s |

JUnit 文件 SHA-256：

- 当前重构：`80721a03d21607379b3ce9e8f2589266c0145a7ba72c7ccb1d1222acdd6b33c5`
- 旧算法：`8ec08012f043486ee5d460d6efa6da5b898bff285d5d559acb1a8ca0c6010ffe`

## 三份真实页面输出

输入文件内容固定为：

| 页面 | 输入 SHA-256 |
| --- | --- |
| `test.jpg` | `526e0d7fd9a5cdeb1d25764b93ce9c655688364eb762f47898d850aded14b8af` |
| `environment-page-003.png` | `47a7d9fc4062cfa556e2e4a1ea62124342416c9b2f27d0c42a691f76d8ad83cc` |
| `warehouse-page-001.png` | `ee4937113bf9615ae2ab056c71850d279fea515258b7c87ed0b100439bf6011d` |

当前重构基线：

| 页面 | 轮廓/顶点 | 直线 | 前景像素 | DXF 实体 | 审计错误 | `structure_id` |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| test | 146 / 7,593 | 90 | 643,818 | 317 | 0 | `0611db76d8047955c51b216617f2e71ad0713146353eff19bd1b80837013ecbe` |
| environment | 2,379 / 38,362 | 634 | 133,962 | 3,111 | 0 | `080f07948ad698db468dd6158ac84e01492134078295599bf9c711d679904020` |
| warehouse | 1,404 / 22,135 | 121 | 52,591 | 1,581 | 0 | `6e41b658a97841af57bf55c913dcf709313de9e04404599ea32711a95362593f` |

旧算法基线：

| 页面 | 轮廓/顶点 | 直线 | 前景像素 | DXF 实体 | 审计错误 | `structure_id` |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| test | 135 / 9,256 | 0 | 767,909 | 228 | 0 | 不适用 |
| environment | 3,172 / 68,378 | 0 | 385,728 | 3,536 | 0 | 不适用 |
| warehouse | 1,574 / 24,965 | 0 | 133,387 | 1,638 | 0 | 不适用 |

DXF 文件的 SHA-256 已保存在 `baseline-result.json`。DXF 头部可能包含生成时间，因此字节哈希属于本次冻结证据；跨机器重跑时，首要验收项是输入哈希、commit、配置、测试计数、结构统计、`structure_id` 和 DXF 审计。

## OCR 边界与已知限制

双基线比较明确采用生产默认的 OCR 关闭状态，三份输入、运行环境和调用入口一致。它不借助关闭 OCR 掩盖当前版本问题：当前重构 commit `5a1b065` 已另行通过启用 OCR 的三页强制真实回归。

另外做过一次不计入默认双基线的 OCR 开启诊断。旧算法基线完成了 OCR 和追踪（例如 environment 页得到 3,172 条路径、160 个文字候选和 68,378 个顶点），但进程在旧版 `export_exact_trace_dxf` 生成 OCR CAD 实体期间以代码 1 退出，未保存 DXF。该限制被保留为旧路径的已知运行问题，不能通过修改阈值或删除失败证据让阶段一“变绿”；应在后续对应阶段基于真实回归单独调查。

## 从固定标签完整复现

以下命令从三个固定标签建立独立 worktree，重新运行两套完整测试，并用同一工具和同一组冻结输入生成 DXF。命令不传 `--enable-ocr`，因此严格复现生产默认配置。

```powershell
$repo = 'C:\Users\agcrf\Desktop\image-to-cad'
$python = "$repo\cad_photo_to_dxf\.venv\Scripts\python.exe"
$runId = [Guid]::NewGuid().ToString('N')
$toolWt = Join-Path $env:TEMP "image-to-cad-phase1-tool-$runId"
$currentWt = Join-Path $env:TEMP "image-to-cad-phase1-current-$runId"
$oldWt = Join-Path $env:TEMP "image-to-cad-phase1-old-$runId"
$repro = Join-Path $env:TEMP "image-to-cad-phase1-output-$runId"

git -C $repo worktree add --detach $toolWt baseline/phase1-evidence-2026-07-28
git -C $repo worktree add --detach $currentWt baseline/current-refactor-2026-07-28
git -C $repo worktree add --detach $oldWt baseline/old-algorithm-pre-d9fbda7
New-Item -ItemType Directory -Path $repro | Out-Null

Push-Location "$currentWt\cad_photo_to_dxf"
& $python -m pytest -q --junitxml "$repro\current-pytest.xml"
Pop-Location

Push-Location "$oldWt\cad_photo_to_dxf"
& $python -m pytest -q --junitxml "$repro\old-pytest.xml"
Pop-Location

$capture = "$toolWt\cad_photo_to_dxf\scripts\capture_frozen_baseline.py"
$assets = "$currentWt\cad_photo_to_dxf\tests\real_regression\assets"

& $python $capture `
  --project-root "$currentWt\cad_photo_to_dxf" `
  --label current-refactor-default `
  --expected-commit 5a1b06585b6f068bb5f61e16fd32b96e4f54275b `
  --junit-source "$repro\current-pytest.xml" `
  --input "$assets\test.jpg" `
  --input "$assets\environment-page-003.png" `
  --input "$assets\warehouse-page-001.png" `
  --output-dir "$repro\current"

& $python $capture `
  --project-root "$oldWt\cad_photo_to_dxf" `
  --label old-algorithm-default-pre-d9fbda7 `
  --expected-commit 6a2aa545a534ea6fd50db8a5ba942a0a5db9e353 `
  --junit-source "$repro\old-pytest.xml" `
  --input "$assets\test.jpg" `
  --input "$assets\environment-page-003.png" `
  --input "$assets\warehouse-page-001.png" `
  --output-dir "$repro\old"
```

采集脚本会在以下任一情况返回非零：worktree commit 不匹配、输入或 JUnit 缺失、输出目录非空、测试存在失败/错误、DXF 不能读取或 DXF 审计出现错误。

快速验收：

```powershell
$current = Get-Content -Raw "$repro\current\baseline-result.json" | ConvertFrom-Json
$old = Get-Content -Raw "$repro\old\baseline-result.json" | ConvertFrom-Json
$current | Select-Object label,git_commit,passed,test_result
$old | Select-Object label,git_commit,passed,test_result

$auditCode = @'
import ezdxf
from pathlib import Path
import sys

root = Path(sys.argv[1])
paths = sorted(root.glob("*/outputs/*.dxf"))
assert len(paths) == 6, paths
for path in paths:
    errors = ezdxf.readfile(path).audit().errors
    print(path, "audit_errors=", len(errors))
    assert not errors
'@
& $python -c $auditCode $repro
```

完成后只移除本次命令创建的精确 worktree：

```powershell
git -C $repo worktree remove $toolWt
git -C $repo worktree remove $currentWt
git -C $repo worktree remove $oldWt
git -C $repo worktree prune
```
