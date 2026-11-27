# Image-to-CAD — 图片/PDF 重新生成可编辑 CAD

**研发版：`0.3.0-dev` · 整体产品 `LOCAL_NO_GO`；`main` 持续保存最新经过验证的有效开发源码，不是正式发行版。**

**本实验分支最新结果：[Issue #62 完整组件与数值边界](docs/native/ISSUE62_FINITE_COMPONENT_RESULTS_20261127.md)（2026-11-27）。** 真实原图 4 完整候选／0 新采用；独立保存审核和实际反例已交，原有效 436 主图保持。局部审核副本与开发探针结果不替代后续 #61／#62 联合普通整区验收。以下程序及主图说明属于既有交付，本实验没有生成新有效主图或 Windows 程序。

**[Windows 一页使用说明](docs/native/WINDOWS_CAD_QUICKSTART_ZH.md)** · [产品合同](docs/project/NATIVE_OBJECT_PRODUCT_BASELINE_20261120.md) · [当前任务](docs/project/CURRENT_TASK.md) · [项目状态](docs/project/PROJECT_STATUS.md) · [Agent 指引](AGENTS.md)

## Windows 程序与当前主图

**[本版程序下载入口：Windows #699 完整交付项](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45790101851/artifacts/15103796104)**。图纸、匹配字体及许可由配套结果包提供，私人图纸不在公开仓库发布。

1. 将该交付项中的完整恢复包解压到新目录，双击 **`Restore-Windows-portable.cmd`**，自动校验、解压并启动 `CADPhotoToDXF.exe`。另完整解压结果包，保留字体、许可与子目录。
2. 在软件启动页或文件菜单点 **“打开已有 DXF / 准备 CAD 字体…”**，选择 **`QUARTER_short_contact_text_17415ed.dxf`**。已有图纸无需重新识别；找不到 LibreCAD 时选择安装好的 `LibreCAD.exe`。
3. 点 **“准备 CAD 字体”**。若提示重新打开 CAD，先保存并完全退出 LibreCAD，再回软件重新检查；显示资源已准备后打开图纸。
4. 用 **File → Save as** 另存编辑副本。`S` 可直接双击改字；左侧 `S3` 是含两个 TEXT 的独立块，选中组查看块名，再在块列表选择同名项进入 **Edit Block** 改字；接线保持独立。整组移动／删除步骤见[一页说明](docs/native/WINDOWS_CAD_QUICKSTART_ZH.md)。

## 当前成果：完整短字符与贯穿图线分别编辑

普通整区主图 **`QUARTER_short_contact_text_17415ed.dxf`**，**197578 B**，SHA-256 **`497a521d1b079fba4b80b126d8096e4f859e588bc13827391f685fa03936dfe6`**。原 **432 个正式对象全部严格保持**，新增两个完整文字对象，最终 **434 正式对象／48 REVIEW**；既有 53 个图块保持，新增一个独立文字组块。

| 位置 | 最终主图实际恢复 | 完整性与剩余范围 |
| --- | --- | --- |
| C07 新路径末端、承接线以上 | 完整 `S`，一个可直接改字的 TEXT | 字符完成；原完整路径和承接线保持独立 |
| LAUNDRY 左侧短组 | 完整 `S3`，唯一实例图块内两个真实 TEXT | 整组完成；贯穿路径、三短划和承接线保持独立 |
| 修改前冻结的 LAUNDRY 右侧验证点 | 未采用字符对象 | 缺少已采用的独立贯穿路径承担者，未进入本次短字符补全阶段；不能称为该阶段 OCR 拒绝 |

Linux LibreCAD 2.2.1.6 已实际完成 `S → K7,03` 改字、左组 `S3` 整删、贯穿该组的完整路径整删，三份均普通保存、完全退出并以新进程重开。每份 433 个非目标正式对象、48 REVIEW 和全部 54 个块定义保持；两个删除严格通过，目标在原位无自身残片。改字仅目标字高与宽度系数发生精确五位小数回写，初始严格失败保留并单列，邻居比较未放宽。

[Windows #699](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45790101851) 的十一组 source／实际隔离 EXE 普通入口及已有字体、恢复、安装流程通过；本批新增小输入的 source／EXE 共八份实际编辑文件已下载后冷读通过。两个证据 ZIP 已实际下载并校验；**完整程序包本工作区未下载核验（`NOT_DOWNLOADED_HERE`）**，一次请求超时后保留[官方完整交付入口](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45790101851/artifacts/15103796104)，没有将元数据写成完整包字节核验通过。

主图执行提交 **`17415edf96fb611a40caa5c6495bca077cd23cc6`**，Windows／远端源码提交 **`338a9226cde9789570da2d19b2fcbb23c1ed0a5c`**，经 [PR #55](https://github.com/ryoumiyahayato/image-to-cad/pull/55) 正常合入 main **`f0519d2c7cbc945874c2c138136fb270cf629092`**；三个提交的完整 Git tree 均为 **`e75f4e35f1ac091f0fcad75825edee16a325f556`**。后续文档提交另列，不替代出图与 EXE 执行锚点。

**Windows 私有主图桌面 GUI 和工程师工时仍 NOT_RUN；CAD 保存格式、XDATA、INSERT `zscale=0`、字体别名和 REVIEW 往返仍 LIMITED；产品仍 `0.3.0-dev / LOCAL_NO_GO`。** 第三处仍需后续明确任务先补足独立图线来源责任，再评估完整字符组；本批没有扩展相邻细竖线、其他邻接网络、困难 EBB-3 或三行注释，也不把局部完成写成整片恢复。

方法、实际编辑与版本边界见[本批记录](docs/native/SHORT_CONTACT_TEXT_20261126.md)。

<details>
<summary>历史：三条短划、承接线纠正与 Windows #696（6a27c0f 阶段）</summary>

> 以下“当前／本批／下一步”属于 6a27c0f 阶段，按原执行事实保留；最新范围见上文。

## Windows：取得程序后打开已有 DXF

**[程序构建与下载入口：Windows #696](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45755563007)**。Artifacts 中选择 `CADPhotoToDXF-Windows-Verified-Delivery-f988424b9dcf697d42fac8244acb96abce2b4fc7`。主图与匹配字体由同次配套结果包提供，私人图纸不在公开仓库发布。

1. 下载完整恢复包 **`CADPhotoToDXF-0.3.0-dev-f988424-Windows-Complete.zip`**，解压到新目录，双击 **`Restore-Windows-portable.cmd`**。它使用包内完整程序 ZIP，自动校验、解压并启动 `CADPhotoToDXF.exe`，无需分卷或手工命令。另完整解压结果包，保留 DXF、匹配字体、许可和子目录。
2. 在软件启动页或文件菜单点 **“打开已有 DXF / 准备 CAD 字体…”**，选择 **`QUARTER_laundry_short_strokes_6a27c0f.dxf`**。已有图纸无需重新识别；找不到 LibreCAD 时，只需选择安装好的 `LibreCAD.exe`。
3. 点 **“准备 CAD 字体”**，软件完成目录和资源准备。若显示“需要重新打开 CAD”，先保存并完全退出 LibreCAD，再点“重新检查”。显示“已准备，可打开 CAD”后打开图纸；该状态表示资源准备完成，当前窗口显示需在打开后检查。
4. 在 LibreCAD 用 **File → Save as** 另存编辑副本。短划、长曲线和承接线可分别整删、整移；普通保存、完全退出后重开检查。具体操作与改字见[一页说明](docs/native/WINDOWS_CAD_QUICKSTART_ZH.md)。

## 当前成果：三条完整短划与干净的承接横线

普通整区流程已生成 **`QUARTER_laundry_short_strokes_6a27c0f.dxf`**：**196315 B**，SHA-256 **`eae5a316ff7ebcf7840a5a70ac0e395b7f91ccdaa6c7d76e8a62508ea4ee343c`**，最终 **432 正式对象／48 REVIEW**。本批从 `QUARTER_structure_contacts_26b1b6e.dxf` 的 430 个正式对象接续：**427 旧对象严格保持，2 条旧承接 LINE 替换为 1 条完整 LINE，1 条完整 LAUNDRY 路径更新有证末端与接收对象绑定，新增 3 条完整独立短划 LINE**。所有旧对象均有明确去向。

| 范围 | 最终保存主图实际恢复或纠正 | 仍待修什么 |
| --- | --- | --- |
| LAUNDRY 三条交叉短划 | 各为一条完整独立 LINE；上下端点均来自原笔画，交叉位置与长曲线分别承担编辑责任 | 相邻细竖线、S／S3 字符及其他尚未采用的笔迹 |
| 两条旧承接横线 | 全长与两端核实为同源重复，撤回旧近似，由一条有完整来源的有限 LINE 承担；长曲线实际末端和绑定一起更新 | 其他邻接网络；本批未声称整片恢复 |

C07 新路径、LAUNDRY 上方长曲线、圆字、文字、真实白缝和真实平行双线保持。原曲线前 51 个顶点及原有表示保持，只有末端按来源重新绑定有限承接线；没有为了保持旧数量留下重复横线。

Linux LibreCAD 2.2.1.6 已实际完成三项操作：**删除整条 LAUNDRY 路径、删除左侧一条短划、整体移动最终承接线**。每份均普通保存、完全退出并由新进程重新打开；独立冷审计为 **`PASS_2D_EDIT_ISOLATION_WITH_FORMAT_LIMITATIONS`**。各副本其余 **431 正式对象、48 REVIEW 和全部 53 图块**保持：删曲线后三短划与圆字仍在，删短划后另两条与曲线仍在，移动承接线后原位没有同源旧横线残留。真实独立交叉线保留，不能把窗口中仍有邻居误判为删除不净。

正式主图保留普通流程生成字节，GUI 编辑副本另存。**Windows 私有主图桌面 GUI 与工程师工时验收仍 NOT_RUN**；XDATA、INSERT `zscale=0`、字体别名、REVIEW 和格式往返继续 **LIMITED**，产品仍 **`0.3.0-dev / LOCAL_NO_GO`**。

[Windows #696](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45755563007) 的十组 source／实际隔离 EXE 普通入口、恢复、字体和安装／启动／卸载通过。第十组实际触发三条完整短划、两旧承接线到一条完整接收线的替换、有限末端绑定，并保护真实双线和白缝；五对象各移动／删除一次，source 与 EXE 共 **20 份实际 Windows 保存副本**已下载后冷读通过。完整交付包 **`CADPhotoToDXF-0.3.0-dev-f988424-Windows-Complete.zip`** 已实际下载：**418173918 B**，SHA-256 **`e2dece2dee14ac32e7381f41aa8ac4d98da75def600d0a633347511a9ef484b4`**；1478 个程序文件和 98 份随包 Python 源码逐字节核验，其中 80 份属于 native-build 声明资源。

主图执行提交 **`6a27c0f031f2e2d26ebdf4b485d85d7a42262ee0`**，Windows 执行提交 **`f988424b9dcf697d42fac8244acb96abce2b4fc7`**；两者完整 Git tree 均为 **`761e9a41b76120161c0ce01d61927946959467ff`**。这是相同源码树的两个提交。[PR #54](https://github.com/ryoumiyahayato/image-to-cad/pull/54) 已正常合入 main **`bb165884e16ac61a08ad46c337cb317d63445e8c`**，合并树也与该执行树相同。后续文档提交不替代出图／构建锚点。

详细规则、旧对象替代关系和证据边界见[本批记录](docs/native/LAUNDRY_CROSS_STROKES_20261126.md)。


</details>

<details>
<summary>历史：完整接触路径与 Windows #694（26b1b6e 阶段）</summary>

> 以下“当前／最新／本批”仅指 26b1b6e 历史阶段。当时三短划与旧近似重叠尚未完成；当前结果以上文为准。

## 历史 Windows 入口：#694


**[程序构建与下载入口：Windows #694](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45673521187)**。在 Artifacts 中选择 `CADPhotoToDXF-Windows-Verified-Delivery-26b1b6e14106726fd9b1f66a747e8be16320b815`。主图与匹配字体在同次配套结果包中取得，私人图纸不在公开仓库发布。

1. **下载本次完整恢复交付包 `CADPhotoToDXF-0.3.0-dev-26b1b6e-Windows-Complete.zip`，解压到一个新目录。** 双击解压后的 **`Restore-Windows-portable.cmd`**；包内已有完整程序 ZIP，它自动校验、解压并启动 `CADPhotoToDXF.exe`，不需要分卷或手工命令。另解压同次结果包，保留主 DXF、匹配字体、许可及原有子目录。若使用其他普通便携 ZIP 或历史分卷，步骤见[一页说明](docs/native/WINDOWS_CAD_QUICKSTART_ZH.md)。
2. **在软件启动页点击“打开已有 DXF / 准备 CAD 字体…”**，选择结果包中的 DXF。文件菜单也有同一入口，已有图纸无需再次识别。应用会检查该图纸所需字体并查找 LibreCAD；找不到时点击“选择 LibreCAD…”，选择安装好的 `LibreCAD.exe` 即可。
3. **点击“准备 CAD 字体”。** 软件使用随包固定资源完成准备；不需要选择字体目录或手工修改 CAD 配置。若显示“需要重新打开 CAD”，请先保存图纸、完全退出 LibreCAD，再点“重新检查”。只有显示“已准备，可打开 CAD”后才点击“在 LibreCAD 中打开”。“已准备”表示资源准备完成，不是已验证当前 CAD 窗口显示。
4. **在 LibreCAD 中先用“File → Save as”另存编辑副本。** 点击曲线主体选中整条路径，用 **Tools → Modify → Move / Copy** 移动并选择 **Delete Original**，或用 **Tools → Modify → Delete selected** 整条删除。圆字仍可通过块列表 **Edit Block** 修改内部 TEXT；从 **Drawings** 返回主图。普通保存后完全退出并重开副本。`Ctrl+Shift+S` 是 Save All，不是另存为，详见[一页说明](docs/native/WINDOWS_CAD_QUICKSTART_ZH.md)。

## 历史成果：两条穿过接触笔迹的完整独立路径进入主图

最新主图 **`QUARTER_structure_contacts_26b1b6e.dxf`**，**195818 B**，SHA-256 **`b7bbaa765575d1d7e89ef9c7ee0185aaeac22768b84cb09ea8026e956e01b144`**。普通 `native-objects` 整区流程复用已核验原始观察并重算受影响阶段。基线 426 个正式对象全部严格保持，新增两条目标路径、一条自然适用的 E 圆相关路径及一条独立承接 LINE，最终 **430 正式对象／48 REVIEW**。

| 目标 | 最终主图实际恢复 | 完整性与仍待修范围 |
| --- | --- | --- |
| C07 右侧 F 圆上方缺线 | 从 F 圆来源端口穿过 S 形接触区，抵达独立承接线；一条完整 LWPOLYLINE，承接 LINE 单独保存 | 指定路径完成；原 C07 主曲线、左上路径和 F 圆字保持。S 字符及其他支路仍待修 |
| LAUNDRY 左侧 D 圆向右、通往 S3／结构线一带的缺线 | 从 D 圆来源端口经过短划及接触区，抵达已有独立承接线；一条完整 LWPOLYLINE | 指定路径完成；S3、三条短划、其他邻线及旧近似重叠仍待修 |

两处的起圆、共享墨迹、竞争路径和真实终点均经过来源核对及最终保存文件冷读。圆字、文字、承接线和既有路径保持独立；真实白缝保持。旧近似对象 `LINE-16db792c3c06` 的完整来源责任尚未证明，本批保留待修；“路径完成”不表示整片网络、所有字符或全部重叠已解决。详细范围见[本批记录](docs/native/STRUCTURE_CONTACT_PATHS_20261126.md)。

Linux LibreCAD 2.2.1.6 已实际整体移动 C07 目标路径、整体删除 LAUNDRY 目标路径，并分别普通保存、完全退出、新进程重开；独立冷审计状态：**`PASS_2D_EDIT_ISOLATION_WITH_FORMAT_LIMITATIONS`**，每份其余 429 正式对象、48 REVIEW 和全部 53 图块保持。Windows 私有主图 GUI 仍 **NOT_RUN**。XDATA、INSERT `zscale=0`、字体别名、REVIEW 和格式往返限制仍 **LIMITED**；正式主图保留原始生成字节，GUI 副本另存。

同版 [Windows #694](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45673521187) 九组 source／实际 EXE、恢复、字体及安装／启动／卸载均通过；新小输入实际触发接触区划分和结构线终接，保存后的整体删移与白缝另行冷读。完整包实际下载 **418085481 B**，SHA-256 **`5044c5d885183245ecdf09358950690b60d7b90f2e49011939d2913e630da0fa`**；1475 个程序文件与 77 份随包源码已核验。主图与 EXE 同绑 **`26b1b6e14106726fd9b1f66a747e8be16320b815`**，[PR #53](https://github.com/ryoumiyahayato/image-to-cad/pull/53)；main 合并回执：**`5ed7490e7c0c5ddfdaf002496256f2e5477c816a`**。后续文档提交不替代出图／构建锚点。


</details>

### 历史：圆字对象与 LAUNDRY 指定接头（3f51048）

上一批 `QUARTER_circle_characters_3f51048.dxf` 为 426 正式对象：三个固定目标 D/E/D 圆字完成，六处旧裸圆同 ID 升级，LAUNDRY 原长曲线补齐有证末段。其实际改字、圆字整删与路径整删、Windows #692 和保存限制均按原执行版本保留，见[圆字阶段记录](docs/native/CIRCLE_CHARACTER_COMPLETION_20261125.md)。该阶段的 C07 缺线未完成结论属于历史；本批只更新上表两条指定路径，未改写其他旧待修项。

## 我们要得到什么

使用者提供扫描图片、TIFF 或 PDF，软件利用**固定规则、图像算法、OCR、机器学习和必要的图形约束**识别并重新绘制，输出具有合理对象边界的二维 DXF：

- 完整的 LINE、ARC、CIRCLE、LWPOLYLINE 等独立线条与曲线；
- 可整体操作的门、房号、符号和墙段；内部用合理的原生图元组织；
- 内容正确、可编辑的 TEXT/MTEXT；字体不要求与旧扫描逐像素完全一样；
- 保留真实开口、短线、邻线、图框、标注、LOGO/签名等必要内容；
- 确实无法辨认时，在正式绘图区留白并**明确标记来源与待修位置**。

**不要求算法理解工程语义；识别与“读懂”的概念不同。** 能按有依据的规则恢复完整、可删改的对象，即是有效的技术路径。不能把像素小碎线、HATCH 色块或整个背景图像冒充完整 CAD 对象。

交付以**实际保存 DXF**为准，重新打开之后需要能够删、移、改，且旧对象/邻居保持。像素覆盖率、测试数和实体数量均只是诊断，不代表产品成功。

## 历史：圆形标记阶段的实际实现范围（2026-11-22）

**本轮已在普通整区主图恢复圆形标记。** 最新执行提交为 `38a77a487784763d0919baaf718744aa446421b0`，主 DXF 已正式保存发布并通过自身来源冷读。同提交 Windows 源码、实际 EXE、安装／卸载及下载产物独立来源冷读均通过；主图旧对象与跨版本独立后审也已通过。版本和实际文件统一见[本轮圆形标记记录](docs/native/CIRCULAR_MARKERS_20261122.md)。

完整标记使用每实例唯一的 INSERT／BLOCK，内含真实 CIRCLE 和可改内容的 TEXT，外接线保持独立。字符不可靠时只恢复有证圆边并单列部分组成，开放边界不强补整圆。普通入口、保存冷读、来源核对和实际 DXF 预览共用同一表示，不输入案例答案。

| 最新 38 实际主图结果 | 数量与含义 |
| --- | --- |
| 新增完整验收标记 | **19**，圆字齐备且无未决的已观察外部端点关系 |
| 部分组成 | **17＝15 个仅圆边＋2 个圆字齐备但外接关系待修** |
| 几何尚未恢复／全部待修位置 | **9／26**，按圆位 ID 去重，不再累加 5 个端部记录 |
| 实际圆字组成／仅圆边结构量 | **21 个 CIRCLE＋TEXT 图块／15 个独立 CIRCLE**；21 不等于完整验收数 |
| 原有 377 对象去向 | **366 精确保留＋11 条路径有证增加 14 个短末段**；最新实际主图逐项独立审计通过，退场／无法解释丢失均为 0 |
| 实际顶层正式对象／REVIEW | **413／48**，不把圈与字分别累加为两个成果 |

8 个真实代表覆盖 C07 两端、单／多接线、字符不清和空内域，含 1 个先冻结后验证的留出位置。原图／旧版／实际新版对照已打开检查，全部 36 个新圆对象做来源冷读；普通 `O/0`、门弧、既有路径、PANTRY 与墙组纳入保护。原版缺失的部分枝线与其他内容继续保留待修，未声明整个邻域或工程网络已恢复。

LibreCAD 实际操作绑定 **e2 主图**：移动 CM-01 的圆字整体并将 F 改为 K，CM-02 保持；另删除 CM-03 的圆字整体。完成普通保存、完全退出、新进程重开，共 2 个操作实例＋1 个隔离对照、13 张原始截图。全部正式对象另做保存二维内容检查；这不等于全部标记均已手工操作。最终 38 与 e2 的全 413 实体／块成员及 48 REVIEW 对应已通过，复用原 GUI 证据，不改其执行版本，也不称全部来源证据文件逐字节相同。

端部恢复保留旧路径全部顶点、bulge 与来源，仅增加原图直接黑墨支持的极短直段。新白缝保护进一步限定在已确认圆旁的旧 LINE 短尾：证明完整白条、独立外线端帽和圆边责任后才以同 ID 截回；已支持的局部环内重叠保持。未满足窄范围条件的对象不据此判定安全；显式发现角接、额外短枝或来源责任不足时按对应分支待修。白缝修复的 200 项针对性回归通过；最新实际主图未触发额外白缝截回或该类待修（均为 0），没有因这项保护扩大本批旧对象修改范围。

本轮从上一轮 `6225980` 的 377 对象基线接续，历史见[上一轮记录](docs/native/QUARTER_NATIVE_EXE_20261122.md)。`e9cc336` 的字形布局／编码失败、`787de72` 的 Windows 字体解析失败、`6710afc` 的接线间隙和 e2 的真实白缝失败分别保留，不被新成功覆盖。

LibreCAD XDATA 丢失、INSERT `zscale=0`、字体／样式变化等保存限制继续 **LIMITED**；旧三行注释失败结论不改写。当前仍为纸面毫米，整体产品 `LOCAL_NO_GO`，工程师完整修图工时验收 `NOT_RUN`。源码已通过 PR #46 正常合入 main `1147420cf278b29f58127ae3c3697209a527115e`；实际主图／Windows 仍绑定 38，版本详见[当前任务](docs/project/CURRENT_TASK.md)。

## 从源码运行

本仓库的原生开发环境已在 **Linux x86_64 / Python 3.12** 的指定依赖与字体/模型条件下验证。具体输入命令、资源校验与无缓存运行使用 [docs/native/REPRODUCE.md](docs/native/REPRODUCE.md)，不要根据旧临时路径执行。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r cad_photo_to_dxf/requirements-native.lock
.venv/bin/python maintenance/check_native_resources.py
.venv/bin/python cad_photo_to_dxf/main.py
```

已有受控来源检查点时，正式无界面入口可使用 `--connection-checkpoint PATH`，配合原有 `--input`、`--roi`、`--dpi`、`--output`。JSON 绑定原图、既有 DXF／来源账本、保存的文字观察和 1—8 个局部窗口；manager 捕获后重新校验哈希与参数，worker 仍执行保存、冷读和来源审核门禁。它不是旧采用白名单，也不自动调用 OCR 或扩大到全区转换。该检查点模式用于明确授权的局部任务；本次普通整区没有使用它。私人输入和大型模型不进入公开仓库。

首选交付 DXF，比例来源不足时使用纸面毫米；不能把 DPI 冒充工程设计比例。Windows 构建与原生检查沿用已建立的流程，基础用法见 [Windows 检查说明](docs/native/WINDOWS_NATIVE_SMOKE.md)，当前短字符能力的实际软件验证见[本批记录](docs/native/SHORT_CONTACT_TEXT_20261126.md)，接触路径历史保留原执行记录。真实工程图的 Windows 用户验收、Android APK、DWG 全流程和跨 CAD 完整性仍待验证。

## 研发及合并原则

每轮以一项**中等规模、能增加实际内容**的任务推进：代码＋真实 DXF＋邻居保护/必要反例＋冷读/编辑检查。正确结果进入 `main`；失败研究保留在私有证据和临时非默认代码，不作为产品成果。同步前核对远端 HEAD、CI 和当前实际 DXF；合并之后清理冗余分支，不强推、不重写历史、不公开受限原图或字体模型。

当前目标仍是冻结旧图连续四分之一区域的完整内容恢复。最终人工验收要求包括全部遗漏补绘、核对、纠错：**修图总人工时间不超过同范围、同质量从零重画的一半**。尚无工程师实测，不能声称达到目标。

历史日期状态与旧像素/HATCH研究仅作证据参考，不再决定下一步产品研发优先级。
