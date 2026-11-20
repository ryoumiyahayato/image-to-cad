# 当前项目状态 — 2026-11-20

**版本0.3.0-dev；整体LOCAL_NO_GO。** 当前目标是[完整可编辑原生对象](NATIVE_OBJECT_PRODUCT_BASELINE_20261120.md)。

## 公开基线与私有v8.4

| 范围 | 已验证事实 | 未通过事项 |
|---|---|---|
| 本公开保留基线 | ProductionProcessingService/FinalStructure/DXF基础设施；GUI默认DXF；入口和构建明示preserved_main_baseline；既有基线CI与精确保留检查 | 尚未迁入私有app/native_objects完整链路；旧Windows CI不代表新原生引擎通过干净机验收 |
| 持续研发分支（[PR #42](https://github.com/ryoumiyahayato/image-to-cad/pull/42)，尚未合入main） | `development/native-reconstruction`已从G1合并提交建立；实际原生核心、manager/worker、CLI/GUI和依赖资源清单已提交 | 结果按该PR的明确提交与实际产物核对，不能写成本main已默认使用原生引擎；完整区域和产品验收仍须独立判断 |
| 私有v8.4 | 同一固定四分之一区域正式生成主DXF；342正式对象；原453条OCR保留并来源重验；真实冷读、独立渲染与LibreCAD 2.2.1.6八项编辑和退出重开 | 完整内容验收未过；PANTRY、一个完整墙编辑组合退化；多行说明、EBB-3、其他文字/交汇/符号仍待修 |
| 产品采用 | 有来源和实际编辑证据的局部对象 | Windows最新引擎EXE、APK、DWG、工程师修图≤手画50%均未通过 |

私有最终DXF SHA-256：`0d5453c453b571baeba1109e58ae2e2e7f05778d318c61f2c17bd4c7df57fd5c`；算法指纹：`a58b6ac25f6a439430223c12260a1c3bdaf346a92f6fdf2eb1297d677a609e97`。公开这里只登记版本边界，不复制私人原图、OCR、模型和完整实验包。

旧295项：263保留、28有依据替代、1正确撤回、2遗漏/完整组成退化、1尚未识别；人工复核分支单列。当前完整区域输出不是完整来源已经重建的证明。

R1/R2私有逻辑修复已通过，不再要求重做原局部实验。三行注释前两行完整，第三行i/I/1证据冲突；旧7个曲线像素已不在当前输入域。EBB-3仍缺可靠完整采用，相关邻近EBB区域必须按真实来源位置区分。

LibreCAD普通保存的二维编辑与交换兼容分开记录。本轮复核发现历史普通保存文件的25个INSERT原始group43为0；FreeCAD 1.0独立消费者对实际房号/双门/单门切片的4/4/7条边均变成0，仅将诊断副本zscale恢复1后恢复原几何。这是已证实的交换问题，不能由二维截图消除。字体、REVIEW和PLOTSETTINGS仍按实际显示、选择和打印分别检查；XDATA丢失影响追溯，不直接等于实体不可编辑。原审核只绑定原文件，不自动适用于改后文件。当前单位为纸面毫米，未证明建筑实际比例。具体证据边界见[研发分支CAD兼容说明](https://github.com/ryoumiyahayato/image-to-cad/blob/development/native-reconstruction/docs/native/CAD_COMPATIBILITY.md)。

## 仓库收口和当前工作

[PR #41](https://github.com/ryoumiyahayato/image-to-cad/pull/41)已作为唯一清理内容入口合并，G1内容合并提交为`1b82d8f9fa165e93b3e8ff9caef5543e8d566b3f`，包含#41最终HEAD与#40目标提交；#40已关闭。两个已合并工作分支尚待删除，五个独有研究分支继续保留。维护合并不等于正式发布；旧`main=5b2a76b`是清理前历史起点，G1合并提交也是历史锚点，main允许正常前进。

G2源码迁入已由持续研发分支及[PR #42](https://github.com/ryoumiyahayato/image-to-cad/pull/42)跟踪；本main继续保持公开legacy行为和受保护回归。原生安装、依赖与资源说明见[研发分支REPRODUCE](https://github.com/ryoumiyahayato/image-to-cad/blob/development/native-reconstruction/docs/native/REPRODUCE.md)。Q1—Q5继续处理退化、完整连接、文字分型、CAD影响及工程师试用准备，结果绑定实际提交和文件，见[当前任务](CURRENT_TASK.md)。

历史清理已删除7条冗余分支和11个重复/空文件，#38/#39关闭；原执行事实见[历史清理账本](CLEANUP_EXECUTED_20261120.md)。新收口后的活动引用与保留原因见[G1收口记录](G1_CLOSEOUT_20261120.md)。

## 历史记录

[截至2026-11-16的原状态记录](PROJECT_STATUS_HISTORY_20261116.md)原文保存，日期和当时任务不作为当前指令。不存在“旧历史快照必须永远等于当前main”的要求。
