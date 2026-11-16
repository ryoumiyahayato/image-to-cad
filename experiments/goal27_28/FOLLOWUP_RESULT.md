# 来源关系续用与第二次局部修复

用户授权实施INDEPENDENT_FOLLOWUP_REVIEW.md和ZIP中的优先建议。本批从dc54c7b开始；输入原件、旧工程和旧输出只读。A/B使用新树，新输出为D:/programs/Image-to-CAD/g2728-followup-20261027。

## 已复现与修复

B通过实际ReconnectProject.open、已有ReviewProject来源完整性路径复现：旧实际导出D0与LibreCAD保存件D1内容相同，原预览0项，但接受后6B3当前确认关系降级且不带来源证据/操作人。历史仍在，TL1未丢。

新行为：内容复核0、关系复核1。接受后6B3变为PRIOR_CONFIRMATION_REVIEW_REQUIRED，通过prior_confirmations引用原确认所在state/member，resolve_confirmation可读完整原source_evidence和actor。当前没有自动来源权限，也不把跨保存身份写成已证明。

| 接续情况 | 当前行为 | 实测类型 |
|---|---|---|
| 真实外部另存首次回接 | 关系复核1，旧确认可追查 | 实际旧CAD/工程，程序及GUI |
| 候选不变的再次另存 | 新关系复核0，候选继续显示 | 程序构造另存 |
| 复制同内容对象 | 两个候选均待复核，不选一个当历史原件 | 真实工程临时程序分支 |
| 删除且无对应 | 工程级unresolved_relation_refs保留失效引用 | 真实工程临时程序分支 |
| 已未决候选内容改变 | 新增关系复核项 | 局部合成测试 |
| 第二对象修复 | 不清除第一对象候选及失效记录 | 局部测试及真实工程程序检查 |

## 第二次局部修复

目标为DEV08当前6D6，$10@200→Φ10@200。重新读取第40页、240 DPI，邻域[2069,714,2240,816]；源图首符是圆形贯竖线，旧OCR的$不符。只转录首字符U+03A6，不改变10@200，也不作工程规范或设计含义判断。

A程序检查：先接受真实D0/D1关系变更，再完成第二次修复。只有6D6内容变化，1706非目标保持；TL1、PTB9及既有几何保留；6B3候选和原确认完整相等。保存重开后有效，独立撤销副本回到第二修复前payload。记录a/second-local-result.json。

B已在真实GUI中完成首次外部回接，预览内容0/来源关系1/合计1，明确接受保存为revision7。历史候选窗口显示原裁片/操作人/历史记录，点击重新读取来源未改CAD。第二修复保存后关闭重开，GUI导出后revision9。LibreCAD Text属性为Φ10@200、OCR_TEXT、wqy-unicode、高3.04085、width0.571233。

视觉证据分歧：PyQt预览中字符与最近蓝线有空隙；LibreCAD显示Φ底部竖线贴蓝色下划线，@下降部跨线。B在当前副本同处临时改回旧$观察，再Undo回Φ，未保存临时$。旧$及@原来也触/跨蓝线；Φ未新增明显遮挡，字符可读。原布局接触问题保留。不能用预览图代替目标CAD应用结果。

LibreCAD另存dev08-second-librecad.dxf，完全退出后新进程重开，Text属性仍为Φ10@200及原字体/高度。独立程序读取保存前后：111 TEXT、409 LINE、1172 LWPOLYLINE、6 CIRCLE、9 HATCH，handles保持，changed_members={}；首字U+03A6；TL1/PTB9保持。见b/second_librecad_readback.json。

最后再次用真实D0/D1回接：内容0、关系1、合计1，仅6D6的新确认降为候选；6B3旧候选不重提示。B明确接受保存revision10，关闭后新进程重开，候选成员2、无当前对应0。GUI分别查看两条历史确认；独立读取两个proof的裁片/操作人/来源可解析，自动操作0，历史身份仍NOT_PROVEN。原core及旧payload保持；相较本批旧工程只有6D6字符串改变，1706非目标规范化标签相同；TL1/PTB9保持。当前payload与dev08-second-librecad.dxf字节相同。见b/final_gui_project_readback.json。

## 入口与证据

project_entry.py新增“外部保存回接”和“查看来源候选及失效”。回接分开计数内容与关系；历史裁片明确标为旧证据，重新读取才调用来源校验和源区域渲染。后续把原始JSON预览改为可读摘要，事务逻辑不变。

本批GUI截图已保存：b/gui-reconnect-preview.png、b/gui-prior-confirmation.png、b/gui-second-repair-preview.png。它们来自实际操作，不使用来源PDF裁片替代GUI。桌面悬浮物遮挡部分窗口边缘；不据截图声称全窗口或全页视觉检查通过。

## 检查与限界

命令：`.venv-gui-check/Scripts/python.exe -m pytest experiments/goal27_28/test_relation_review.py experiments/goal27_28/test_reconnect.py experiments/goal27_28/test_local_repair.py -q --basetemp <新输出目录>/a/pytest-initial`。21 passed，2.49s。GUI代码py_compile通过。没有全仓回归。

这是执行者查看来源、明确选择并确认的局部校对，不是自动发现漏字。待复核关系仍待复核；未恢复全部历史实例，也未开放自动来源批处理。布局、来源残留清理、正式主窗口整合、全页重新处理合并、DWG、真人UAT及净劳动计时未执行。既有PLOTSETTINGS owner问题本轮未修复、未另行审计。

本批两项优先建议在限定范围成立：明确关系可经下一次外部保存保留为可追查候选，并继续完成另一对象的来源支持修复和再次回接。整体仍为PARTIAL，未把局部流程升格为正式生产整合或整页质量通过。

原产品意图Markdown保持不变。不合并、不推送、不训练、不外传。未计算额外哈希或创建指纹清单、额外门禁、验收矩阵或大型证据包。输出目录创建于22:04:07（+08），代码与GUI结果记录至22:41；此前附件阅读不计入，也不是真人节省工时。B本轮GUI进程已正常退出，资源锁已释放。
