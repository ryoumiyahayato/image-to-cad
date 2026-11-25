# Windows：准备字体、打开主图和编辑圆字

适用 **0.3.0-dev / `3f51048`** 与 **`QUARTER_circle_characters_3f51048.dxf`**，目标 CAD 为 **LibreCAD 2.2.1.6**。公开入口：[Windows #692](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45635504374)；在 Artifacts 中选择 `CADPhotoToDXF-Windows-Verified-Delivery-3f510488cfd61558435a0c6e1812655caf76d930`。主 DXF、匹配字体及许可由同次结果包提供，保留在同一结果目录。

## 1. 启动程序

**本次推荐入口：** 下载完整包 **`CADPhotoToDXF-0.3.0-dev-3f51048-Windows-Complete.zip`**，解压到新目录，双击 **`Restore-Windows-portable.cmd`**。它校验包内完整程序 ZIP，解压并启动 `CADPhotoToDXF.exe`，无需手工命令。另解压配套结果包，保留 `drawing` 目录内的主图与字体。

**若另行取得普通便携 ZIP：** 解压整个普通便携包，再双击其中的 `CADPhotoToDXF.exe`。这与上面的完整恢复交付包是两种不同布局。

**已有分卷时：** 把所有 `.zip.partXX`、`PORTABLE_RESTORE_MANIFEST.json`、`Restore-Windows-portable.cmd`、`Restore-Windows-portable.ps1` 放在同一新目录，双击 **`Restore-Windows-portable.cmd`**。它校验、恢复、解压并启动；缺卷／损坏会指出文件，已有不同文件会停止并保留原件。同版重复执行保持稳定。无需手工拼接命令，也不会永久修改执行策略。

## 2. 让软件准备 CAD 字体

在启动页或文件菜单点 **“打开已有 DXF / 准备 CAD 字体…”**，点“选择 DXF…”并选择最新主图。已有 DXF 不需要再识别。软件查找 LibreCAD；找不到时点“选择 LibreCAD…”，只选择 `LibreCAD.exe`，不用寻找字体目录或修改配置。

| 软件状态 | 下一步 |
| --- | --- |
| 未准备 | 点“准备 CAD 字体”。 |
| 已准备，可打开 CAD | 点“在 LibreCAD 中打开”。 |
| 需要重新打开 CAD | 保存工作，完全退出 LibreCAD，再回软件点“重新检查”。 |
| 准备失败 | 按显示原因处理或重新选择 LibreCAD；内部诊断保留在日志。 |

资源重复准备稳定，保留其他字体和设置。**“已准备”表示资源已准备，不表示运行中的 CAD 窗口已加载新字体。**

## 3. 修改圆内字、整块删除或删除独立路径

先用菜单 **File → Save as（文件 → 另存为）** 在结果目录保存编辑副本。**`Ctrl+Shift+S` 是 Save All，不是另存为。**

**修改一个圆内字：** 在右侧块列表选择该位置的唯一实例，右键 **Edit Block（编辑块）**；双击内字打开 TEXT 对话框，例如把 D 改成 K。保留其他文字参数，确认后从 **Drawings（图纸）菜单**返回主图，按 `Ctrl+S` 普通保存。每处使用独立块定义，修改该实例不会改另一个圆字。

| 位置 | 右侧块列表中的名称 |
| --- | --- |
| LAUNDRY 右端 D 圆 | `I2CAD_CIRCULAR_4958f90982ad` |
| 213 上方 BEDROOM 远端 E 圆 | `I2CAD_CIRCULAR_07cacd10e00b` |
| 右侧 `2LP-11` 上方验证 D 圆 | `I2CAD_CIRCULAR_0406020b25d6` |

**整体删除圆字：** 回到主图，点击圆边选中整个块，用 **Edit → Delete selected（编辑 → 删除所选）**。圆和内字一起删除，独立外接线保持。

**删除 LAUNDRY 完整路径：** 在主图点击曲线主体选中该路径，再用 **Edit → Delete selected**；本次补的尾段属于同一条路径，整条删除后不会留下自己的尾段。普通编号仍可双击 TEXT 修改整串，例如 `TEST-A7,03`，独立引线和下划线不随文字删除。

普通保存后，完全退出 LibreCAD，再重新打开副本检查。正式交付保留原始生成字节，GUI 保存及编辑副本另存。

## 4. 这版已完成与仍待修

LAUNDRY 右端 D、BEDROOM 远端 E、第三验证位置 D 已成为完整圆字对象。LAUNDRY 指定接头恢复 5.711458 px 并入原路径；BEDROOM 既有接头保持；第三位置未扩大接线范围。其他邻线、上批 C07 右上缺线和上批第四圆位继续待修。

Linux 已在最终主图副本实际完成改字、另一圆字整删、LAUNDRY 整路径删除及普通保存／退出／重开，独立冷审计通过。Windows #692 的八组实际 EXE、恢复、字体及安装检查通过，完整包已实际下载核验；**Windows 私有真实主图 GUI 仍 NOT_RUN**。首次普通保存二维内容通过；XDATA、INSERT `zscale=0`、字体别名、REVIEW 与格式变化仍 LIMITED。改字对话框对目标宽度因子的六位小数舍入已单列验证。

主图和 EXE 均绑定 `3f510488cfd61558435a0c6e1812655caf76d930`，PR #52 合入 main `c6ca18f468dd1139f69bba1badd2843eeafb09de`。完整包 418023784 B，SHA-256 `06145f839f1bf15ba459eb7f04bb728528c124cd97c4a9a84805f9d1bd4d7ffe`；详细指纹见[本批记录](CIRCLE_CHARACTER_COMPLETION_20261125.md)。产品仍 **LOCAL_NO_GO**，工程师完整修图工时验收 **NOT_RUN**。
