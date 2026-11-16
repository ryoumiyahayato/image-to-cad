# G29 当前隔离入口

G29直接文字确认已停用。实际LibreCAD发现一次Qt已接受的文字候选新增遮挡，内容事务已撤销。最终入口只作查源、显示建议和受控外部CAD回接。按钮及回调均不能直接接受文字建议；旧`local_repair.py accept`不作为G30准入路径。

```powershell
& 'D:\programs\Image-to-CAD\.venv-gui-check\Scripts\python.exe' `
  'D:\programs\Image-to-CAD\goal29-region-review\experiments\goal27_28\project_entry.py' `
  'D:\programs\Image-to-CAD\goal29-20261028\b\region-work\dev08-region.icreview' `
  --actor AGENT_REVIEWED
```

后续编辑先另存工程副本，导出到新的空目录。在实际CAD修改并核验完整邻域后保存D1，再用“外部保存回接”选择该D0/D1、检查全部差异、明确接受。关闭并新进程重开工程后再导出；不得从历史FinalStructure重建当前CAD。

显示复用现有ezdxf几何与项目LFF文字路径。仅支持已核验字体的平面、基线左对齐明文TEXT；不支持的字体/布局、MTEXT及缺字拒绝预览。手形平移仍是必要操作，不能凭局部窗口裁切断言全文或邻域无碰撞。入口属于实验候选，不是生产GUI。范围、失败和最终产物见仓库根目录`GOAL29_HANDOFF.md`。

## G27–G28 历史入口

当前跟进修订见[FOLLOWUP_ROUTE.md](FOLLOWUP_ROUTE.md)及[FOLLOWUP_RESULT.md](FOLLOWUP_RESULT.md)。从`g2728-relation-followup`运行入口，避免使用不认识候选引用的旧版代码重新保存新工程。

```powershell
& 'D:\programs\Image-to-CAD\.venv-gui-check\Scripts\python.exe' `
  'D:\programs\Image-to-CAD\g2728-relation-followup\experiments\goal27_28\project_entry.py'
```

“外部保存回接”依次选择真实D0和外部保存D1。预览分别显示内容复核与来源关系复核。首次明确关系降级会计数；接受后保留`prior_confirmations`，引用旧确认所在state/member。`resolve_confirmation`可读原source_evidence及actor。当前候选没有自动来源权限，不宣称跨保存身份。没有对应时，`unresolved_relation_refs`保留失效记录。

“查看来源候选及失效”可查看原确认和历史裁片；该图明确标为历史证据。选择“重新读取”才调用既有来源校验并重新读取源区域。确认其他成员的局部修复不清除这些候选和失效记录。重复未变的候选仍显示在工程中，但不再作为新关系复核项；新增复制、内容变化或失效仍提示。

以下为前一批修订的历史入口和说明。

2026-10-27独立复核修订入口见[REVIEW_FIX_ROUTE.md](REVIEW_FIX_ROUTE.md)，本批结果见[REVIEW_FIX_RESULT.md](REVIEW_FIX_RESULT.md)。三项边界修复后，新增当前CAD局部文字修复窗口；下方旧命令和旧结果保留历史适用范围。

```powershell
$py = 'D:\programs\Image-to-CAD\.venv-gui-check\Scripts\python.exe'
$lab = 'D:\programs\Image-to-CAD\g2728-review-fix\experiments\goal27_28'
# 打开新窗口后选择工程。先另存副本，选择当前TEXT及来源区域，再预览、确认、保存。
& $py "$lab\project_entry.py"
# 自动化GUI操作显式标为AGENT_REVIEWED；真人操作默认HUMAN_REVIEWED。
& $py "$lab\project_entry.py" '<工程副本.icreview>' --actor AGENT_REVIEWED
```

窗口导出当前CAD；不会从旧FinalStructure重新导出。源PDF/图像通过已有ReviewProject校验并重新读取邻域。接受只修改选中TEXT字符串，保持位置、字号、颜色及其他成员；一次确认只授权该局部操作。已有模糊关系继续隔离，不凭几何相同证明历史身份。来源邻域包含padding，记录实际读取范围。保存后的当前成员关系与来源观测分开保留。

CLI也可使用`local_repair.py preview --project ... --member ... --source-uuid ... --text ... --output ...`生成预览，查看后用`local_repair.py accept --project ... --preview ... --actor AGENT_REVIEWED`接受。此处member是用户明确选中的当前工程成员，source-uuid是明确选择的历史来源区域；它们不进入外部差异匹配器。

R1幂等按已接受事务及有效基线判断。R2检查传递引用块及其样式；缺块、循环块、嵌套不支持实体拒绝回接。R3保留MTEXT背景范围、颜色名和透明字段；多栏MTEXT暂不支持。没有实现任意DXF特征或全页重处理后的合并。

只用于独立候选。正式GUI不识别扩展工程。原ReviewProject的来源、cache11、文字校对记录和校对图保留在同一ZIP；external-cad扩展保存当前CAD和可撤销事务。原始FinalStructure表示历史观测，当前编辑几何由扩展保存。

## PowerShell 命令

```powershell
$py = 'D:\programs\Image-to-CAD\.venv-gui-check\Scripts\python.exe'
$lab = 'D:\programs\Image-to-CAD\goal27-28-a\experiments\goal27_28'
$out = 'D:\programs\Image-to-CAD\goal27-28-20261027'

# 真实文件差异；无目标句柄或预期文字参数
& $py "$lab\cad_delta.py" "$out\b\dev08\D0.dxf" "$out\b\dev08\D1.dxf" --output "$out\a\dev08-recheck.json"

# 新工程要求不存在；D0必须是该run中的实际生产导出
& $py "$lab\reconnect.py" create --run 'D:\programs\Image-to-CAD\goal25-20261026\runs-final\DEV-08' --d0 "$out\b\dev08\D0.dxf" --project "$out\a\new-dev08.icreview"
& $py "$lab\reconnect.py" preview --project "$out\a\new-dev08.icreview" --before "$out\b\dev08\D0.dxf" --after "$out\b\dev08\D1.dxf" --output "$out\a\new-preview.json"

# 先读取preview中的delta、资源和冲突，再接受；本轮实际使用AGENT_REVIEWED
Get-Content "$out\a\new-preview.json"
& $py "$lab\reconnect.py" accept --project "$out\a\new-dev08.icreview" --preview "$out\a\new-preview.json" --actor AGENT_REVIEWED
& $py "$lab\reconnect.py" export --project "$out\a\new-dev08.icreview" --directory "$out\a\new-export"

# 撤销只回退本工程的上一接受事务
& $py "$lab\reconnect.py" undo --project "$out\a\new-dev08.icreview"

# 仅本轮局部反例；临时目录必须使用新路径
& $py -m pytest "$lab\test_reconnect.py" -q --basetemp "$out\a\new-test-temp"
```

G26 source scene创建须显式加`--source-scene`。状态记录`G26_SOURCE_SCENE_NOT_PRODUCTION_GEOMETRY`，不能据此宣称生产页完成来源几何整合。

`edit-text --project ... --member ... --text ... --actor AGENT_REVIEWED`只改当前工程的一项原生文字，用于验证本轮内部/外部分叉冲突。member是当前工程成员，不是外部匹配器的答案参数。

## 读取结果

- `mappings`：内容对应。`identity=NOT_PROVEN`不证明历史实例。
- `changes`：字段变化及原始标签差异。包括真正编辑和有实际影响的保存损失，不能全部叫用户编辑。
- `serialization_or_subresolution`：保留小数差异与未引用表记录。功能等价不等于原始值相同。
- `removed_or_unmatched`、`added_or_unmatched`：快照中缺失或新增；不编造MOVE、复制或拆合历史。
- `duplicate_groups`、`ambiguous`：重复计数或多候选。未变的相同内容不需要逐个确认，但也不恢复实例身份。
- `document_changes`：图层可见/冻结/锁、有效颜色、字体/线型、坐标系和块。
- `source_records_lost`、`missing_dependencies`：来源丢失和实际依赖问题。

原始D0/D1保持本地，只读。坐标精度与边界见ROUTE.md。所有历史来源对应只是候选；当前自动来源修复全部关闭。接受外部结果不表示来源追溯完成。

已有首次 DXF 和另存件时，可用同一个比较入口生成独立来源记录。

```powershell
& $py "$lab\cad_delta.py" $before $after --retain-source --output $sourceJson
```

`$sourceJson` 必须是新文件。`source_trace.baseline` 保存首次件的 XDATA、原对象属性和图层状态，`saved` 保存另存件实际读到的状态。`candidates` 是内容对应候选。重复项按组记录，未匹配项仍可按原句柄查阅。块内来源记录可查，块内成员对应未推断。需要完整几何和原始标签差异时，沿用不加 `--retain-source` 的比较命令。已有 `.icreview` 工程的历史与确认流程独立保留。

需要连同来源记录一起交付时，使用现有便携打包器。

```powershell
& $py "$lab\cad_delta.py" $before $after --portable --restore-layer-states --output $deliveryZip
```

解压整个 ZIP，在同一目录打开 DXF。图片引用使用相对路径，`FONTS.txt` 列出文字样式所需字体。`dependencies.json` 列出交付成员、图层和兼容性修复。省略 `--restore-layer-states` 会采用另存件的图层状态。启用时只在交付副本恢复同名层的开关、冻结和锁定。

包内 `*.source.json` 直接与交付的 DXF 对照。模型空间候选含交付句柄和内容。块内候选要求同名块、基点一致且内容双向唯一。歧义项保留供核查。首次 DXF 的来源记录保存在 JSON 中，`before` 记其文件名。交付不把候选写回 XDATA，也不证明历史对象身份。

接受是整份经预览的当前CAD事务；歧义对象一并保留并隔离来源操作。此原型没有逐对象混合合并界面。当前工程已偏离D0时，明确拒绝冲突或要求合并，不覆盖。重复已接受文件返回ALREADY_ACCEPTED、0确认。

工程保存使用同目录临时ZIP、实际读回、原子替换、版本检查与单文件互斥。坏CAD、缺资源、输入变化、旧预览或并发保存不覆盖最后可用工程。进程崩溃遗留`.lock`时须人工确认所属进程已退出后处理，本原型不偷清其他写者锁。

正式生产重新处理、跨编辑器、任意DWG编辑、完整历史身份恢复及真人净省时不由本入口证明。

## 2026-11-15：大量填充的回存对照与同批文件绑定

同一 CAD 内容另存后，HATCH 边界的小数序列化差异会令精确键失配。线段边界填充现在用保守的空间候选索引，随后仍调用原匹配判据；没有改变 0.001 mm 比较精度、来源身份或自动修复权限。曲线、空边界和超大坐标回退原来的穷举路径。`matching_diagnostics` 报告实际评分对数，不是已证明的对象身份数量。

`--retain-source` 和 `--portable` 生成的来源记录新增 `file_binding`。它绑定实际首次 DXF、实际记录目标 DXF 和引用图片的 SHA-256。修改或再次另存后应重新生成记录；不得把旧 sidecar 搭配新文件。可在 Python 中调用 `cad_delta.validate_source_record_binding(record, current_dxf, baseline_path=first_dxf)` 核查。旧记录没有绑定则明确拒绝这项检查，不因此删掉旧证据。

沿用已有 `--portable --restore-layer-states` 命令，仅修改新交付副本的图层状态、相对图片路径及既有白名单的属主兼容性修正，不改写工程几何、正文或 XDATA。恢复标志是显式操作，会采用首次件同名图层状态；用户有意改变图层时应先审查差异或省略此选项。它不能改变 LibreCAD 再次保存时的行为。

独立来源 JSON 保存原证据与当前内容对应候选，`historical_identity=NOT_PROVEN`、`source_automatic_operations=false` 不变。当前 DXF 仍是实际另存件派生的副本，不能从旧 FinalStructure 重建来覆盖用户编辑。新包中应同时保留未改动的首次件、实际另存件及同批依赖，便于审查文件级变化。
