# P2C — AutoCAD Web 手动验收

**历史方案，已停止作为当前 primary validation。** 当前本地开发验收器
改为 Bentley View。用户报告的是另一个产品 Autodesk Viewer 的 missing
font substitution；该结果不是 AutoCAD Web 字体加载结果。Viewer 的
FONT_LOADED=FAIL、SUBSTITUTION=YES、FONT_FIDELITY=NOT_VALIDATED，
仅作为小文件云端 sanity check，不用于 variable 字重推断或大图纸验收。
以下说明保留为历史操作记录，不是当前待执行指令。

本包用于 Autodesk 端的开发验证。最终目标仍是 **AutoCAD Desktop**；
Web 结果不能替代最终 desktop AutoCAD RC 验收。TrueView 2026/2027
安装已因用户报告的 ODIS Error 4000 放弃，本周期不继续处理安装。

## 上传的两个文件

从 `local-artifacts/product-fix-p2c/autocad-web/` 选择：

- `comparison.dxf`：十个原生 TEXT 对象，STYLE 为 `P2C_NOTO_SC_CANDIDATE`。
- `NotoSansSC[wght].ttf`：完整、未修改的官方字体，保持原文件名。

字体 SHA256：
`a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da`。
压缩包只是方便传递；解压后分别上传 DXF 和 TTF。
OFL.txt、清单和反馈模板随包提供，不需要作为绘图上传。

## 手动步骤

1. 打开 [AutoCAD Web](https://web.autocad.com/)，上传 `comparison.dxf`。
2. 在 Support Files / Manage Support Files 的字体管理中上传上述 TTF。
   Autodesk 官方说明支持通过该管理器上传字体；不能只把 TTF 放在普通
   绘图文件列表里。入口可从首页进入，或使用字体选单的 Add Fonts。
3. 字体上传后重新打开 comparison 绘图。保留原 STYLE、文字内容、字高
   和 width factor，以便判定引擎实际加载情况。若界面自动替换字体，记录
   替换名称和提示，不把手动改过的 STYLE 当作原始测试通过。
4. 查看整页和放大的中文、英文、数字及 ®。截图包含实际绘图和可见的
   字体/STYLE 信息；再保存一张字体上传结果或缺失/替换提示截图。
5. 把截图和结果返回本聊天。可以直接用普通文字回复，不必编辑 JSON。

参考：[Autodesk 字体上传说明](https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Uploading-SHX-fonts-to-AutoCAD-Mobile-app.html)、
[Web text styles](https://help.autodesk.com/cloudhelp/ENU/AutoCAD-Web-Help/files/Drafting-and-Creating/AutoCAD_Web_Help_Drafting_and_Creating_styles_html.html)。

## 要检查的内容

| 从上到下的原文 | 字高 | Width factor | 插入点，mm |
| --- | ---: | ---: | --- |
| 电施 | 5 | 1 | 10, 110 |
| 图纸目录 | 5 | 1 | 10, 100 |
| 项目编号 | 5 | 1 | 10, 90 |
| Project Name | 5 | 1 | 10, 80 |
| Design Institute | 5 | 1 | 10, 70 |
| 1 | 5 | 1 | 10, 60 |
| 7 | 5 | 1 | 10, 50 |
| 01 | 5 | 1 | 10, 40 |
| 2024.8.15 | 5 | 1 | 10, 30 |
| ® | 5 | 1 | 10, 20 |

CAD TEXT height 是实体参数，并不保证可见墨迹恰好高 5 mm。相邻插入点
纵向间隔为 10 mm，所有 width factor 均为 1，未做压窄 fitting。请记录
是否出现丢字、方框、空白、空心轮廓、异常粗细、字体替换、位置变化或行间重叠。

此 variable 字体的默认字重是 **Thin 100**，含 **Regular 400** named
instance。不能因为 name table 中 legacy subfamily 为 Regular 就认定
Web 实际使用了 400；请记录界面显示的 family/style/weight，无法确认时写未知。
上传成功也不能单独证明绘图已经使用该字体。

DXF 在 AutoCAD Web 中以 view-only 打开，这是
[Autodesk 记录的行为](https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Unable-to-edit-DXF-file-in-AutoCAD-Web.html)。
本包已在本地验证为十个 native TEXT，view-only 不能据此判定文本变成图片
或轮廓。本轮不要求在 Web 编辑或转成 DWG。

## 返回结果

请返回：字体上传是否成功、绘图是否实际加载该字体、中文/Latin/数字/®
是否完整、是否实心、是否替换、family/style/weight（若能确认），以及整页
和局部截图。尺寸无法量测时写未知，不需猜测精确 bbox。

`user-result-template.json` 内有逐个 TEXT 的参数和待填的 Web render bbox。
这个 comparison 先验字体加载；**没有代表 W01/W02/W03 的 source cell**。
真实图纸的 source-visible ink sizing、cell overflow 和生产字体策略仍需
在 Autodesk Web 字体结果返回后继续验收。Desktop 字体安装/同目录查找
模式也不能从 Web support-font 上传结果推断已经通过。

这里是本轮 STOP 点：等待手动 Autodesk Web 视觉结果。
