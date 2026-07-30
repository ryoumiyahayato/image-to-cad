# 当前基线与旧算法基线

| 基线 | Commit | 标签 | 测试 | 真实输出 |
| --- | --- | --- | ---: | ---: |
| 当前重构基线 | `5a1b06585b6f068bb5f61e16fd32b96e4f54275b` | `baseline/current-refactor-2026-07-28` | 205/205 | 3 |
| 旧算法基线 | `6a2aa545a534ea6fd50db8a5ba942a0a5db9e353` | `baseline/old-algorithm-pre-d9fbda7` | 156/156 | 3 |

两套配置快照、JUnit、三份 DXF、输入哈希、DXF 哈希与审计结果位于
`validation/system-refactor-baselines/`。旧基线没有
`straight_line_reconstruction.py`，输出中原生结构线数为 0，也没有
`FinalStructure.structure_id`；当前基线已具备结构线和结构 ID。
