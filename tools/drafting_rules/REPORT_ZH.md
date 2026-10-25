# 首个可执行规则包交付证据 — 2026-10-25

范围：`cn-sheet-text-table@0.1.1`。本轮权威入口是远程 main `ce89a8d7c8ba8952e8d4e016b81c77f404faf672`，初始工作区干净。
该入口已含首版原型；本轮复核并修正其坐标误判、补完正式来源研究，不重复开发已有能力。
本轮是用户明确授权的实现任务，不是只读审计；交付一个独立包和一个常规提交，不替换生产转换入口。

## 代码事实

实现六项可运行检查：原生可见文字与给定字符串、LFF 单元格范围、已映射旧字形退场、独立背景保护、来源直线段多重集、编辑非目标保持。
其中四项为 `PRODUCT_REQUIREMENT`，单元格范围算法和线段对照方法为 `EXPERIMENTAL_HEURISTIC`。
后两项的几何假设与 `1e-6` 比较容差不是国家标准条文。

复现并修正表线检查的 OCS/WCS 误判：本地 `(0,0)→(60,0)`、法向 `(0,0,-1)` 的多段线实际位于世界 `(0,0)→(-60,0)`。
0.1.0 误将原始局部数字与来源比较；0.1.1 复用 ezdxf 的 `vertices_in_wcs()` 转换，正确报告位置不符，非世界 XY 平面的线段弃判。
这是合成 DXF 中已复现的检查器缺陷，不声称已在真实 W02 中发现相同错误。

`engine.py` 是纯数据规则接口；`dxf_adapter.py` 读实际保存的 DXF，并复用既有 `librecad_text_metrics`。
`cli.py` 验证 JSON schema、来源/前后文件摘要、坐标单位、规则来源，输出逐目标 PASS/FAIL/ABSTAIN 和版本比较。
输出独占创建，运行前后源文件保持不变。未调用模型、未训练、未外传真实资料。

修改前已检查：`ocr_layout.py`、`ocr_fast.py`、`content_ownership.py`、`text_output_contract.py`、`logo_detection.py`、
`signature_overlay.py`、`review_text.py`、`ocr_outline_export.py`、导出器及相应旧测试；没有复制旧 Skill 充当实现。
已有文字/归属/保护/导出算法、依赖声明、锁文件和旧回归基线均未修改。
新增 CI 工作流单独运行包测试；远程 CI 状态须以实际 Actions 结果为准，本报告不替代它。

## 实际研究来源与正式条款

已核对的规范性依据是本项目已确认产品要求和验收门槛，具体章节在 [清单](pack/manifest.json) 中逐条登记。
已实际打开、渲染并检查的真实来源是仓库保留的 `warehouse-electrical-vector.pdf` 第 2 页、136 DPI 局部 `[4080,2200,4390,2410]`。
SHA-256：`8967fc042f4979f017ca4d27d25e66e7c9fbb2e46d840d0fd81e68268af31017`。
复用 `test_table_text_layout.py` 已有“专业负责人 / Discipline / Responsible”转录观察，不声称新的自动 OCR 识别成果。
该局部可观察到双语文字、邻接格线和手写签名；英文行的矩形范围有交叠，不能直接推出字形碰撞。
裁片边缘截断了部分手写内容；本轮未将这个局部当作完整图签或整页保真通过。

本轮 SAMR 访问成功，原先的 CONNECT 403 仅保留为历史证据。已实际核实：

| 正式来源 | 核实范围 | 程序中的处理 |
| --- | --- | --- |
| GB/T 10609.1-2008《技术制图 标题栏》 | 官方标为“现行”；2008-06-26 发布，2009-01-01 实施；公开预览全部 5 页，封面版本相符 | §3.1 的每张技术图样应有标题栏要求成为有正式依据的候选；没有全页清单与可靠图签归属时不自动判有无 |
| 同上 §3.3、§4.1、§5.1–5.2、附录 A | 签字字体例外；常用分区可按需增减；尺寸/格式；附录明确为资料性 | 未把签字强制转成正文，未把示例模板套用到建筑/电气图签；未扩大为所有标准符合性通过 |
| GB/T 14691-1993《技术制图 字体》 | 官方标为“现行”；1993-11-09 发布，1994-07-01 实施；因采标版权不提供正文阅读 | 全文/条款仍未核实，只有来源研究记录，不再将它标为 OFFICIAL_STANDARD 候选规则 |

官方链接、响应摘要、公开预览图像及各页摘要见 [访问和研究记录](evidence/standard-access.json)。
仅使用公开预览的正常页面资源，按其 CSS 矩形显示正文；未提交或绕过下载验证码。全文和预览图只保留在忽略目录，不上传完整标准。
住房城乡建设部入口本轮返回代理 502，未读到其条文。没有可执行 `OFFICIAL_STANDARD` 规则；标准存在性候选与文字碰撞/对齐候选的依据和分类均单独记录。
加载器现在对正式分类的候选也要求核验全文、版本和条款，避免未知内容先占用正式分类。

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
| 独立包测试 | 49 passed，0 failed / skipped / xfail | `local-artifacts/drafting-rules/revision-011/tests.xml` |
| 纯数据规则测试 | 上述 49 中的 16 项 | `tests/test_engine.py` |
| 合成保存 DXF 测试 | 上述 49 中的 32 项 | `tests/test_dxf.py` |
| 真实 PDF 保存 DXF 测试 | 上述 49 中的 1 项 | `tests/test_real_pdf.py` |
| 既有相关完整测试文件及 native-first | 113 passed，0 failed / skipped | `local-artifacts/drafting-rules/revision-011/regression.xml` |
| 保真检查 | EXACT，匹配 2026-10-24 基线；P10-A 身份和旧 LINE 来源义务保持 | `maintenance/preservation_check.py` |
| 包 Ruff / compileall | 全部通过；依赖不变，pip check 为上一轮证据 | 下列命令 |
| 未改主程序 headless（ce89a8d 上轮证据） | 实际输出 DXF；151 个原生 LINE；独立读回 0 errors / 0 fixes、端点有限 | `local-artifacts/drafting-rules/app-smoke.*` |

精确命令：

```bash
.venv/bin/python -m pytest -q tools/drafting_rules/tests --junitxml=local-artifacts/drafting-rules/revision-011/tests.xml
.venv/bin/python -m pytest -q cad_photo_to_dxf/tests/test_source_text_layout.py cad_photo_to_dxf/tests/test_table_text_layout.py cad_photo_to_dxf/tests/test_scanned_text_rows.py cad_photo_to_dxf/tests/test_content_ownership.py cad_photo_to_dxf/tests/test_ownership_commit_veto.py cad_photo_to_dxf/tests/test_text_output_contract.py cad_photo_to_dxf/tests/test_signature_overlay.py cad_photo_to_dxf/tests/test_text_protection.py cad_photo_to_dxf/tests/test_review_save_preservation.py cad_photo_to_dxf/tests/test_native_text_geometry.py cad_photo_to_dxf/tests/test_portable_font_bundle.py tools/native_first/tests --junitxml=local-artifacts/drafting-rules/revision-011/regression.xml
.venv/bin/python maintenance/preservation_check.py
.venv/bin/python -m ruff check --config cad_photo_to_dxf/ruff.toml tools/drafting_rules
.venv/bin/python -m compileall -q tools/drafting_rules
.venv/bin/python -m tools.drafting_rules.study --output local-artifacts/drafting-rules/revision-011/real-cell
```

安装、启动、74 项合跑和主程序 smoke 是 ce89a8d 的既有证据，本轮没有改依赖或生产入口。
0.1.1 真实 study 的逐项结果与保留的 0.1.0 报告一致，版本比较记录包与实现摘要变化，语义变化为空。
同一个镜像表线合成 DXF 用 ce89a8d 的原始适配器/引擎重放得到 6 PASS；当前版得到 5 PASS / 1 FAIL，准确拒绝错误的世界位置。
该反例的原始文件在本机忽略目录，紧凑报告和真实版本比较在 `evidence/v0.1.1/`，没有改旧报告或基线吸收差异。
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

本版逐项数值、句柄和失败原因见 [正常报告](evidence/v0.1.1/edited.report.json)、[越界失败报告](evidence/v0.1.1/overflow.report.json)、
[旁及修改失败报告](evidence/v0.1.1/unrelated-change.report.json)、[判定变化](evidence/v0.1.1/comparison.json) 和 [运行摘要](evidence/v0.1.1/study.json)。
另见 [镜像表线版本差异](evidence/v0.1.1/coordinate-version-comparison.json) 和 [真实单元格版本比较](evidence/v0.1.1/real-version-comparison.json)。0.1.0 的原报告保留未改。
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
当前实例支持离线开发、局部真实 DXF 生成与检查；SAMR 的官方元数据和标题栏公开预览已实际读取成功，字体正文由来源版权政策限制。
保存草稿不等于发布或新任务恢复验证；需在环境设置中审阅并保存，再发布环境。未验证新实例恢复。
