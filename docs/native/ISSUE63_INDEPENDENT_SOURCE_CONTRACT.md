# Issue 63：独立来源模型 v2（首次真实采用前冻结）

本合同是 #62 独立保存审核 v1 之外的新入口，不改写历史结果。原 TIFF、
ROI、200 DPI、阈值 128 与 20°／18° 方向门保持。旧 436 对象不允许改形或
插点。ID 仅定位实际保存对象；任何 producer PASS、候选端点或候选链都不作
独立来源真值。

## 1. 有界方向依赖和实心微循环

每个接点从新建原图骨架枚举全部端口和有限方向竞争。固定短观察失败仍
保存；允许使用既有有界无循环方向证明（最多 8 层、64 个依赖节点、64 个
方向状态），每轮只使用较早轮已证明的唯一正反配对，最坏偏转 ≤20°，
最坏双向竞争余量 ≥18°。不得删不利方向、依起点选支或修改原图 pairing。

循环核心仅增列一个有限子集：最小像素包围矩形全部原黑，原核心无内部
自由端、无真实白洞，所有外臂方向完整且全部由互斥唯一正反配对覆盖。
保留全部原骨架邻接和简单路径，不删边造树。沿用 64 像素、12 像素尺度、
64 条简单路径和 8192 搜索状态上界；超界明确 pending。实心本身不授权
接线或整块覆盖。

## 2. NECESSARY_PRIOR_FINITE_PORT

新增类型不是 COMPLETE_TARGET_STROKE 或完整旧路径重新通过。旧对象完整
实际保存几何和完整旧来源绑定分别哈希；实际 mm 坐标与旧 writer 运算
严格绑定。证书只授权原图可重建的有限相关源臂，保留完整对象不变。

影响域先由目标全长、端帽和 model window 固定；对原图支持的目标端点
全部方向候选，用轴向最多 240 px、法向最多 12 px 的有限走廊追加可观察
延续范围。不得采用 target bbox 四周加 240 的正方形，也不得按失败结果
缩窗。实际使用的方向依赖、核心原像素、全部独立法线截面和有限出口
两侧源臂作为显式 evidence read domain 记录。几何按原生段的精确参数范围
截取，各次出入分别成有限对象；不拼接不连续段，不改完整 CAD。

每个有限源臂保留原 graph edge ID 和端点 index 子范围，出口两侧至少
4 px 同一原始八连通源臂；原始已绑定对象终端单列，不冒充新自由端。
每个实际有限子范围两端固定 6/8/12 px 观察全部枚举；未独立、太短、
重复、无内部法线等观察保留原因，不能只挑有利截面。宽度交集空可由
新 bounded field 层处理，端口证书本身不放宽任何截面。

公共 API：`build_influence_domain(source, graph, target_rows, model_window)`；
`certify_finite_prior_port(source, graph, saved_row, prior_object, domain, *, roi, dpi)`；
`validate_finite_port_certificate(source, graph, row, *, prior_object=None)`；
`measure_finite_port_sections(source, graph, row, all_rows, *, forbidden_core_cells=())`。
certify 返回 `rows` 和完整 receipt；validator 从 source、fresh graph、实际
完整几何及绑定重算，不能相信 receipt.pass。

证书 row 必有 `body_role=NECESSARY_PRIOR_FINITE_PORT`、完整保存几何与 hash、
完整 prior binding 与 hash、influence domain 与 hash、`source_graph_edge_ids`、
`source_edge_subranges`、`source_path_px`、`representation_exact_points`、
`independent_sections`。远处失败在 `excluded_remote_findings` 单列；若其像素
属于任何实际使用证据，不得排除。无来源身份时只能继续完整旧入口，
不能凭 bbox 排除旧对象问题。

## 3. 实际 CIRCLE 的独立曲线入口

reader 返回实际保存的 center/radius、源坐标精确分数和实际 INSERT 变换。
保持 CIRCLE，不以弦替代。恢复的完整旧 circle source 仅用作旧身份与原
像素绑定；旧 458 采样通过单列，不能冒充新 exact 通过。

有限相关域内按像素闭格到实际圆心的精确最小／最大平方半径判断实际
圆弧进入。正长度穿过白格内部为严格失败；切触／角点零长度另列。
原环黑格、相关白格、实际 center/radius、有限空间域、旧四端口分别返回，
供共同黑白责任核检验带宽。中心线支持不等于圆墨责任通过。

## 4. 保存审核和验证

`audit_saved_source_component(..., source_model="v2", prior_source_bindings=...,
circle_source_objects=...)` 新建原图 graph、冷读实际 DXF，重建目标、有限
prior ports 和独立圆入口，再调用 `bounded_source_component.audit_bounded_bodies`。
默认／显式 v1 保持 #62 原入口。61 个 TEXT 的原 bytes-bound 字形边界证明
保持。所有几何、源像素和证书身份变化须可被复核发现。

新增验证必须含成功正例，以及不唯一方向、真实白洞／缺黑格、未绑定
旧几何、域内微小白穿、出口源臂不足、伪造缩窗／证书、圆半径／源像素
修改、白格弧穿越反例。首个真实回执无论成功失败均独立保存；不回填
#62 历史 v1 身份。

## 5. 恢复实现的接口澄清（#63 评论 7218448576 后）

方向 v2 是独立枚举实现；没有修改既有 direction helper 的 OR 条件。每条
已使用或已排队的原方向臂记录有限 14 px 前缀，短臂全保留；经内部核心时
枚举全部原简单路径。失败、太短、重复 edge、深度／状态截断仍记录原臂和
实际读像素。完整方向候选至多 64，展开状态另有 8192 上限，依赖至多 64
节点、8 轮；各轮只可引用更早轮证明。所有已参与的核心原邻接不变。

有限 prior 的 source-stage helper 为 `prior_source_geometry_row(obj)`；它
明确不声称保存冷读。`prior_source_points(obj)` 仅规范读取 `points` 或
已知 LINE／无 members 的 WALL_SEGMENT `start/end`；完整原对象和哈希不改。
actual reader 行则必须核对原 native 类型、全部 mm 顶点及其精确逆变换。
验证器可额外接收 `expected_influence_domain`，组件必须用它绑定共同目标域。
各次出入为不同 row，保存几何仍是原对象；新 type 不冒充 whole chain。

`independent_sections` 是端口初步观察。组件必须用完整实际 context 再调用
`measure_finite_port_sections`，并把最终截面全部读格并入实际证据域，再检查
此前排除的 remote finding。有限 prior 缺少完整原身份时 pending，不能把
完整对象改成几何相近的替代物。原文件保存前、保存后必须各自重算。

圆入口为 `certify_finite_circle_source(source, actual_row, full_source_object,
scope, *, roi, dpi, other_rows=(), forbidden_core_cells=())`。固定有理半角方向
产生真圆上的径向截面；它们不是圆弧弦。二次根用固定 128 位 dyadic 外包：
黑格最小圆距的下界、首白格最大圆距的上界构成保守平方半宽区间。该区间
包含所有满足相应精确径向条件的半宽，**不能单独证明某个半宽可用**。
最终同一参数向量必须用 `circle_cell_intersects` 和
`circle_point_strictly_outside` 对自有截面黑格与全部共同白格精确重验；纯代数
消去根号，不用近似距离决定 PASS。外包有额外候选只会导致精确拒绝或有限
搜索 pending，不能将数值搜索未找到解写成物理无解。

圆 row 的 `authorized_original_ring_cells_y_x0_x1` 限定可承担的原黑格；
`finite_arc_domain.authorized_query_cells_y_x0_x1` 限定可查询源格。context
相关性可以用预定 12 px 上界保守发现，但不是圆墨覆盖许可。共同 circle
scope 必须包含目标窗与所有实际直线、端口和径向截面读格；未授权查询不能
静默跳过圆。历史采样 replay、实际有限弧支持、独立径向界和共同模型结果
分别保存。

公开独立分派接受 `source_model="v2"`、完整 `prior_source_bindings` 和
`circle_source_objects`（list 或 ID map），标准 `font_bindings` 与两文件 hash
参数沿用。它只重建实际 targets，把原始 `actual_saved_prior_rows` 传给
`bounded_source_component.audit_bounded_bodies`，不以完整旧路径先行重证阻断
有限认证。旧 host 的局部来源／精确接触 locator 必须由共同组件补上对应
finite-port 证书及接点域，不能被当作旧完整路径的 PASS。缺组件时显式
`PENDING_BOUNDED_SOURCE_COMPONENT_NOT_READY`；v1 逻辑和默认入口保持。
