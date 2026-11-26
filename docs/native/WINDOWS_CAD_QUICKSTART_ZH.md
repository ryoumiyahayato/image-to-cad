# Windows：准备字体，分别编辑短划、曲线和承接线

适用 **0.3.0-dev / Windows `f988424`** 与主图 **`QUARTER_laundry_short_strokes_6a27c0f.dxf`**，目标 CAD 为 **LibreCAD 2.2.1.6**。[Windows #696 下载入口](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45755563007)的 Artifact 为 `CADPhotoToDXF-Windows-Verified-Delivery-f988424b9dcf697d42fac8244acb96abce2b4fc7`。主图、匹配字体和许可由配套结果包提供。

## 1. 启动和准备

1. 下载 **`CADPhotoToDXF-0.3.0-dev-f988424-Windows-Complete.zip`**，解压到新目录，双击 **`Restore-Windows-portable.cmd`**。它使用完整内包，自动校验、解压并启动程序，不需要拼接命令。另完整解压结果包，保留图纸旁的字体、许可与子文件夹。
2. 在软件启动页或文件菜单点 **“打开已有 DXF / 准备 CAD 字体…”**，选择上述主图，无需再识别。找不到 LibreCAD 时只需选择安装好的 `LibreCAD.exe`，不用寻找字体目录或手工改配置。
3. 点 **“准备 CAD 字体”**，按状态操作，再点 **“在 LibreCAD 中打开”**。

| 状态 | 操作 |
| --- | --- |
| 未准备 | 点击准备 CAD 字体。 |
| 已准备，可打开 CAD | 打开图纸；此状态表示资源准备完成。 |
| 需要重新打开 CAD | 保存工作、完全退出 LibreCAD，再回软件重新检查。 |
| 准备失败 | 查看显示原因，必要时重新选择 LibreCAD；内部诊断写入日志。 |

重复准备保留其他字体与设置，不把复制成功当作当前 CAD 窗口已加载字体。历史分卷仍可将所有分卷、清单与两份 Restore 脚本放到同一新目录，双击同一 CMD；缺卷、损坏或不同现有文件会停止并保留原件，不永久修改系统执行策略。

## 2. 分别编辑完整对象

先用 **File → Save as（另存为）** 保存编辑副本；`Ctrl+Shift+S` 是 Save All。单击目标主体选中一个完整对象：

- **三条短划各是一条 LINE**，可分别选取。整条曲线和最终承接横线也是各自独立对象。
- **整体移动：Tools → Modify → Move / Copy**，选参考点与目标点，在对话框选 **Delete Original**；保留目标原图层和属性。
- **整体删除：Tools → Modify → Delete selected**。删长曲线后三短划和圆字应保留；删一条短划后另两条与曲线应保留；移走承接线后原位不应留下同源重复横线。真实独立交叉邻居仍会存在。
- **修改圆内字：** 右侧块列表进入对应唯一实例的 **Edit Block**，双击 TEXT 修改，再从 **Drawings** 返回主图。普通完整文字可直接双击修改。

普通保存，完全退出 LibreCAD，再重开副本检查。使用结果包中的原始主 DXF 开始编辑，验证用的已修改副本另存。

## 3. 本版完成与边界

LAUNDRY 三条交叉短划已完整恢复，两条旧同源承接横线由一条完整 LINE 承担，长曲线接点同步核验。430 基线全部可追溯，最终 432 正式对象／48 REVIEW；S／S3、相邻细竖线及其他邻接网络仍待修。

Linux 实际整路径删除、短划删除和承接线整移，普通保存／完全退出／新进程重开均通过，各副本其余 431 正式对象、48 REVIEW 和 53 图块保持。Windows 十组实际 EXE、恢复、字体、安装检查及本批 20 份文件编辑副本冷读通过。**Windows 私有主图桌面 GUI 仍 NOT_RUN，CAD 保存格式 LIMITED，工程师工时 NOT_RUN，产品 LOCAL_NO_GO。**

主图 `6a27c0f` 与 Windows `f988424` 的完整源码树相同，经 PR #54 合入 main `bb165884`。完整包 418173918 B；指纹与版本详见[本批记录](LAUNDRY_CROSS_STROKES_20261126.md)。
