# OCR 与文字输出

十页专项验证共有 1,188 个 OCR 候选：
197 个原生可编辑 `TEXT`、
977 个 `TEXT_FALLBACK_OUTLINE`、
14 个 `RESIDUAL_GRAPHIC`。降级原因是
`replacement_unsafe` 977 次和
`confidence_below_contract`
14 次。

原生 TEXT 写入内容、字体、位置、旋转、置信度、替换安全状态和
`TEXT_OUTPUT_CONTRACT` XDATA；fallback 明确不可编辑并保留源轮廓；低置信度
残留不得称为文字或签名。字体显示方式不改变可编辑性。130/130 专项检查、
DXF 审计和重复语义稳定性均通过。
