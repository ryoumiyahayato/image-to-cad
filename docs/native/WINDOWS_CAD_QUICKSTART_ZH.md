# Windows：准备字体、打开主图和编辑

适用本次 **0.3.0-dev** 开发程序与 **`QUARTER_end_boundaries_d136aaf.dxf`**。目标 CAD 为已安装的 **LibreCAD 2.2.1.6**。程序公开构建入口为 [Windows #690](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45599753968)；本次交付的一页说明提供已核验的完整便携包和配套结果包。主 DXF、字体和许可保留在同一结果目录中。

## 1. 启动程序

**本次推荐入口：** 下载完整恢复交付包 **`CADPhotoToDXF-0.3.0-dev-398b8b9-Windows-Complete.zip`**，解压到一个新目录，双击其中的 **`Restore-Windows-portable.cmd`**。它自动校验包内已有的完整程序 ZIP、解压并启动 `CADPhotoToDXF.exe`；不需要分卷。另解压配套结果包，`drawing` 文件夹包含最新主图与匹配字体。

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

## 3. 修改文字或独立对象，保存副本

在 LibreCAD 中先在原结果目录**另存为编辑副本**。改完整编号时，选 **工具 → 修改 → 属性（Tools → Modify → Properties）**，点文字，修改完整字符串，例如 `TEST-A7,03`。只改内容时保留字高、字体和宽度因子。删除文字时只选该文字按 Delete，旁边独立圆、引线和下划线应保持。

已有圆字图块可整体选择删除；独立外接路径分别选择。新恢复的三个圆边目前没有采用内字，不能把它们当成完整圆字图块。普通保存，完全退出 LibreCAD，再重新打开副本检查。可查看 `2LP-10,12` 旁 F 圆白缝、独立引线，`2LP-6,8` 的独立下划线以及原有 `LAUNDRY`。

## 4. 这版已完成与仍待修

LAUNDRY 右端已补圆边，但内字和应连接的 5.36 px 末段仍缺；BEDROOM 远端补圆边及接头，内字待修；F 右上缺失外线和固定第四圆位未采用。七张对照图随结果包提供。四个目标均未达到完整恢复，当前正式对象为 426。

Linux 已实际完成圆字块整删、独立完整路径整删，各自保存、退出并新进程重开；每个副本其余 473 实体保持。Windows #690 的实际程序、恢复及安装检查已通过；**Windows 真实主图 GUI 仍 NOT_RUN**，缺少可操作的桌面条件。首次普通保存二维内容通过，但 XDATA、INSERT `zscale=0`、字体别名、REVIEW 开关／颜色及样式／表／指针保存限制仍在。

实际主图绑定 `d136aaf`，Windows 程序绑定 `398b8b9`；主线合并及包指纹见[本批版本记录](CURVE_END_BOUNDARIES_20261125.md)。产品保持 **LOCAL_NO_GO**，严格 CAD 往返 **LIMITED**。不需要用户在本机代做排错。
