# Windows：准备字体、打开图纸和改字

适用本轮 `0.3.0-dev` 开发包与 `QUARTER_shortcodes_2fd4373.dxf`。目标 CAD 为 LibreCAD 2.2.1.6；应已安装 LibreCAD。匹配字体及许可随包提供，保留包内文件即可。

## 1. 启动程序

**完整 ZIP：** 解压整个程序包，双击其中的 **`CADPhotoToDXF.exe`**。结果包另行解压，保留主 DXF 和随附字体／许可。

**分卷：** 在一个新目录放齐所有 `.zip.part01`、`.zip.part02` 等分卷，以及 `PORTABLE_RESTORE_MANIFEST.json`、`Restore-Windows-portable.cmd`、`Restore-Windows-portable.ps1`。双击 **`Restore-Windows-portable.cmd`**，它自动校验、恢复 ZIP、解压到同名程序目录并启动。完整 ZIP 也可以使用这个入口。无需输入拼接命令或永久修改执行策略。

缺卷或损坏时，窗口会指出需要重新取得的文件；已有不同 ZIP 或程序文件时会停止并保留原件，请换新目录恢复。同版完整目录重复执行会校验并启动。恢复日志为同目录 `Restore-result-日期时间.json`。

## 2. 由软件准备字体并打开真实 DXF

启动页点击 **“打开已有 DXF / 准备 CAD 字体…”**，再点“选择 DXF…”。文件菜单也有这个入口；已有图纸无需再次转换。软件自动查找 LibreCAD，找不到时点击“选择 LibreCAD…”，只需选择安装好的 `LibreCAD.exe`。

| 软件状态 | 现在如何操作 |
| --- | --- |
| 未准备 | 点击“准备 CAD 字体”。 |
| 已准备，可打开 CAD | 点击“在 LibreCAD 中打开”。 |
| 需要重新打开 CAD | 保存正在编辑的图纸，完全退出 LibreCAD；回到软件点击“重新检查”，再打开。 |
| 准备失败 | 按界面原因处理，例如重新选择 LibreCAD 程序；详细诊断在应用日志。 |

软件准备所需资源，不覆盖其他字体或设置；重复准备保持稳定。**“已准备”不表示运行中的 CAD 已加载新字体。** 不需要寻找字体目录、改配置文件或另装替代系统字体。

## 3. 改字、删除和保存

在 LibreCAD 中先将主图**另存为编辑副本**。要改整行编号，选 **工具 → 修改 → 属性（Tools → Modify → Properties）**，再点该文字，在弹出的文字属性中修改完整字符串，例如 `TEST-A7,03`，确认即可。保持原字体、字高和宽度因子，除非您也希望调整排版。此操作入口见 [LibreCAD 官方实体编辑说明](https://docs.librecad.org/en/2.2.0_a/guides/dwg-edit.html#changing-attributes-and-properties)。

要删除整条文字，在另一个副本中只选中该文字并按 Delete；圆、引线或下划线是独立对象。使用普通“保存”，退出 LibreCAD，再重新打开编辑副本。`2LP-10,12` 旁 F 圆白缝、独立引线，`2LP-6,8` 下划线以及原有 `LAUNDRY` 可作为查看位置。

## 版本和验证范围

主图仍绑定 `2fd4373`，应用／字体准备能力绑定本次程序包的构建提交；以[当前任务](../project/CURRENT_TASK.md)记录为准。Windows 实际 GUI、文件级验证分别记录，自动测试不能代替真实 GUI 打开改字证明。既有 XDATA、INSERT `zscale=0` 等保存限制继续 **LIMITED**，产品保持 **LOCAL_NO_GO**。
