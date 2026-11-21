# CAD 兼容验收：按实际影响分级

更新：2026-11-21。当前产品仍为 **LOCAL_NO_GO**。本页区分原始导出、CAD 普通保存、诊断副本和工程师交付；它们各有自己的文件哈希，不能共用审核结论。

## 本轮目标配置

| 项目 | 固定配置与边界 |
|---|---|
| 主要二维编辑器 | LibreCAD **2.2.1.6 Linux x86-64**；v8.4 历史普通编辑证据绑定此版本 |
| 原生引擎导出 | DXF R2013 / AC1027，`$INSUNITS=4`，纸面毫米 |
| LibreCAD 普通保存 | DXF R2007 / AC1021；检查当前实体、单位、文字与操作结果，不要求版本字串不变 |
| 输出文字度量 | 配套 `DejaVuSans.ttf` 与许可证；不能由同目录有 TTF 推断 LibreCAD 已加载它 |
| LibreCAD 试用改字 | 对话框明确选择 `wqy-microhei`，记录实际字体和字号；若该字体不可选则记录环境未备好，禁止默称字体通过 |
| 独立几何消费者 | FreeCAD **1.0.0** C++ DXF importer，`DxfImportMode=2`；不把几何导入当成文字可编辑或人工 GUI 操作 |
| 未覆盖平台 | Windows、DWG、Android、其他 CAD 版本均须独立实测 |

普通改字可以采用合理替代字体。验收对象是内容、缺字、可读性、越框、重叠、字号和行序，以及编辑保存重开后的结果；字体名称变化本身不决定通过或失败。

已取得并校验[官方 v2.2.1.6 发行包](https://github.com/LibreCAD/LibreCAD/releases/tag/v2.2.1.6)：Linux x86-64 AppImage SHA-256为 `f2d86e6a40ec684b758c821eff3496a7d36e69f17519cde0b508a66d72c5754c`，与官方校验值相符。包内 `wqy-microhei.lff` SHA-256为 `788b2e10ba142176e53a632deeaaef98b07428f31fb9eedf3b8174362e4a6195`；v8.4配套 `DejaVuSans.ttf` SHA-256为 `57f73e11f51999432bf7ab22ce55b6f945d5eca1bf824404cfa9ec2e3718c84e`。资源存在与哈希符合不代替实际字形检查；二进制不提交公开仓库。

## 已核查 v8.4 文件的实际影响

原始主 DXF SHA-256：`0d5453c453b571baeba1109e58ae2e2e7f05778d318c61f2c17bd4c7df57fd5c`。
LibreCAD 首次普通保存 SHA-256：`8a73d543855167f610c8fa3c1002470ded0db5ac1ab708cef51aedc4da1a0c93`。

| 项目 | 事实与分级 | 必须验证的结果 |
|---|---|---|
| 字体 | `I2CAD_TEXT` 的 font 字段从 `DejaVuSans.ttf` 变成 `I2CAD_TEXT`；历史两次改字另用了 `wqy-microhei`。属显示/排版待核验 | 不缺字、不越框、不重叠，内容可改且保存保持 |
| DXF 版本 | AC1027 → AC1021，单位4保持。属格式变更记录 | 实际使用的实体与编辑结果保持；不扩展为所有 DXF 特性兼容 |
| XDATA | 模型空间390个携带来源数据的实体 → 0。属追溯能力变化 | 原审核只绑定原文件；改后文件重新审核。不能据此宣称 LINE/TEXT/INSERT 不能编辑 |
| INSERT zscale | 25个 INSERT 从默认1变为原始group43=0，变换行列式0。**独立消费者中已证实几何消失，属交换阻断** | 见下方单变量对照。LibreCAD二维可见不能关闭此项 |
| REVIEW | off丢失，frozen/locked/plot=0保持。历史重开仍隐藏；打印和选择行为须单独核查 | 默认隐藏、正常编辑不误选、打印不出现。不能把off字段变化单独等同于可见 |
| PLOTSETTINGS | 原始导出0个；LibreCAD保存后1个无owner的孤立对象。属保存/打印专项 | 正常打开、保存和打印；源导出目前未引入此对象，不能声称源导出修好了外部保存器 |

### zscale 的独立消费者与单变量对照

从实际原始文件和普通保存文件中提取一个房号、一个双门和一个单门的 INSERT 诊断切片。保留所选 INSERT、全部 BLOCKS/TABLES/HEADER 的原始字节，只移除其他模型空间实体。未重画、未改缩放、未覆盖原件。

| 样例 | 原始文件 FreeCAD 导入边数 | 普通保存文件导入边数 | 仅将副本group43由0改1后的边数 |
|---|---:|---:|---:|
| 房号框 | 4 | 0 | 4 |
| 双门 | 4 | 0 | 4 |
| 单门 | 7 | 0 | 7 |

三份单变量控制副本恢复后的每条边17点几何采样（9位小数）均与原始文件一致。这将本次故障定位到零 Z 缩放，不能再将它视为无害字段差异。FreeCAD 此导入模式未创建可编辑文字对象，因此本项只证明几何消费者表现，未验证字体或文字编辑。控制副本是诊断证据，不是原始普通保存文件，也不继承其来源审核。

FreeCAD console importer 首次尝试因无GUI导入模块失败，日志保留；成功证据来自 offscreen GUI 引擎的自动导入，不是人类 GUI 操作。

处理路径：使用经本项目实测不会写出零缩放的 CAD 构建；或在保留原始普通保存文件后，显式产生兼容副本、记录变更和新哈希并重新核验。不得默默改写用户文件。LibreCAD 官方有对应[问题1428](https://github.com/LibreCAD/LibreCAD/issues/1428)和[主线修复2756](https://github.com/LibreCAD/LibreCAD/pull/2756)，主线修复不等于本项目固定的2.2.1.6二进制已经修复。

## 可重复只读检查

```bash
python maintenance/native_cad_compatibility.py \
  --before /controlled-input/original.dxf \
  --after /controlled-input/cad_ordinary_saved.dxf \
  --output /private-results/compatibility.json
```

脚本读取原始 ASCII group41/42/43，同时记录 ezdxf 解释与矩阵行列式、XDATA、单位、字体、图层和 PLOTSETTINGS；不会调用修复或写回 DXF。结果包含私有文字/几何，留在受控材料中，不提交公开仓库。原始与改后哈希不同即不能沿用旧审核；输出为观察记录，不是笼统的 CAD PASS。原始字节审计不支持二进制 DXF，会明确报错。

## 收口标准

完成一次目标 CAD 打开→普通编辑→保存新文件→退出→重开，保留实际文件。核对目标和邻居、字形/行序、单位、门及房号变换、REVIEW默认显示/选择/打印和正常打印。发现问题的试用允许带着已说明的缺陷开始；跨 CAD 正式交换不得忽略已证实丢失对象的缺陷。

当前单位是纸面毫米。DPI只把像素换为纸面长度；实际门宽、墙长和设计比例须通过已知工程尺寸或比例尺标定，不得由DPI推断。

## 依据

- [ezdxf XDATA](https://ezdxf.readthedocs.io/en/stable/xdata.html)：实体上的自定义应用数据。
- [ezdxf INSERT](https://ezdxf.readthedocs.io/en/stable/blocks/insert.html)：轴向缩放、变换和非均匀缩放限制。
- [ezdxf Layer](https://ezdxf.readthedocs.io/en/stable/tables/layer_table_entry.html)：off、frozen、locked与plot的不同职责。
- [ezdxf DXF版本与编码](https://ezdxf.readthedocs.io/en/stable/drawing/management.html)；[单位](https://ezdxf.readthedocs.io/en/stable/concepts/units.html)。
- 私有 v8.4 保存原件、逐步GUI账本和本轮 `v84_ordinary_compatibility.json`、`freecad_actual_inserts.json`、`freecad_actual_inserts_z1_controls.json`；审核以所列文件哈希为准。
