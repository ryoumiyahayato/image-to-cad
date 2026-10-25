# 可执行制图规则原型 0.1.1

这是一个**独立、只读的检查器**，不导入正式 GUI/转换链，不修改 DXF，不自动补线，不依赖通用 AI。
它处理中国大陆工程图图签、表格和普通文字中可观察的表示与几何合同，不判断完整工程语义。

## 运行

在仓库根目录，Python 3.11+：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r cad_photo_to_dxf/requirements.txt -r cad_photo_to_dxf/requirements-test.txt -r tools/native_first/requirements.txt
export QT_QPA_PLATFORM=offscreen
export XDG_CACHE_HOME=/workspace/.cache
export PYTHONPATH="$PWD/cad_photo_to_dxf"
.venv/bin/python -m pytest -q tools/drafting_rules/tests
.venv/bin/python -m tools.drafting_rules.study --output local-artifacts/drafting-rules/example-01
```

`study` 要求全新输出目录，防止覆盖旧证据。它复用现有真实 PDF、现有转录观察和生产导出器；不重新 OCR。
产生真实局部 DXF、程序编辑后的 DXF、超长文字反例、无关轮廓移位反例、来源裁片、JSON 报告和版本比较。
`test_engine.py` 是纯数据规则测试；`test_dxf.py` 是合成 DXF 保存读回测试；`test_real_pdf.py` 是真实 PDF 局部测试。

检查另一个具有来源映射的保存文件：

```bash
.venv/bin/python -m tools.drafting_rules.cli validate \
  --before local-artifacts/drafting-rules/example-01/baseline.dxf \
  --after local-artifacts/drafting-rules/example-01/edited.dxf \
  --source cad_photo_to_dxf/tests/real_regression/assets/sources/warehouse-electrical-vector.pdf \
  --evidence local-artifacts/drafting-rules/example-01/evidence.json \
  --output local-artifacts/drafting-rules/example-01/cli-report.json --strict
```

退出码：0＝已执行项没有失败；1＝有失败，或 `--strict` 时有弃判；2＝输入错误。
没有 `--strict` 的退出 0 **不表示所有合同通过**，必须查看 `ABSTAIN` 数量。报告保留每个目标、原因、来源分类和数值。
文件摘要不符、陈旧证据、非法 JSON/schema 均不能继续判通过；输入错误也写入报告。

```bash
.venv/bin/python -m tools.drafting_rules.cli compare \
  local-artifacts/drafting-rules/example-01/edited.report.json \
  local-artifacts/drafting-rules/example-01/overflow.report.json \
  --output local-artifacts/drafting-rules/example-01/cli-comparison.json
```

比较要求同一个知识包 ID、来源摘要、页、范围和坐标单位；记录规则版本、包/实现/字体摘要、运行时版本、DXF 摘要和逐项变化。
修改规则版本或阈值时，用 `--pack` 传入完整新清单，对同一组文件重跑，再比较两份报告。

## 可执行合同与边界

| 规则 | 分类 | 真实行为 | 缺少证据时 |
| --- | --- | --- | --- |
| editable-text | PRODUCT_REQUIREMENT | 指定成员必须为默认可见 TEXT/MTEXT，字符与给定转录一致 | 无目标映射弃判；不自行证明转录正确 |
| cell-fit | EXPERIMENTAL_HEURISTIC | 复用现有 LFF 度量，检查墨迹范围越出指定矩形单元格 | 未知字体/字形、MTEXT、特殊对齐/倾斜/任意旋转弃判 |
| source-glyph-exit | PRODUCT_REQUIREMENT | 检查完整归属声明中原字形成员是否仍可见 | 无完整成员映射弃判；不能发现未映射或重新创建的旧笔画 |
| background-protection | PRODUCT_REQUIREMENT | 背景与正文成员独立，实体及已解析资源指纹不变 | 未知背景归属、BLOCK/IMAGE/HATCH 等依赖未解析弃判 |
| table-line-parity | EXPERIMENTAL_HEURISTIC | 对完整独立表格图层做来源线段多重集匹配，发现新增/重复/缺失/端点延伸 | 无来源线段、未知曲线等弃判 |
| edit-isolation | PRODUCT_REQUIREMENT | 除明确允许的改动/新增句柄外，模型空间成员及资源不变 | 无编辑范围、未知嵌套资源弃判 |

线段先从 OCS 转到 WCS，再在世界 XY 平面匹配；离开该平面的多段线弃判。镜像坐标不能因本地数字相同而误判位置保持。
匹配不吸附、不桥接、不合并；源本身有重复线时保留重复数量。一段拆成两段也会违反这个**窄表示合同**，不等于已经证明缺墨迹。
容差 `1e-6` 是在输入声明的 CAD 坐标单位下用于数值比较的试验参数，不是国标字号、线宽或容许间距。
普通文字暂只验证真实表示、给定字符串和单元格范围；**字形碰撞、字号风格、对齐规范仍是候选，未实现自动裁决**。

## 来源与正式标准研究

机器可读清单见 [pack/manifest.json](pack/manifest.json)，输入合同见 [pack/evidence.schema.json](pack/evidence.schema.json)。
来源身份、页号、选区、单位、转录权威、前后 DXF 摘要必须显式提供。映射完整性是调用者的证据声明，不由 JSON 自行证明物理真实性。
报告中的通过只针对声明的成员和支持范围，不是整页质量认证。

- 已阅读核实的规范性项目来源：`PRODUCT_INTENT_AND_KNOWLEDGE_PACKS_ZH.md` §2、§4.3–4.6、§8；`ACCEPTANCE_GATES.md` G2/G4/G5。
- 已实际检查真实来源：仓库 `warehouse-electrical-vector.pdf` 第 2 页、136 DPI 局部。该单元格含“专业负责人”、上下两行英文、右侧签名及邻接格线；英文边界框有交叠，不能直接判字形碰撞。
- 正式依据：已阅读 [GB/T 10609.1-2008 官方公开预览](https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=0F8577CB9AB82D5819048A87920CABAB) 全部 5 页，封面版本相符，官方详情标为“现行”。§3.1 的图签存在性要求登记为 `OFFICIAL_STANDARD` 候选；缺少完整页面清单与可靠图签归属时不执行裁决。
- 同时核实 §3.3 的签字字体例外、§4.1 的常用分区及可增减条件、§5.1–5.2 和资料性附录 A。没有把示例布局当作所有建筑/电气图签的固定模板。
- [GB/T 14691-1993 官方记录](https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=44F8A8E5B9D37004AB8445B42992B1BC) 标为“现行”，但官方因采标版权不提供正文。其 `verified_full_text: false`、`clause: null`，只保留来源研究记录，不标成正式候选规则。没有编造字号条文。
- 尚无可执行 `OFFICIAL_STANDARD` 规则；加载器对正式分类的**候选和已实现规则**都要求核验全文、版本与条款。原来的 CONNECT 403 是历史访问结果；本轮已成功读取 SAMR，住房城乡建设部入口重试返回代理 502，未核实其条文。

源 PDF 仅沿用项目内研究授权，没有新增公开再分发许可；不复制原件、截图或大 DXF 进本交付。运行产物留在忽略的 `local-artifacts/`。

## 与现有系统的接口

`engine.evaluate(evidence, before_snapshot, after_snapshot, pack)` 只消费普通 Python/JSON 数据，无 CAD 或模型运行时依赖。
`dxf_adapter.snapshot(path)` 从**实际保存文件**重新读取成员与图层状态；复用 `app.ocr.librecad_lff.librecad_text_metrics`，不信任陈旧导出 bbox。
`cli.validate_files(...)` 先验证 schema 和 SHA-256，再调用适配器与规则。所有操作只读源文件，产物独占创建。

已有能力保持原入口：`ocr_layout.constrain_texts_to_table_cells`、`VerifiedCellTextSource`、`content_ownership.complete_verified_text_ownership`、
Logo/签名保护、`text_output_contract`、`review_text.ReviewLayoutGuard` 和 `export_final_structure_dxf`。
本包不复制其算法，不改变其阈值或旧基线；真实试验仅复用现有局部回归的候选注入和导出。
今后可写薄适配器把已验证归属证明映射到本输入合同；本版不扩充 FinalStructure、不新增生产 schema、不接入生产。

## 验收证据与未测项

见 [REPORT_ZH.md](REPORT_ZH.md) 和 `evidence/` 的小型结果与失败报告。
程序测试不能证明真人编辑成功；LibreCAD 打开、中文/英文/数字改字、移动、保存、完全关闭后重开、字体表现、撤销、Logo/签名稳定、DWG 往返均需分别验收。
本版未计真人节省时间，也未宣称实现整张图纸的自动修正。

## 真实来源证据适配

新增只读 `source_adapter` 和独立 `source_study`，不修改上述 0.1.1 原入口或报告。
它消费实际生产缓存、原 PDF 和保存 DXF，重放来源归属；完整正例可通过，明确残留失败，不完整来源继续弃判。
使用方式、原 W02 的实际残留失败、同页干净对照、逐项比较及保留弃判见 [来源适配阶段报告](SOURCE_ADAPTER_ZH.md)。
