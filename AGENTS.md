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

## 当前阶段：端部圆边与邻接线（2026-11-25）

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
