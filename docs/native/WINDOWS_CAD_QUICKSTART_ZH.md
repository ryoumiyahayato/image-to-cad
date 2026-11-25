# Windows：准备字体、打开主图和整条编辑路径

适用 **0.3.0-dev / `26b1b6e`** 与 **`QUARTER_structure_contacts_26b1b6e.dxf`**，目标 CAD 为 **LibreCAD 2.2.1.6**。[Windows #694 构建下载入口](https://github.com/ryoumiyahayato/image-to-cad/actions/runs/45673521187) 的 Artifact 为 `CADPhotoToDXF-Windows-Verified-Delivery-26b1b6e14106726fd9b1f66a747e8be16320b815`。主图、匹配字体与许可由配套结果包提供。

## 1. 启动和准备

1. 下载 **`CADPhotoToDXF-0.3.0-dev-26b1b6e-Windows-Complete.zip`**，解压到新目录，双击 **`Restore-Windows-portable.cmd`**。它校验完整内包、解压并启动程序，不需要拼接命令。另完整解压结果包，保留主图旁的字体、许可和子文件夹。
2. 在软件启动页或文件菜单点 **“打开已有 DXF / 准备 CAD 字体…”**，选择最新主图，无需再识别。找不到 LibreCAD 时，只需选择安装好的 `LibreCAD.exe`，不用寻找字体目录或手工改配置。
3. 点 **“准备 CAD 字体”**，按下面状态操作，再点 **“在 LibreCAD 中打开”**。

| 状态 | 操作 |
| --- | --- |
| 未准备 | 点击准备 CAD 字体。 |
| 已准备，可打开 CAD | 打开图纸；此状态表示资源准备完成。 |
| 需要重新打开 CAD | 保存工作、完全退出 LibreCAD，再回软件重新检查。 |
| 准备失败 | 查看显示的原因或重新选择 LibreCAD；内部诊断写入日志。 |

重复准备保留其他字体与设置，不把文件复制成功当作当前 CAD 窗口已加载字体。若使用历史分卷，把全部分卷、清单和两份 Restore 脚本放在同一新目录，双击同一 CMD 入口；缺卷、损坏或不同现有文件会停止并保留原件，不永久修改系统执行策略。

## 2. 整条移动、删除与改字

先用 **File → Save as（另存为）** 保存编辑副本；`Ctrl+Shift+S` 是 Save All。点击曲线主体选中完整路径，然后：

- **整体移动：Tools → Modify → Move / Copy**，选参考点和目标点，选 **Delete Original** 后确认。
- **整体删除：Tools → Modify → Delete selected**。新路径是一条完整 LWPOLYLINE，独立圆字、承接线与邻居保持。
- **修改圆内字：** 在右侧块列表进入对应唯一实例的 **Edit Block**，双击真正 TEXT 修改，再从 **Drawings** 返回主图。普通完整文字可直接双击修改。

普通保存，完全退出 LibreCAD，再重开副本检查。正式主图使用结果包根目录的 DXF；`evidence/gui` 中是已修改的验证副本。

## 3. 这版完成与边界

C07 右 F 圆上方路径和 LAUNDRY 左 D 圆通往 S3 一带的支路均已完整恢复；旧 426 对象严格保持，附带 E 路径及一条独立承接线另计，最终 430 正式对象。S／S3 字形、三条短划、其他邻线和旧近似重叠仍待修。

Linux 实际整移／整删、普通保存、完全退出与新进程重开通过；每份其余 429 正式对象、48 REVIEW 及 53 图块保持。Windows 九组实际 EXE、恢复、字体及安装检查通过；**Windows 私有主图桌面 GUI 仍 NOT_RUN**。XDATA、INSERT `zscale=0`、字体别名等保存限制继续 **LIMITED**，产品仍 **LOCAL_NO_GO**。

主图和 EXE 同绑 `26b1b6e14106726fd9b1f66a747e8be16320b815`，PR #53 正常合入 main `5ed7490e7c0c5ddfdaf002496256f2e5477c816a`。完整包 418085481 B；文件指纹、真实证据和恢复阶段见[本批记录](STRUCTURE_CONTACT_PATHS_20261126.md)。
