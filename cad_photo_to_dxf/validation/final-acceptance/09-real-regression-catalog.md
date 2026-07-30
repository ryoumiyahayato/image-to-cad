# 真实回归集清单

正式清单包含 12 次运行、10 个唯一完整页面、
3 个独立源文档和 22 个覆盖类别。
每项保留原文件、授权、页码/DPI、六类人工区域标注、预期对象类型和复核说明。

| Fixture | 源文档 | 页码 | DPI | 覆盖类别 |
| --- | --- | ---: | ---: | --- |
| `perspective-sample-plan` | sample-plan-photo | 1 | 96 | mobile_perspective_photo, landscape_drawing, leaders_and_arrows, dimensions, short_and_double_lines, no_title_block |
| `environment-plan-page-003-150dpi` | environment-building-scan-pdf | 3 | 150 | low_quality_scan, landscape_drawing, dense_text, complex_table, broken_frame, broken_table_lines, signature_adjacent_text, graphic_logo, leaders_and_arrows, dimensions, short_and_double_lines, dashed_and_dashdot_lines, dpi_150, mixed_chinese_english_numbers |
| `warehouse-index-page-001-150dpi` | warehouse-electrical-vector-pdf | 1 | 150 | digital_generated_pdf, portrait_drawing, dense_text, complex_table, wordmark_logo, graphic_logo, short_and_double_lines, dpi_150, mixed_chinese_english_numbers |
| `environment-scan-page-001-120dpi` | environment-building-scan-pdf | 1 | 120 | low_quality_scan, landscape_drawing, dense_text, complex_table, broken_frame, broken_table_lines, signature_adjacent_text, graphic_logo, leaders_and_arrows, dimensions, short_and_double_lines, dashed_and_dashdot_lines, mixed_chinese_english_numbers |
| `environment-scan-page-002-120dpi` | environment-building-scan-pdf | 2 | 120 | low_quality_scan, landscape_drawing, dense_text, broken_frame, signature_adjacent_text, leaders_and_arrows, dimensions, short_and_double_lines, dashed_and_dashdot_lines, mixed_chinese_english_numbers |
| `environment-scan-page-004-120dpi` | environment-building-scan-pdf | 4 | 120 | low_quality_scan, landscape_drawing, dense_text, complex_table, broken_frame, broken_table_lines, signature_adjacent_text, leaders_and_arrows, dimensions, short_and_double_lines, dashed_and_dashdot_lines, mixed_chinese_english_numbers |
| `environment-scan-page-008-120dpi` | environment-building-scan-pdf | 8 | 120 | low_quality_scan, landscape_drawing, dense_text, broken_frame, signature_adjacent_text, leaders_and_arrows, dimensions, short_and_double_lines, dashed_and_dashdot_lines, mixed_chinese_english_numbers |
| `environment-scan-page-014-120dpi` | environment-building-scan-pdf | 14 | 120 | low_quality_scan, landscape_drawing, dense_text, complex_table, broken_frame, broken_table_lines, signature_adjacent_text, wordmark_logo, graphic_logo, leaders_and_arrows, dimensions, short_and_double_lines, dashed_and_dashdot_lines, mixed_chinese_english_numbers |
| `warehouse-system-page-002-72dpi` | warehouse-electrical-vector-pdf | 2 | 72 | digital_generated_pdf, landscape_drawing, dense_text, complex_table, wordmark_logo, graphic_logo, leaders_and_arrows, short_and_double_lines, dashed_and_dashdot_lines, mixed_chinese_english_numbers |
| `warehouse-plan-page-003-72dpi` | warehouse-electrical-vector-pdf | 3 | 72 | digital_generated_pdf, landscape_drawing, dense_text, complex_table, wordmark_logo, graphic_logo, leaders_and_arrows, dimensions, short_and_double_lines, dashed_and_dashdot_lines, mixed_chinese_english_numbers |
| `warehouse-index-page-001-300dpi` | warehouse-electrical-vector-pdf | 1 | 300 | digital_generated_pdf, portrait_drawing, dense_text, complex_table, wordmark_logo, graphic_logo, short_and_double_lines, dpi_300, mixed_chinese_english_numbers |
| `warehouse-index-page-001-600dpi` | warehouse-electrical-vector-pdf | 1 | 600 | digital_generated_pdf, portrait_drawing, dense_text, complex_table, wordmark_logo, graphic_logo, short_and_double_lines, high_resolution_large_page, dpi_600, mixed_chinese_english_numbers |

阶段 12 严格回归 12/
12 通过，唯一页面
10；没有重录基线。CI 对零样本、缺类别、加载失败、
捕获异常、skip/xfail 和录制模式均设置硬失败。
