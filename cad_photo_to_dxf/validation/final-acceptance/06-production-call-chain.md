# 主生产调用链

桌面单页与批量入口：

`main.run_gui` → 活动 GUI → `ProductionProcessingService.process_page`
→ `trace_image_optimized` → `prepare_scan_page`
→ `recognize_text_candidates_optimized`
→ `reconstruct_straight_lines` → `detect_structural_rois`
→ `extend_lines_to_first_intersection`/`evaluate_structural_bridge`
→ `partition_content` → `arbitrate_content_candidates`
→ `finalize_content_ownership` → `text_output_decisions`
→ `trace_binary` → `build_final_structure`
→ `render_final_structure_preview` / `save_trace_cache`
/ `export_final_structure_dxf`。

单页和批量 GUI 只收集 `ProductionProcessingConfig`；没有第二套隐藏算法入口。
缓存恢复必须验证完整 `ProcessingCacheKey` 并重建完整 `FinalStructure`。
