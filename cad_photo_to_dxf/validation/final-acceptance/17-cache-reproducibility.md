# 缓存可复现性

缓存 v8 的键包含十项：输入内容 SHA-256、页码、DPI、OCR、算法版本、模型版本、
完整配置摘要、profile、FinalStructure schema 和关键阈值摘要。文件路径不是
内容身份。

阶段 11 的 10 个真实页全部缓存往返一致；同路径内容、OCR、DPI、算法、模型、
配置和 profile 七类变化全部未命中。阶段 12 九次独立运行均
`cache_key_match=true`，且每一规模三次结构 ID 完全相同。profile 默认
`disabled`，尝试启用未安装 profile 会失败。
