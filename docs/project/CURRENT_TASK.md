# 当前执行任务 — G1/G2/Q1—Q5

**产品0.3.0-dev / LOCAL_NO_GO。** [当前规范](NATIVE_OBJECT_PRODUCT_BASELINE_20261120.md)要求完整且独立可编辑的原生对象。

## G1：清理收口

[清理 PR #41](https://github.com/ryoumiyahayato/image-to-cad/pull/41)已通过正常检查并合并，G1 内容合并提交为`1b82d8f9fa165e93b3e8ff9caef5543e8d566b3f`。main已包含#41与#40的目标提交，#40已关闭；不要再次安排合并这两份PR。

剩余清理是删除两个已合并工作分支并读回核实；[G1收口记录](G1_CLOSEOUT_20261120.md)列出实际保留清单。五个独有研究分支尚无本轮新建且读回验证的替代归档，继续保留。历史快照和当前可恢复性分别检查，main正常前进不算资料损毁。

## G2：持续源码研发分支

持续分支[`development/native-reconstruction`](https://github.com/ryoumiyahayato/image-to-cad/tree/development/native-reconstruction)已从上述整理后main建立，实际核心、manager/worker、CLI/GUI及依赖资源说明已进入[源码PR #42](https://github.com/ryoumiyahayato/image-to-cad/pull/42)，尚未合入main。后续实现与验证继续绑定该研发分支的明确提交；保留本main的legacy行为，不把研发分支的默认原生入口误报为main现状。

当前继续核对源码PR适用检查、干净入口实际DXF及同一冻结区域的来源责任和编辑结果，按[研发分支复现说明](https://github.com/ryoumiyahayato/image-to-cad/blob/development/native-reconstruction/docs/native/REPRODUCE.md)运行。空任务目录、没有旧采用名单的新输入必须经正式入口生成实际DXF；界面明确引擎。源码PR与私人证据分开，局部通过不等于完整区域或产品采用通过。

## Q1—Q5：完整区域质量

- Q1：PANTRY真实字形与邻线分离；完整墙可行性先于局部近似代表选择，成功后撤回合理替代散线。
- Q2（主要算法）：归并交汇/孤立性拒绝，含C07/C08；保留端口、短枝、白缝、孔洞及接触证据，有限路径分解在同冻结全区域使用。
- Q3：邻线混域、i/I/1冲突、EBB-3后缀分别处理。原始字形/同页可靠参照和负例支持裁决；相同输入不重复识别，模糊字符不阻塞其他区域。
- Q4：按显示、内容、变换、可编辑性、审核绑定和打印的实际影响划分CAD差异；明确纸面毫米与工程比例标定。
- Q5：准备发现问题的工程师试用。真人文件、时间和高成本位置没有发生就NOT_RUN；正式50%门槛不因减少最终内容而降低。

## 本轮交付与边界

G1交真实合并/main SHA/删除保留清单；G2交源码PR、资源清单及干净入口DXF；Q阶段交同一冻结区域主DXF、前后对象账本、真实删移文件和工程师试用包。

原v8.4及失败保持，不重跑R1/R2已完成实验，不全页、不Android、不正式Release。普通路径、空几何、导出异常在当前任务内修复继续；未知异常和资源停止保存检查点，未执行不能记作算法失败。
