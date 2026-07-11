# 样例数据说明

## `test.jpg`

该文件在审计基线提交中已经存在，但仓库当前没有提供可核验的原始来源、作者、拍摄设备、许可协议或对应原始 CAD。

因此它目前只能用于开发期冒烟测试，不能用于：

- 对外展示模型精度；
- 声称真实手机照片数据集覆盖；
- 计算设计尺寸误差；
- 训练或再分发；
- 证明制造、施工或工程交付能力。

在来源和许可得到确认前，任何 Release 都不应把该文件描述为正式 benchmark 或 ground truth。

正式夹具应迁入 `tests/fixtures/<fixture-id>/`，并提供符合 `tests/fixtures/fixture-manifest.schema.json` 的 `manifest.json`，至少记录输入 SHA-256、来源和许可、纸张角点、坐标空间、原始 CAD、允许误差和预期验证结果。
