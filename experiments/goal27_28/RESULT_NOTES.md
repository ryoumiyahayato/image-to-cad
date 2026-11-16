# 实际执行记录

本轮开始2026-10-27 19:32 +08。A开发/运行，B独立GUI/复核；最多两人。

局部测试命令：`.venv-gui-check/Scripts/python.exe -m pytest experiments/goal27_28/test_reconnect.py -q --basetemp <独立新目录>`。当前9 passed，2.01s。随后IMAGE资源状态从双计为CONTENT_EQUAL修正为ASSET_CHANGE，仅重跑资源项：1 passed、8 deselected，1.19s。未全仓测试。

实际工程副本检查：坏CAD输入拒绝，模拟最终os.replace失败保持原工程，两个已打开版本的旧保存被PROJECT_VERSION_CONFLICT拒绝。本人单文件保存锁占用时PROJECT_SAVE_BUSY，释放后无锁残留。均比较实际保存文件原始字节，不计算哈希。

DEV08：真实生产D0与G25 runs-final/DEV-08/drawing.dxf字节相同。首轮预览15项接受，第二轮预览2项接受；每轮均独立Python进程打开工程并导出。最终revision4、两接受事务，导出与B实际D2字节相同。重复D2返回ALREADY_ACCEPTED/0确认。

A06：G26 source scene，明确非生产几何整合。首轮2项接受、第二轮1项接受；两轮保存重开导出。最终revision4、两接受事务，导出与B实际D2字节相同；重复0确认。三个HATCH来源均不宣称实例身份已恢复。

最终实际并发案例：基于DEV08第二轮导出，工程内部edit-text成LOCAL 456 mm，B在LibreCAD外部分支改字并增删LINE、冻结TRACE_STRAIGHT。外部差异1705相同、1文字变化、1旧LINE/1新LINE、1冻结状态；预览OBJECT_CONFLICT，accept拒绝，内部保存件保持。未声称冲突自动合并。

来源XDATA丢失：DEV08 521、W02 391、DEV03 877；G26三个控制和A06首轮各1。历史身份确认0。内容相同不恢复身份，source_automatic_operations全false。身份未知的数量不能写成几何匹配未决数量。

原始CAD、资源、完整差异及GUI保存件在外部输出根；不制作重复大型交付包。开发JSON保留原始数值差异，非用户必须逐条确认清单。

原型修正记录：初始HATCH浮点归一、DXF不支持属性读取和图层线型大小写；空间索引缩小整页候选搜索；事务文件互斥/冻结输入接受/内部文字操作；最后IMAGE资产变化状态双计修正。没有修改毫米精度、字符串比较规则、原数据或真值，没有替代第二套匹配路线。

DWG控制使用已安装ODA27.1.0的既有_run_converter，两次exit0，实际DWG格式头AC1032。最终1707实体、111字符串逐序保持，但全部111TEXT从wqy-unicode字体改为Standard/txt。另有8width/2rotation原始微差和轮廓层颜色变化。转换损失保留，无DWG GUI通过结论。执行后按本人owner/PID/nonce释放high-resource锁。

最终只读核main/G25/G26两实验树均干净、HEAD未改；冻结产品意图diff为空。LibreCAD/ODA进程均无，资源锁目录空。没有主动计算哈希或生成指纹清单。

重复运行：旧G26 HATCH/IMAGE控制在初始归一修正后重读；9项局部测试随事务变化复跑；不重复原始OCR、来源渲染或生产转换。没有把重复运行累计成独立案例。
