# GUI 与 DXF 一致性

活动 GUI 单页与批量均调用 `ProductionProcessingService`。缓存恢复、文字复核、
预览和导出都以同一不可变 `FinalStructure` 为边界；导出前强制比较预览结构 ID。
十页执行 80 项逐页检查和 5 项架构检查，全部通过；10/10 结构 ID 与阶段 10
完全一致，10/10 缓存往返一致。

阶段 12 性能样本的九次预览、缓存恢复和 DXF 导出也逐次使用相同 structure ID，
三种规模均确定性一致，DXF 审计错误总数 0。
