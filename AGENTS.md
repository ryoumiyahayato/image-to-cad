# Image-to-CAD — Agent 执行入口

**当前开发主线：`main`，版本 `0.3.0-dev`，产品总体 `LOCAL_NO_GO`。**

本仓库的产品是 **扫描图片／PDF → 按证据和固定规则识别 → 重新构造完整、独立可编辑的二维 CAD 对象 → 实际保存 DXF**。**不以“理解工程语义”为必要条件**：可使用传统算法、规则、OCR、机器学习和可替换视觉模型；只要能正确重建和编辑，就不必证明模型理解了“墙”“门”或其他对象的工程意义。对象标签与模型置信度不是最终成果。

先阅读 [当前产品合同](docs/project/NATIVE_OBJECT_PRODUCT_BASELINE_20261120.md)、[当前任务](docs/project/CURRENT_TASK.md)、[状态](docs/project/PROJECT_STATUS.md) 和 [既有执行协议](docs/project/AGENT_OPERATING_PROTOCOL.md)。这些旧文档若将默认执行限制为“只审计并停止”或将 `main` 说成仅有 legacy，应以本入口和用户当前授权为准。

## 每轮工作应该交什么

- **一个中等规模的实际交付目标**：一种对象或一类共通缺陷，加上必要邻居与代表性负例；不要七项并行，也不要为了单个字形/字体无限实验。
- 从真实输入或已有可恢复的来源检查点修改代码，生成 **实际 DXF**，保存、独立冷读、渲染，并以原图和目标CAD（适用时）进行删／移／改／保存重开对照。
- 汇报本轮 **新增或修复了哪些完整对象、哪些旧正确内容保留、尚存何种漏项和编辑成本**；回归测试、OCR调用数、像素覆盖与报告页数不能取代这三项。
- 模糊、证据不足时明确待修，不伪造字符串、尺寸、接线或消失的内容；保留邻线、门洞、真实短划、Logo/签名和来源记录。
- 任务失败保存代码及反例，不无限调参；问题有可复用一般机制时修通用算法，不为单独样例写死答案。

## GitHub 与版本收口（2026-11-21 起的当前规则）

1. **`main` 是最新经过验证的有效开发版本，不是永久冻结的 legacy，也不等于正式 Release。** 整体产品仍可保持 `LOCAL_NO_GO`。
2. 一个有实际成果的任务完成后，及时推送；确认受影响测试、真实 DXF 行为、既有正确对象保护与适用 CI 通过，就把可用代码尽快快进或正常合并进 `main`。**不要求全部工程师 UAT 或产品 GO 才能合并已验证的开发代码**；在文档中保留准确的局部验收与未通过范围。
3. 验证失败的实验只能作为非默认诊断代码或恢复证据，不能将已知回归覆盖到 `main`。如果修复简单而必要，先在当前研发工作线上修 CI / 资源依赖，再合并；不为了绿灯删除真实测试或忽略 Windows 失败。
4. 保持分支最少：`main`＋**至多一个主要在研分支**；临时备份完成集成、远端读回后及时删除。已有研究末端先核对唯一提交及恢复引用后退役。不得强推或重写历史来掩盖失败。
5. 每次写入前核对远端 HEAD；新提交不允许覆盖其他代理的更新。遇到登录／权限阻塞，立即在私有持久存储保存 commit、补丁与恢复信息，不反复等待登录或 CI；可用连接器时再安全同步。
6. 私人扫描、原始OCR、专用字体/模型、未授权材料、密钥和实验ZIP不得加入公开仓库。真实图纸与大型证据保存在受控私有资料库。

## 当前阶段：完整短字符与独立贯穿路径（2026-11-26）

普通整区主图 **`QUARTER_short_contact_text_17415ed.dxf`**，**197578 B**，SHA-256 **`497a521d1b079fba4b80b126d8096e4f859e588bc13827391f685fa03936dfe6`**。原 **432 个正式对象全部严格保持**，新增两个完整文字对象，最终 **434 正式对象／48 REVIEW**；既有 53 个图块保持，新增一个独立文字组块。

C07 的完整 `S` 为一个 TEXT，LAUNDRY 左侧完整 `S3` 为唯一实例的两个 TEXT 组成图块；字组与完整接线分别编辑。右侧冻结验证点因缺少已采用的贯穿路径承担者，未进入本次短字符补全阶段，不能记成 OCR 采用拒绝或用别处成功替代。

Linux LibreCAD 2.2.1.6 已实际完成 `S → K7,03` 改字、左组 `S3` 整删、贯穿该组的完整路径整删，三份均普通保存、完全退出并以新进程重开。每份 433 个非目标正式对象、48 REVIEW 和全部 54 个块定义保持；两个删除严格通过，目标在原位无自身残片。改字仅目标字高与宽度系数发生精确五位小数回写，初始严格失败保留并单列，邻居比较未放宽。

[Windows #699](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45790101851) 的十一组 source／实际隔离 EXE 普通入口及已有字体、恢复、安装流程通过；本批新增小输入的 source／EXE 共八份实际编辑文件已下载后冷读通过。两个证据 ZIP 已实际下载并校验；**完整程序包本工作区未下载核验（`NOT_DOWNLOADED_HERE`）**，一次请求超时后保留[官方完整交付入口](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45790101851/artifacts/15103796104)，没有将元数据写成完整包字节核验通过。

主图执行提交 **`17415edf96fb611a40caa5c6495bca077cd23cc6`**，Windows／远端源码提交 **`338a9226cde9789570da2d19b2fcbb23c1ed0a5c`**，经 [PR #55](https://github.com/ryoumiyahayato/image-to-cad/pull/55) 正常合入 main **`f0519d2c7cbc945874c2c138136fb270cf629092`**；三个提交的完整 Git tree 均为 **`e75f4e35f1ac091f0fcad75825edee16a325f556`**。后续文档提交另列，不替代出图与 EXE 执行锚点。

**Windows 私有主图桌面 GUI 和工程师工时仍 NOT_RUN；CAD 保存格式、XDATA、INSERT `zscale=0`、字体别名和 REVIEW 往返仍 LIMITED；产品仍 `0.3.0-dev / LOCAL_NO_GO`。** 第三处仍需后续明确任务先补足独立图线来源责任，再评估完整字符组；本批没有扩展相邻细竖线、其他邻接网络、困难 EBB-3 或三行注释，也不把局部完成写成整片恢复。 当前操作入口见[一页说明](docs/native/WINDOWS_CAD_QUICKSTART_ZH.md)，实际范围见[本批记录](docs/native/SHORT_CONTACT_TEXT_20261126.md)。

## 历史：LAUNDRY 交叉短划与承接线重复表达（2026-11-26）

> 本节的“本批／下一步”属于 6a27c0f 阶段；保留历史事实，当前结果以上文为准。

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

共享交叉墨迹不等于合并编辑责任。完整短划须有独立自由端点、原墨迹连续性、正反向唯一交汇配对，以及另一条独立完整路径的来源责任。旧承接线去重须核对全长与两端；撤回后重新生成实际有限承接关系，并冷读检查改名残留、图块内 LINE 和 LWPOLYLINE 直段中的同源重复。真实平行双线、白缝和独立端部笔迹保持。ID、坐标和案例数量仅用于定位评估，不进入生产采用条件。

下一步从相邻细竖线、S／S3 字符和其他明确待修笔迹继续；本批三短划与指定两横线的重复已解决，不再列作当前漏项。用户步骤见[一页说明](docs/native/WINDOWS_CAD_QUICKSTART_ZH.md)，规则和恢复阶段见[本批记录](docs/native/LAUNDRY_CROSS_STROKES_20261126.md)。私人图纸和原始来源继续保存在受控交付中。

## 历史：穿过接触笔迹并终止于独立承接线的完整路径（2026-11-26）

> 以下“本批／最终／后续”属于 26b1b6e 阶段；其三短划与旧承接重叠未完成结论保留为历史，当前结果以上文为准。


从 main `c9798f14ed93a24c6cd11eaee933e217b7d50de8` 与 `QUARTER_circle_characters_3f51048.dxf` 的 426 正式对象接续。最终普通主图 **`QUARTER_structure_contacts_26b1b6e.dxf`**，195818 B，SHA-256 `b7bbaa765575d1d7e89ef9c7ee0185aaeac22768b84cb09ea8026e956e01b144`；**旧 426 全部严格保持＋三条独立 LWPOLYLINE＋一条独立承接 LINE＝430 正式对象／48 REVIEW**。三条路径为两个冻结目标与自然适用的 E 圆相关路径，附带成果不能替代目标验收。

两个目标均已完整进入最终主图：C07 右侧 F 圆上方路径穿过 S 形接触区后止于独立承接线；LAUNDRY 左侧 D 圆向右的路径经过短划及 S3 一带后止于已有独立承接线。起圆、端口、双侧延续、所有竞争分支、反向路线与实际保存端点均有来源核对；不得由位置名称或字母预填答案，不按最近距离吸附。字符尚未采用不自动阻止充分有证的路径，但共享墨迹不等于吞并字符侧枝或整个网络。

最终普通主图来源冷读、基线去向和逐处反向检查通过。Linux LibreCAD 2.2.1.6 已实际整体移动 T1、整体删除 T2，普通保存、完全退出并新进程重开；独立 GUI 冷审计状态为 **`PASS_2D_EDIT_ISOLATION_WITH_FORMAT_LIMITATIONS`**；每份其余 429 正式对象、48 REVIEW 与全部 53 图块保持。Windows 私有主图 GUI 仍 **NOT_RUN**；格式往返、XDATA、`zscale=0`、字体别名及 REVIEW 限制继续 **LIMITED**。

[Windows #694](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45673521187) 九组 source／实际 EXE、恢复、字体及安装／启动／卸载通过；新增输入实际触发本批能力，18 份转换 DXF 与本批 4 份实际删移副本下载后核对通过。完整包 **418085481 B**，SHA-256 `5044c5d885183245ecdf09358950690b60d7b90f2e49011939d2913e630da0fa`；1475 文件、77 份随包源码绑定通过。普通主图和 EXE 均绑定 `26b1b6e14106726fd9b1f66a747e8be16320b815`，[PR #53](https://github.com/ryoumiyahayato/image-to-cad/pull/53)，main 合并回执 **`5ed7490e7c0c5ddfdaf002496256f2e5477c816a`**。

**完成范围只限整条目标路径。** S／S3、三条短划及其他邻接网络仍待修；`LINE-16db792c3c06` 的旧近似重叠因完整来源责任未证明而保留，基线严格保持不表示每个旧表达都已正确。额外不可靠起圆候选、公开小输入的旧长近似 LINE 责任失败和方向证据不足拒绝均保留。后续任务从这些具体未决项接续，不重新把已完整路径拆成碎线，也不删除未归档来源。字体准备、双击恢复和一页用户流程继续复用。详见[本批记录](docs/native/STRUCTURE_CONTACT_PATHS_20261126.md)、[当前任务](docs/project/CURRENT_TASK.md)和[一页说明](docs/native/WINDOWS_CAD_QUICKSTART_ZH.md)。

## 历史：已有圆边的圆字对象与指定主接线（2026-11-25）

> 以下“本批／最新”及当时 C07 缺线未完成结论属于 3f51048 阶段；不覆盖上面的当前路径成果，也不改写原阶段的失败与验收范围。


从 main `48884a3` 与 426 对象的 `QUARTER_end_boundaries_d136aaf.dxf` 接续，最终主图为 **`QUARTER_circle_characters_3f51048.dxf`**，191372 B，SHA-256 `7a627317ec40b508a9140232531352fdb107b9499c3cc66a624158d5458809bb`。三处修改前冻结的目标圆字 **D/E/D 均完成**：LAUNDRY 右端、213 上方 BEDROOM 远端、右侧 `2LP-11` 上方验证圆。每实例唯一 CIRCLE＋TEXT 图块，独立外线保持。

426 基线的去向为 **419 严格不变＋6 同 ID 裸圆升级＋1 LAUNDRY 路径追加顶点**。六升级包括三个目标和附带 D/J/F；附带结果不能代替目标。LAUNDRY 指定接头恢复 5.711458 px，旧径向缺口为 5.362678 px；原 31 顶点、宽度和 bulge 保留，新尾并入同一 32 顶点路径。BEDROOM 已有接头保持，第三处没有扩大接线范围，其他邻线仍待修。

字符采用保留原 D/0 等分歧，增加冻结的同源原字形核验：至少两个独立原位置支持，所有实际竞争读法须有可靠参照且被排除；新采用字不回流作参照。尾段修复传递、重放原始已有末端核心，用原墨迹、唯一端口和竞争路径门确认，不按距离吸附或围绕 5.36 放宽长度门。ID、坐标、案例名只用于定位评估。

最终主图来源冷读、三目标反向对照、8 项文件编辑隔离通过。Linux LibreCAD 2.2.1.6 已实际完成 T1 D→K、T2 整块删除、LAUNDRY 整路径删除，并普通保存／完全退出／新进程重开；三份冷审计均通过，每次其余 425 正式对象＋48 REVIEW 保持。目标 TEXT 宽度因子六位小数舍入单列；首次普通保存二维内容 PASS，XDATA、zscale、字体别名、REVIEW 与格式限制仍 LIMITED。正式交付保留原始生成字节，GUI 副本另存。Windows 私有主图 GUI 仍 NOT_RUN。

主图与 Windows EXE 同绑 `3f510488cfd61558435a0c6e1812655caf76d930`。[PR #52](https://github.com/ryoumiyahayato/image-to-cad/pull/52) 已正常合入 main `c6ca18f468dd1139f69bba1badd2843eeafb09de`。[Windows #692](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45635504374) 八组 source／实际 EXE、恢复、字体与安装／启动／卸载通过；完整下载 418023784 B / `06145f839f1bf15ba459eb7f04bb728528c124cd97c4a9a84805f9d1bd4d7ffe`，1474 文件和 76 份应用源码字节绑定通过。双击恢复入口与字体准备继续使用。

详见[本批记录](docs/native/CIRCLE_CHARACTER_COMPLETION_20261125.md)、[当前任务](docs/project/CURRENT_TASK.md)和[一页说明](docs/native/WINDOWS_CAD_QUICKSTART_ZH.md)。上轮四处未完整结论仅属历史：C07 右上缺线、上轮第四圆位和其他邻接网络本轮没有完成，不得改写为整片恢复。旧 strict-three、跨平台 shortcode 完整 raw 重放失败及产品 LOCAL_NO_GO 保持。以下旧记录保留其执行版本。

## 历史：端部圆边与邻接线（2026-11-25）

> 本节“本轮／最新／下一阶段”均指端部圆边阶段，不代表上面的圆字完成结果。

从 main `fadd0f7` 和 423 正式对象的短编号主图接续。实际主图 **`QUARTER_end_boundaries_d136aaf.dxf`** 为 426 正式对象／48 REVIEW：旧 423 ID 全保留，418 旧几何保持，5 条路径追加 7 个有证短末段顶点，新增 3 个仅圆边 CIRCLE。四个冻结目标没有完整恢复；T1 圆边已补而应连接的 5.36 px 末段／内字待修，T2 圆边与接头已补而内字待修，T3 右上缺线和 T4 圆边未采用。不得把已有左上路径改善记为 T3 成功，不得把 T1 缺口称为真实白缝。

Linux 两种代表删除均普通保存、退出并新进程重开，每个副本其余 473 个实体保持；首次普通保存二维内容 PASS_2D_CONTENT_WITH_SAVE_LIMITATIONS，XDATA、zscale、字体映射、REVIEW 开关／颜色及样式／表／指针限制单列。Windows 私有主图真实 GUI 仍 NOT_RUN。

[PR #51](https://github.com/ryoumiyahayato/image-to-cad/pull/51) 已正常合入 main `cdc49c3097850a82cac9e449516ce2ac4043fa6f`。主图生成锚点为 `d136aaf`，Windows 实际构建为 `398b8b9`，生产模块逐文件相同。Windows [#690](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45599753968) 在构建提交 `398b8b924ebf0f8e61ed8db2eb8b705c3a3b2711` 全部适用步骤成功；六组 source／实际 EXE 普通入口、恢复与字体准备、安装／启动／卸载均通过。已取回核验的完整恢复交付包 `CADPhotoToDXF-0.3.0-dev-398b8b9-Windows-Complete.zip`，417986281 B，SHA-256 `7f6c6ef0c82d145384002d073b3ce27da94ff241d8e92e3f88080771c4dcd945`。将该包解压到新目录后双击 `Restore-Windows-portable.cmd`，自动校验内层完整 ZIP、解压并启动 EXE，无需分卷。已核对合并可达性并清理本轮无独有内容的本地临时分支。远端分支清理受限：GitHub 连接器没有删除 ref 能力，Git 推送缺少凭据；浏览器只能看到未登录的已合并 PR 页面，没有删除分支按钮。未登录或反复等待，`development/curve-end-boundaries` 的删除未完成。 后续文档提交不改变执行锚点。

继续复用已有字体准备、完整程序／双击恢复入口。下一阶段从实际未恢复的圆内字、可靠末段与邻接路径继续；按原图证据和共同规则处理，不因距离近强接或为数字凑完整。详见[本批记录](docs/native/CURVE_END_BOUNDARIES_20261125.md)、[当前任务](docs/project/CURRENT_TASK.md)与[一页说明](docs/native/WINDOWS_CAD_QUICKSTART_ZH.md)。历史失败与来源审批边界保持，产品仍 LOCAL_NO_GO。

## 历史：上一轮 Windows 字体准备与交付（2026-11-25）

本轮交付代码 `943c721` 已经 PR #50 合入 main `97c0fb2`，Windows #687 全部通过；完整417683910字节便携包与最终取回文件已校验为同一份。应用已有字体准备/已有DXF入口，恢复脚本实际在新Windows目录通过。主图仍是 `QUARTER_shortcodes_2fd4373.dxf`，未新识别。Windows真实主图人工GUI仍NOT_RUN，不能以Windows进程/PDF/ezdxf或Linux GUI代替。详见 [Windows交付记录](docs/native/WINDOWS_CAD_DELIVERY_20261125.md)及当前任务。之后的文档提交不替代实际EXE构建锚点。

## 短编号生成阶段与核验入口（历史，图纸继续作为验证材料）

当前任务从 main `241d99dabecbb4d23f7a724727dcea5127359aea` 与 `QUARTER_contact_cbac773.dxf` 的 **423 个正式对象**接续。只处理五条固定完整短编号：`2LP-10,12` 优先，其次 `2LP-6,8`、`2LP-20`、`2LP-19`、`2LP-22`。这些都是已有开发／回归位置，不称新留出。标签答案不能进入生产逻辑。

本轮已完成普通整区主图 `QUARTER_shortcodes_2fd4373.dxf`：五条固定编号4完整／20待修，实际共6个新TEXT替换6条字内LINE，417旧对象严格保持，总数423。执行提交 `2fd4373` 经 PR #49 合入 main `1133cea`，合并树与执行树相同；新进程保存来源、全部6条的18项文件编辑、1条代表编号的LibreCAD改字／整删／保存退出重开均已完成。严格GUI保存仍FAIL／LIMITED，不能由邻居隔离PASS覆盖。

同版Windows #684实际五组source／EXE及现有安装流程通过，实际10份DXF和20份编辑文件读回通过。额外Linux跨平台完整来源重放仅8/10通过，短编号两份因6处派生角度末位差继续FAIL，单列 `LIMITED_SOURCE_REPLAY_CROSS_PLATFORM`；原像素、路径和本例选择未变，但跨平台来源恢复不能保证。不要改写旧strict-three、旧拟合重放失败和拒交首稿。产品仍LOCAL_NO_GO；最新主线文档提交不替代2fd4373实际执行锚点。

严格保护原有房号、圆形标记、门墙、正确文字和完整路径。新 TEXT 接管的字内横划可以有证退场，独立下划线、引线和短划必须保持。普通 `native-objects` 重算受影响阶段，不向旧 DXF 拼接新文字。来源转写和排版分别记录；所有已有 raw 冲突重放，不靠先遇到的一致候选停止检查。

当前实证和恢复阶段见[当前任务](docs/project/CURRENT_TASK.md)及[短编号记录](docs/native/SHORT_CODES_20261125.md)。历史继续引用[字线接触记录](docs/native/TEXT_CONTACT_20261124.md)、[单行标签](docs/native/SINGLE_LINE_LABELS_20261122.md)及[圆形标记](docs/native/CIRCULAR_MARKERS_20261122.md)。旧 Windows strict-three 失败、XDATA、INSERT `zscale=0` 等保存限制不改写。产品仍 `0.3.0-dev / LOCAL_NO_GO`，兼容 LIMITED，工程师工时 NOT_RUN。

**验收总方向**：同一冻结图纸四分之一区域，尽可能多、干净、完整地恢复线、文字、门、墙、符号和连接对象；专业人员实际修图（包括全部漏画补绘、校验、纠错）时间不超过同范围同质量从零绘制的一半，才能对外声称达到最终采用目标。此正式工时测试目前仍为 `NOT_RUN`。
