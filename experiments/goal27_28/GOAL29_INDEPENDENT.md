# GOAL29 独立区域复核

2026-10-28，B。自动GUI，非真人UAT。基线e05bb4361733422a4483aff62e444286265c1ab0。最终运行代码e5f35900f63a4893d4bbdd7a0d8b3751a30f1793。A实现及局部测试，B独立查源、全区域评价、唯一GUI。TASKS在改代码前冻结，提交fdd890c43ffc37ec1c7f4eb6adf9ccbc3cbd5e09；单位读取勘误7c8846ba1ae264997b934321f255341b9f86aac1。DEV08完整7项/8TEXT，DEV03完整8项/9TEXT。DEV03未运行候选。

独立裁决：直接Qt可信预览并接受路线为NO_GO。08-5已在Qt接受，实际LibreCAD才发现新增末0与中文笔画重叠。已撤销该内容事务，保留失败文件及截图。该准入候选已停用。最终安全工程通过一次受控LC补救后封存，范围为PARTIAL：08-4内容及布局、08-5完整字符和局部宽度、08-7方向改善；流程仍需明显外部CAD补救。不能用局部字体/蓝线改善称预览可信或产品READY。

## 基线、选路与失败机制

已完整阅读AGENTS、产品意图、协议、验收、状态、旧FOLLOWUP_RESULT/独立报告、GOAL29要求及新版computer-use skill、guidance、API、confirmations。旧工程/输出只读。源裁片明确为source，未冒充GUI。

基线窗口实际选6D6查源、6D8查源/输入Φ8@200/预览，再切下一对象取消并关闭。关键蓝线及楼梯几何极暗，字体窄实心，无法安全判断；未接受，磁盘仍revision10。确认/保存/新进程重开没有完成。相同CAD字节的LibreCAD可见LFF空心字与蓝线。模型线存在；旧Qt解析字体为Arial Unicode。未达到数值相同视口，不能宣称像素对照通过。

选A复用已有显示路径，减少每对象切CAD定位负担；B受控CAD核验需要导出/切窗/重新定位/回接。首次ezdxf LFF解析发生IndexError，使用唯一一次机制修正：TEXT复用项目既有librecad_text_path，几何仍ezdxf。3D/镜像/倾斜/复杂对齐、MTEXT、格式串、未核验字体拒绝。屏幕细线约1.4px起，不代表出图线宽。真实GUI可见LFF、蓝线和楼梯斜轮廓，但这没有阻止08-5错误接受。

A在e5停用直接文字确认。B新进程打开安全revision19，重新读08-5第40页来源、输入Φ10@200并预览。按钮仍disabled，状态明确“本版邻字遮挡判断未通过，直接确认已停用”。未接受，退出后仍revision19。后续只能把此窗作为查源/建议辅助；修订须先实际CAD修改/核验，再外部保存回接。旧local_repair CLI不作为GOAL30的准入。

## 正式区域结果

当前工程来自旧revision10副本。布局均由实际Qt导出→LibreCAD原生Text属性→明确另存D1→Qt差异预览/明确接受完成。只处理三个计划布局成员和两个内容候选，正确对象不改。当前成员表示当前CAD位置/内容匹配，不证明历史实例身份。

|项|基线→当前成员|最终内容和布局|旧字/引线与新增退化|原生编辑及结果|
|---|---|---|---|---|
|08-1|6CF→6CF|166.67X9=1500，90°；原字段保持|全区尺寸字及两端可见，未见本轮新增遮挡；未清几何轮廓|TEXT。真实查源/全区核对；保护，不算新收益|
|08-2|6D6→6D6|既有Φ10@200，0°；完整字段保持|Φ竖干/@靠近或触及既有蓝下划线仍在；未称已解决|TEXT。真实查源/同文件Qt与LC核对；保护，不算新收益|
|08-3|6D7→6D7|120，0°；完整字段保持|本轮Φ8改后与120下划线有可见间隙；未移120/引线|TEXT。真实查源/全区核对；保护|
|08-4|旧6D8→711→710；中文旧6D9→6D8|Φ8@200；height2.5、width.55、rotation0。分布筋内容/字段保持|第一次仅缩宽仍贴120，未接受；单成员降字高后再预览/接受。最终LC间隙可见，中文独立；未删共享轮廓|两项均TEXT。Φ8在新进程LC属性可读；中文在独立QA改字保存重开。新增完成|
|08-5|6DA→70F→711|最终Φ10@200；rotation0、width.47、height3.26332，位置不变|Qt接受的.525候选末0新增重叠中文，已撤回。随后唯一受控LC候选.47使完整字串在原引线内留白，与中文分离；实际CAD核验后才回接|TEXT。最终新进程LC属性及全区可读，内容经外部补救完成；原直接路线仍NO_GO|
|08-6|6DD→6DB|260x8=2080，0°；完整字段保持|Qt默认局部视口截末0，一次手形平移才看全文；最终LC全条及端线可见|TEXT。QA末位改为1保存、退出、新进程重开；正式件保持2080。保护|
|08-7|6DE→710→70F|TB1，4.085616779974935°→0°；height4.04521、width.609758|双下划线保持，最终LC水平可读；未清共享轮廓|TEXT。QA改为TBQ1保存退出重开，正式件仍TB1。新增方向完成|

全7项/8个TEXT都已实际选择并重新读取来源。人工/代理看图后输入Φ8/Φ均为代理转录，未称自动识别。没有按规范或常识改数字。区域内几何/引线实际检查；原冻结SOURCE_TEXT_OUTLINE层保持。未见新增第二份可见TEXT；细小轮廓残留和旧描摹连接不等于已清理或逐线证明正确。08-2原接触保留，全部7项分母不变。完整区域的新增完成为3项，其中08-5依赖受控CAD补救；其余4项作保护核对，不重算收益。旧接触、细小残留/连接未全面裁决仍列为限制，不能据此写完整质量GO。

## 保存链与整份保护

正式工程：D:/programs/Image-to-CAD/goal29-20261028/b/region-work/dev08-region.icreview，最终revision21。两轮LC布局回接revision12/14，Φ8接受15，下侧Φ接受16；b065新进程重开/导出17，发现遮挡后GUI撤销18，再正式导出19。没有只在内存中撤回。随后一次实际CAD补救回接保存20，新进程重开并正式导出21。安全revision19完整副本保留为b/cad-rescue/safe-revision19.icreview。

最终正式真实GUI导出：b/cad-rescue/project-export/drawing.dxf。最终LC另存：b/cad-rescue/DEV08-GOAL29-final-LibreCAD.dxf。中途rev19导出b/accepted-export/drawing.dxf及其精确字节副本b/safe-export/drawing.dxf、当时LC保存件b/DEV08-GOAL29-LibreCAD.dxf均保留。失败导出b/final-export/drawing.dxf保留，禁止作为后续输入。

B通过实际ReconnectProject.open打开最终工程。revision21、当前payload等于正式export和实际补救D1字节；最终export与LC保存件的1707实体完整规范化tags多重集相等，只忽略本地handle/owner，无数值容差，missing/added均0。rev19 core及全部历史payload精确保留，3条pending引用可解析，自动来源true计数0。最终结果b/cad-rescue/final-readback.json，旧b/final-readback.json保留。中途rev19已完全退出旧LC后由新进程5900重开并核Φ8原生属性；最终LC于17:29:13由新进程19492重开，全区及下侧Φ原生TEXT属性.47/3.26332/0检查完成。

A独立程序检查rev19的a/whole-cad-protection.json及最终rev21的a/final-protection.json、a/final-rescue-readback.json：1704非目标完整tags精确匹配，余3为本表布局成员。TL1、既有上侧Φ、绿色PTB9（旧711→最终70E）完整内容/位置/颜色保持。111TEXT、409LINE、1172LWPOLYLINE、6CIRCLE、9HATCH。core、全部旧payload、资产字节保持，字体/图层/坐标文档元数据无变化。B读过该结果；该1704核对为A执行，不冒称B测试。

属性框舍入保留为实际差异：旧6DA height3.263317452741887→3.26332；旧6DE height4.045211708681815→4.04521、width.6097580678492527→.609758。旧6D8先height2.982387475538164→2.98239，再明确改2.5。没有用放宽容差隐藏舍入。DXF序列化可省默认字段，不声称整文件字节等于旧输入。原PLOTSETTINGS owner审计修复建议在基线/安全件均有，审计未写回；不扩大兼容性改造。

单位勘误：B对基线副本/安全导出/LC/QA各读取raw splitlines及ezdxf.readfile，均INSUNITS4。TASKS原6来自CRLF原文直接StringIO读取的默认值，已追加勘误；区域公式/分母不变。单位未修改或重缩放。

## 独立QA与工作量

QA文件b/qa-native-edit/QA-only-edited.dxf，明确非正式结果、不回接。用原生Text对话框实际改三类字符：分布筋→分布筋测；260x8=2080→260x8=2081；TB1→TBQ1。保存后完全退出LC，新进程再打开，三字符串均显示。B程序回读各1个TEXT。正式件仍原中文/2080/TB1。

|阶段|固定初始化/耗时|输入调用与逐对象成本|
|---|---|---|
|旧基线走查|可见启动至取消关闭235秒；Hidden误启动122秒单列|Qt19次。确认/保存/重开0；未闭合流程|
|正式第一段|16:07:39–16:39:43，32分04秒|Qt87次；成员定位12次/24动作，来源选择重读10次/30动作，输入3、预览3、内容接受2、外部回接含切窗13、导出8、平移1、激活/最大化2、关闭1。LC布局42次。含一次宽度候选取消及第二轮字高返工|
|最终读回/失败回退/QA/停用确认|b065新进程16:42:47；LC新进程16:59:08；e5新进程17:03:32，17:07前退出。约24分钟混合工具/判读；分类净耗时未测|Qt另27次输入调用尝试，含新进程定位/导出、撤销、安全再导出、e5建议预览和退出；其中1次返回检测到用户输入，已刷新/激活再继续。LC另39次，含两份读取、正式/QA另存、9次QA改字动作、保存、退出/重开、原生属性及QA回读|

最终段LC路径最初用正斜线，文件框拒绝无效文件名；改Windows反斜线成功，多3次输入记录在39内。e5首次Start-Process返回“操作已被用户取消”，没有安全弹窗操作；按此前有stdout/stderr重定向的同一非提权启动形式一次重试成功，错误不隐藏。所有观察调用不算输入。正式Qt输入合计114次尝试，LC81次；另有基线输入、读取和固定启动。代理动作不是鼠标按键底层次数，也不是真人净劳动。每对象净时、常规CAD真人对照及净省时未测。不能据此声称省时，外部布局/核验/回接是明确补救成本。

额外受控补救：源图完整Φ10@200末端在引线内留白，中文位置保持。B选择只把该成员width.525→.47，height3.26332及insert不动。实际LC原生Text一次候选输入完整字串并改宽；全区可读且末0与中文分离后SaveAs b/cad-rescue/D1.dxf。Qt回接显示内容1/关系1/合计2，1706相同、歧义0；关系1是新Φ8先前确认711降为当前710候选，旧6B3/6D6 pending不重提示。两个坐标点击未触发接受；刷新、激活、Tab聚焦、Return后保存20。再关闭/新进程重开、正式导出21，实际LC打开该导出→最终SaveAs→退出→新进程重开核验。没有通过停用的直接确认按钮接受。

补救段17:13:53启动，17:31附近全部退出，约18分钟混合用时；Qt另21次输入尝试，LC另22次，固定增加两个Qt和两个LC启动。含两次模态坐标未命中、刷新/激活和Tab/Return操作；最后一次激活返回检测到用户输入后按要求刷新，未操作其他应用。正式总Qt135次尝试、LC103次；基线另19次Qt。分类净耗时未测。直接路线的NO_GO不因外部补救成功改成GO。

A另核项目与LC的wqy-unicode LFF：原bytes不同，但通用换行解码后文本相同，Φ10@200解析字宽/advance相同。不能把剩余误判归因不同字体版本。视口裁切/邻域判断限制已观察，具体误判机制未完全分离，不再补renderer。

A报告27项受影响局部检查通过（24+字体/格式拒绝2+安全停用1）；B未重复运行这些测试。全仓回归未运行。恢复历史、重复回接、候选/复制/删除、事务失败/撤销的相关历史检查由A执行；不以测试数替代GUI质量。

## 关键实际GUI文件与后续边界

全部PNG位于新输出，来自公开sky截图载荷按交付用途保存。基线图在b/baseline-walk；正式图在b/region-work。少量关键图：

- [基线受阻预览](D:/programs/Image-to-CAD/goal29-20261028/b/baseline-walk/qt-6D8-preview-blocked.png)
- [LFF与蓝线显示](D:/programs/Image-to-CAD/goal29-20261028/b/region-work/qt-LFF-protected-Phi.png)
- [原区域](D:/programs/Image-to-CAD/goal29-20261028/b/region-work/librecad-region-before.png)
- [Φ8仅缩宽失败未接受](D:/programs/Image-to-CAD/goal29-20261028/b/region-work/gui-08-4-width-only-not-accepted.png)
- [08-5新增遮挡失败](D:/programs/Image-to-CAD/goal29-20261028/b/region-work/librecad-final-new-overlap.png)
- [撤销后安全区域](D:/programs/Image-to-CAD/goal29-20261028/b/region-work/librecad-region-final.png)
- [LC新进程正式重开](D:/programs/Image-to-CAD/goal29-20261028/b/region-work/librecad-new-process-formal-reopen.png)
- [Φ8原生TEXT属性](D:/programs/Image-to-CAD/goal29-20261028/b/region-work/librecad-formal-Phi8-native-properties.png)
- [QA新进程回读](D:/programs/Image-to-CAD/goal29-20261028/b/qa-native-edit/gui-new-process-three-edits-reopen.png)
- [一次CAD补救全区](D:/programs/Image-to-CAD/goal29-20261028/b/cad-rescue/gui-one-candidate-full-region.png)
- [补救后工程新进程重开](D:/programs/Image-to-CAD/goal29-20261028/b/cad-rescue/gui-new-process-project-reopen.png)
- [最终LC新进程全区](D:/programs/Image-to-CAD/goal29-20261028/b/cad-rescue/gui-final-LC-new-process-reopen.png)
- [最终下侧Φ原生属性](D:/programs/Image-to-CAD/goal29-20261028/b/cad-rescue/gui-final-Phi10-native-properties.png)
- [最终建议预览及禁用确认](D:/programs/Image-to-CAD/goal29-20261028/b/region-work/gui-final-direct-confirm-disabled.png)

部分旧Qt截图受桌宠遮挡，未据此认定被遮区域可见。最后LC区域及停用截图无该遮挡。源PDF裁片另标source；不把源图或脚本渲染冒充实际CAD。

GOAL30尚未下达。本批只交接，不执行DEV03候选。TASKS固定区域/分母/质量口径不变。以后若运行，只能沿安全辅助范围和实际CAD核验/回接，不把NO_GO直接确认功能带入；旧接触、轮廓/连接未决及外部补救继续评价。字体仅名称wqy-unicode、项目已有LibreCAD LFF来源，不打包二进制。所有本人Qt/LC进程已退出；工具runtime和其他项目进程未动。
