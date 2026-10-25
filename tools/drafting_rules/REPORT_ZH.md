# 首个可执行规则包交付证据 — 2026-10-25

范围：`cn-sheet-text-table@0.1.0`。权威基线是远程 main `900511b5a884421bc372a39fc7f59ded18639ac9`，初始工作区干净。
本轮是用户明确授权的实现任务，不是只读审计；交付一个独立包和一个常规提交，不替换生产转换入口。

## 代码事实

实现六项可运行检查：原生可见文字与给定字符串、LFF 单元格范围、已映射旧字形退场、独立背景保护、来源直线段多重集、编辑非目标保持。
其中四项为 `PRODUCT_REQUIREMENT`，单元格范围算法和线段对照方法为 `EXPERIMENTAL_HEURISTIC`。
后两项的几何假设与 `1e-6` 比较容差不是国家标准条文。

`engine.py` 是纯数据规则接口；`dxf_adapter.py` 读实际保存的 DXF，并复用既有 `librecad_text_metrics`。
`cli.py` 验证 JSON schema、来源/前后文件摘要、坐标单位、规则来源，输出逐目标 PASS/FAIL/ABSTAIN 和版本比较。
输出独占创建，运行前后源文件保持不变。未调用模型、未训练、未外传真实资料。

修改前已检查：`ocr_layout.py`、`ocr_fast.py`、`content_ownership.py`、`text_output_contract.py`、`logo_detection.py`、
`signature_overlay.py`、`review_text.py`、`ocr_outline_export.py`、导出器及相应旧测试；没有复制旧 Skill 充当实现。
已有文字/归属/保护/导出算法、依赖声明、锁文件和旧回归基线均未修改。
新增 CI 工作流单独运行包测试；远程 CI 状态须以实际 Actions 结果为准，本报告不替代它。

## 实际研究来源及未核实标准

已核对的规范性依据是本项目已确认产品要求和验收门槛，具体章节在 [清单](pack/manifest.json) 中逐条登记。
已实际打开、渲染并检查的真实来源是仓库保留的 `warehouse-electrical-vector.pdf` 第 2 页、136 DPI 局部 `[4080,2200,4390,2410]`。
SHA-256：`8967fc042f4979f017ca4d27d25e66e7c9fbb2e46d840d0fd81e68268af31017`。
复用 `test_table_text_layout.py` 已有“专业负责人 / Discipline / Responsible”转录观察，不声称新的自动 OCR 识别成果。
该局部可观察到双语文字、邻接格线和手写签名；英文行的矩形范围有交叠，不能直接推出字形碰撞。
裁片边缘截断了部分手写内容；本轮未将这个局部当作完整图签或整页保真通过。

尝试从国家标准全文公开系统核对 GB/T 10609.1-2008、GB/T 14691-1993；HTTPS CONNECT 被网络代理拒绝（403），请求未到达正式来源。
也尝试了住房城乡建设部公开入口，结果相同。具体请求与结论见 [访问记录](evidence/standard-access.json)。
因此上述标准的当前有效性、全文、具体条款均**未核实**，没有编造尺寸/字号/字段要求，没有可执行 `OFFICIAL_STANDARD` 规则。
标题栏/字体标准、文字碰撞与对齐规则保持 `CANDIDATE`；加载器拒绝将缺少核验全文/版本/条款的标准来源升级为可执行标准规则。

## 自动化测试事实

环境：Python 3.12.14；ezdxf 1.4.5；PySide6 6.11.2；pypdfium2 5.14.0；PyMuPDF 1.26.7；pytest 8.4.2。
现有 requirements 只有版本范围、没有冻结锁文件；安装遵循现有范围，未改依赖或关闭 TLS/校验。
完整安装版本留在本机 `local-artifacts/drafting-rules/installed-versions.txt`。

下述命令均在仓库根目录执行。测试前设置：

```bash
export QT_QPA_PLATFORM=offscreen
export XDG_CACHE_HOME=/workspace/.cache
export PYTHONPATH="$PWD/cad_photo_to_dxf"
```

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 独立包测试 | 44 passed，0 failed / skipped / xfail | `local-artifacts/drafting-rules/tests.xml` |
| 纯数据规则测试 | 上述 44 中的 16 项 | `tests/test_engine.py` |
| 合成保存 DXF 测试 | 上述 44 中的 27 项 | `tests/test_dxf.py` |
| 真实 PDF 保存 DXF 测试 | 上述 44 中的 1 项 | `tests/test_real_pdf.py` |
| 既有相关完整测试文件及 native-first | 113 passed，0 failed / skipped | `local-artifacts/drafting-rules/regression.xml` |
| 保真检查 | EXACT，匹配 2026-10-24 基线；P10-A 身份和旧 LINE 来源义务保持 | `maintenance/preservation_check.py` |
| 包 Ruff / compileall / pip check | 全部通过 | 下列命令 |
| 未改主程序 headless | 实际输出 DXF；151 个原生 LINE；独立读回 0 errors / 0 fixes、端点有限 | `local-artifacts/drafting-rules/app-smoke.*` |

精确命令：

```bash
.venv/bin/python -m pytest -q tools/drafting_rules/tests --junitxml=local-artifacts/drafting-rules/tests.xml
.venv/bin/python -m pytest -q cad_photo_to_dxf/tests/test_source_text_layout.py cad_photo_to_dxf/tests/test_table_text_layout.py cad_photo_to_dxf/tests/test_scanned_text_rows.py cad_photo_to_dxf/tests/test_content_ownership.py cad_photo_to_dxf/tests/test_ownership_commit_veto.py cad_photo_to_dxf/tests/test_text_output_contract.py cad_photo_to_dxf/tests/test_signature_overlay.py cad_photo_to_dxf/tests/test_text_protection.py cad_photo_to_dxf/tests/test_review_save_preservation.py cad_photo_to_dxf/tests/test_native_text_geometry.py cad_photo_to_dxf/tests/test_portable_font_bundle.py tools/native_first/tests --junitxml=local-artifacts/drafting-rules/regression.xml
.venv/bin/python maintenance/preservation_check.py
.venv/bin/python -m ruff check --config cad_photo_to_dxf/ruff.toml tools/drafting_rules
.venv/bin/python -m compileall -q tools/drafting_rules
.venv/bin/python -m pip check
.venv/bin/python -m tools.drafting_rules.study --output local-artifacts/drafting-rules/run-03
.venv/bin/python cad_photo_to_dxf/main.py --headless --input cad_photo_to_dxf/samples/test.jpg --allow-uncorrected --output local-artifacts/drafting-rules/app-smoke.dxf --preview local-artifacts/drafting-rules/app-smoke.png --report local-artifacts/drafting-rules/app-smoke.json
```

安装脚本已在当前实例执行并重复执行，依赖检查通过；两次独立 study 的逐项规则结果完全相同。
保存的启动步骤已实际执行：包与 native-first 合跑 74 passed，真实 study 与旧主程序 headless 均成功。
CLI 对真实越界反例实际返回退出码 1；`compare` 记录同一规则从通过变为失败及其边界数值。
DXF 文件有生成时间/身份元数据，字节摘要可以变化；来源摘要、结果与版本才是比较依据，不能把文件字节不同当几何退化。
开发过程中新增单位校验发现新合成夹具沿用了 ezdxf 默认米单位，与夹具声明 unitless 不符；已将**新增合成夹具**设置为 unitless 后重跑。
没有改任何旧夹具、降低断言或用改基线吸收失败。

## 真实图纸的具体用途与失败报告

既有导出器生成的真实局部基线含 21 LINE、106 LWPOLYLINE、3 TEXT。
将 `Discipline` 改为 `DisciplineA`，保存后重新解析；3 个字符串、3 个单元格范围与非目标保持共 7 PASS。
把同一实体改为超长重复字符串，新增检查准确报告 `INK_OUTSIDE_CELL`；再移动一个非目标轮廓，额外报告 `UNRELATED_ENTITIES_CHANGED`。
这提供了一个**能截住真实单元格越框编辑与误改旁边实体的独立守卫**，没有声称修复完整转换质量、自动补字或减少了经真人计时的劳动。

| 运行 | PASS | FAIL | ABSTAIN | 解释 |
| --- | --- | --- | --- | --- |
| 正常改字保存读回 | 7 | 0 | 5 | 字符、范围、非目标保持通过 |
| 超长文字反例 | 6 | 1 | 5 | 越出单元格 |
| 再加无关轮廓移动 | 5 | 2 | 5 | 越框及旁及修改 |

逐项数值、句柄和失败原因已保留在 [正常报告](evidence/edited.report.json)、[越界失败报告](evidence/overflow.report.json)、
[旁及修改失败报告](evidence/unrelated-change.report.json)、[判定变化](evidence/comparison.json) 和 [运行摘要](evidence/study.json)。
原 DXF 没有本检查器所需的完整原字形成员映射、独立背景映射和来源表线段集，故 3 个字形检查＋背景＋表线合计 5 ABSTAIN。
这是真实的证据缺口；配置一个完整性布尔值不等于验证了物理归属，后续需要现有来源证明的薄适配器。
合成 DXF 中的完整映射验证了旧笔画残留、Logo 改动、表线重复/缺失/桥接等反例，但不能代替真实图中这些合同的验收。

## 真人 UAT 与假设

本轮没有新的 User UAT 事实。LibreCAD 打开/中文英文数字编辑/移动/保存/完全关闭后重开、字体替换、背景依赖、撤销、DWG 往返、独立来源泛化、真人净省时均为 **NOT_RUN**。
全页 600 DPI 历史 OCR 重转和全库所有无关测试也未运行；本轮只运行此独立包及相关旧合同测试，不修改其冻结基线。
本轮结果不关闭 CAD-001/CAD-005/CAD-008 的既有真人验收问题。
“来源成员适配能减少弃判”和“规则守卫能节省人工”仍是待真实编辑验证的假设。

## 云环境配置

使用 `cloud-environment-onboarding:setup`，已保存完整 `install_script`、`start_skill` 和标准研究所需域名
`openstd.samr.gov.cn`、`std.samr.gov.cn`、`www.mohurd.gov.cn`；保留原网络预设，不添加任何密钥要求。
当前实例支持离线开发、局部真实 DXF 生成与检查；正式标准在线访问仍受阻。
保存草稿不等于发布或新任务恢复验证；需在环境设置中审阅并保存，再发布环境。未验证新实例恢复。
