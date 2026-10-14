"""Read JSON/CSV and frozen numerical inputs. No pickle loading and no learner fit."""

import ast
import csv
import hashlib
import io
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "colab_cpu_handoff"))
import runtime

BASELINE = PROJECT / "local-artifacts/product-fix-p3b/colab-cpu-20261008-001"
NOTEBOOK_SHA = "72c0c10ad9a4d7251f884fab04677d214de880755658bbcff5deba2fac0496b1"
INPUT_SHA = "a73382b74d1e559d5bde5ec06eeb729c903a3b07a73cbf4263e58c415f5f52f6"
FINAL_SHA = "4a4faa39a2a56811f6723fa0ccfa2322320080023c59c35a2179f40f08942795"
RESULT_SHA = "07a165eaf28da9f705861ba4e48fb1c7a3a04d9dee3da79bba5e3bdaa5f9864c"
RESULT_NAMES = {"README.txt", "abstention-evaluation.json", "checksums.sha256", "confusion-matrix.csv",
                "data-identity.json", "environment.json", "logistic-pipeline.joblib", "metrics.json",
                "predictions.csv", "rng-state.json", "run-metadata.json", "training-config.json"}


def anchors_from_notebook(nb):
    source = "".join(next(c["source"] for c in nb["cells"] if c["id"] == "A1-preflight"))
    tree = ast.parse(source)
    assignment = next(n for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "ANCHORS" for t in n.targets))
    return ast.literal_eval(assignment.value)


def verified_result_bytes(path, expected_sha=RESULT_SHA):
    path = Path(path)
    runtime.require(path.is_file(), "MISSING_RESULTS_ZIP: provide p3b-baseline-results.zip; no summary substitutes")
    runtime.require(runtime.sha(path) == expected_sha and path.stat().st_size == 24353, "First result ZIP identity mismatch")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        expected = {"p3b-baseline-results/" + n for n in RESULT_NAMES}
        runtime.require(len(infos) == len(expected) and {i.filename for i in infos} == expected, "Unexpected result ZIP members")
        runtime.require(sum(i.file_size for i in infos) < 2_000_000, "Unexpected result size")
        runtime.require(archive.testzip() is None, "Result ZIP CRC failed")
        payload = {PurePosixPath(i.filename).name: archive.read(i) for i in infos}
    checksums = {}
    for line in payload["checksums.sha256"].decode().splitlines():
        member_digest, name = line.split("  ", 1)
        runtime.require(name not in checksums and name in RESULT_NAMES - {"checksums.sha256"}, "Invalid result checksum member")
        checksums[name] = member_digest
    runtime.require(set(checksums) == RESULT_NAMES - {"checksums.sha256"}, "Result checksum coverage incomplete")
    for name, expected in checksums.items():
        runtime.require(runtime.hash_bytes(payload[name]) == expected, "Result member checksum mismatch: " + name)
    return payload


def parse_predictions(payload, rows):
    predictions = list(csv.DictReader(io.StringIO(payload["predictions.csv"].decode("utf-8"))))
    runtime.require([r["sample_id"] for r in predictions] == [r["sample_id"] for r in rows], "Prediction ID/order mismatch")
    for p, row in zip(predictions, rows):
        for name in ("split", "label", "role", "source_family_id", "source_drawing_id", "target_kind", "record_reference", "truth_reference"):
            runtime.require(p[name] == row[name], "Prediction truth/metadata mismatch: " + name)
        dpi = None if not p["source_dpi"] else float(p["source_dpi"])
        runtime.require(dpi == row["source_dpi"], "Prediction DPI mismatch")
        scores = [float(p["score_" + c]) for c in runtime.CLASSES]
        runtime.require(np.isfinite(scores).all() and min(scores) >= 0 and max(scores) <= 1
                        and abs(sum(scores) - 1) < 1e-10, "Invalid score distribution")
        runtime.require(p["prediction"] == runtime.CLASSES[int(np.argmax(scores))]
                        and float(p["max_uncalibrated_score"]) == max(scores), "Prediction/score mismatch")
        p["max_uncalibrated_score"] = float(p["max_uncalibrated_score"])
        for c, value in zip(runtime.CLASSES, scores): p["score_" + c] = value
        for t in (0.5, 0.8, 0.9, 0.95, 0.99, 0.995):
            name = "abstain_at_" + str(t)
            runtime.require(p[name] in ("True", "False"), "Invalid abstention flag")
            p[name] = p[name] == "True"
            runtime.require(p[name] == (max(scores) < t), "Frozen threshold flag mismatch")
        p["source_dpi"] = row["source_dpi"]
    return predictions


def table(headers, rows):
    return "\n".join([" | ".join(headers), " | ".join("---" for _ in headers)]
                     + [" | ".join(str(v) for v in row) for row in rows]) + "\n"


def percent(value):
    return "N/A" if value is None else f"{100 * value:.2f}%"


def analyze(result_path):
    nb_path = BASELINE / "p3b-colab-cpu-baseline.ipynb"
    runtime.require(runtime.sha(nb_path) == NOTEBOOK_SHA, "Original notebook changed")
    runtime.require(runtime.sha(BASELINE / "p3b-colab-inputs.zip") == INPUT_SHA, "Original input changed")
    runtime.require(runtime.sha(PROJECT / "docs/product-fix-p3b/FINAL-TRAINING-DATA-FREEZE.json") == FINAL_SHA, "Freeze changed")
    nb = json.loads(nb_path.read_text(encoding="utf-8")); anchors = anchors_from_notebook(nb)
    inputs = runtime.archive_payload(BASELINE / "p3b-colab-inputs.zip", anchors)
    rows, matrices, docs, identity = runtime.validate_payload(inputs, anchors)
    payload = verified_result_bytes(result_path)
    objects = {name: json.loads(data) for name, data in payload.items() if name.endswith(".json")}
    runtime.require(objects["data-identity.json"] == identity, "Exported input/config identity differs from frozen input")
    runtime.require(objects["training-config.json"] == anchors["config"], "Exported baseline parameter/threshold change")
    runtime.require(objects["environment.json"]["packages"] == runtime.PINS, "Reported dependency versions differ")
    runtime.require(objects["run-metadata.json"]["model_sha256"] == runtime.hash_bytes(payload["logistic-pipeline.joblib"]),
                    "Exported model byte identity mismatch")
    predictions = parse_predictions(payload, rows["validation"])
    pred = np.array([r["prediction"] for r in predictions]); scores = np.array([r["max_uncalibrated_score"] for r in predictions])
    thresholds = anchors["config"]["thresholds_for_reporting"]
    metrics = objects["metrics.json"]
    summary = runtime.summary(rows["validation"], pred, scores, thresholds)
    runtime.require(summary == metrics["overall"], "Recomputed overall metrics differ")
    for field in ("source_family_id", "source_drawing_id", "source_dpi", "target_kind"):
        recomputed = {}
        for name in metrics["by_" + field]:
            indices = [i for i, row in enumerate(rows["validation"]) if
                ("UNKNOWN_DPI" if row[field] is None and field == "source_dpi" else str(row[field])) == name]
            recomputed[name] = runtime.summary([rows["validation"][i] for i in indices], pred[indices], scores[indices], thresholds)
        runtime.require(recomputed == metrics["by_" + field], "Group metrics mismatch: " + field)
    matrix_csv = list(csv.DictReader(io.StringIO(payload["confusion-matrix.csv"].decode())))
    runtime.require([r["truth"] for r in matrix_csv] == runtime.CLASSES and
        [[int(r[c]) for c in runtime.CLASSES] for r in matrix_csv] == summary["confusion_matrix"], "Confusion CSV mismatch")
    abstention = objects["abstention-evaluation.json"]
    runtime.require(abstention["coverage_table"] == summary["abstention_coverage"]
                    and abstention["ambiguous_cases"] == [r for r in predictions if r["label"] == "AMBIGUOUS"], "Abstention JSON mismatch")
    validation_object = {"metrics": metrics, "predictions": predictions, "abstention": abstention}
    runtime.require(runtime.hash_bytes(runtime.canonical(validation_object)) == objects["run-metadata.json"]["validation_sha256"],
                    "Validation object identity mismatch")
    train_single = [r for r in rows["train"] if r["label"] == runtime.CLASSES[0]]
    val_single = [r for r in rows["validation"] if r["label"] == runtime.CLASSES[0]]
    norm = docs["feature-schema.json"]["training_normalization"]
    feature_comparison = []
    populations = {"train_SINGLE": train_single, "validation_SINGLE": val_single,
        "validation_SINGLE_110": [r for r in val_single if r["source_dpi"] == 110],
        "validation_SINGLE_unknown": [r for r in val_single if r["source_dpi"] is None],
        "validation_OTHER": [r for r in rows["validation"] if r["label"] == "OTHER"]}
    for name, population in populations.items():
        x = np.array([r["features"] for r in population], dtype=np.float64)
        feature_comparison.append({"group": name, "count": len(population),
            "profile_present": sum(r["profile_present"] for r in population),
            "target_kinds": dict(Counter(r["target_kind"] for r in population)),
            "raw_feature_means": dict(zip(anchors["feature_order"], x.mean(0).tolist())),
            "train_standardized_feature_means": dict(zip(anchors["feature_order"],
                ((x - np.array(norm["mean"])) / np.array(norm["scale"])).mean(0).tolist()))})
    source = "".join(next(c["source"] for c in nb["cells"] if c["id"] == "A1-preflight"))
    train_ast = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "train_manual")
    fits = [n for n in ast.walk(train_ast) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "fit"]
    runtime.require(len(fits) == 1 and ast.unparse(fits[0].args[0]) == "matrices['train']", "Unexpected fit input in original source")
    report = {"RESULT_PACKAGE_INTEGRITY": "PASS", "RESULT_JSON_CSV_RECOMPUTATION": "PASS", "MODEL_DESERIALIZED": "NO",
        "LOCAL_MODEL_FIT": "NOT_RUN", "FIRST_RUN_USER_REPORTED": "PRE-FLIGHT/TRAIN/VALIDATE/EXPORT completed in Colab",
        "INDEPENDENT_RUN_COUNT_VERIFICATION": "NOT_VERIFIED", "REMOTE_ACTUAL_FIT_POPULATION_VERIFICATION": "NOT_VERIFIED",
        "STATIC_TRAIN_SOURCE_CHECK": "Pipeline(StandardScaler, LogisticRegression); only train matrix fit; convergence errors stop",
        "FROZEN_INPUT_LEAKAGE_CHECK": "PASS; IDs/drawings/families/source SHA/crop pixels disjoint in inspected input",
        "results_path": str(Path(result_path).resolve()), "results_size": Path(result_path).stat().st_size,
        "results_sha256": runtime.sha(result_path), "members": [
            {"name": name, "size_bytes": len(data), "sha256": runtime.hash_bytes(data)} for name, data in sorted(payload.items())],
        "summary": summary, "groups": {k: v for k, v in metrics.items() if k.startswith("by_")},
        "feature_comparison": feature_comparison, "ambiguous_cases": abstention["ambiguous_cases"],
        "train_profile_available": sum(r["profile_present"] for r in rows["train"]),
        "validation_profile_available": sum(r["profile_present"] for r in rows["validation"]),
        "environment_reported": objects["environment.json"]}
    text = "IMAGE TO CAD — P3B 首轮结果中文审查报告\nEXPLORATORY_BASELINE_ONLY\n\n"
    text += f"只读结果包：{Path(result_path).resolve()}\n大小：24,353 bytes\nSHA256：{runtime.sha(result_path)}\n"
    text += "12 个 ZIP 成员均已读取，CRC、11 个数据成员 SHA256、包内清单覆盖通过；清单自身哈希也记入本地核验。没有解包或反序列化 joblib。\n\n"
    text += "结果 JSON/CSV 直接证明：50 条预测对应冻结验证 ID/标签，其中 49 个定类样本认对 28 个（57.14%）；macro-F1=0.533745947539051，balanced accuracy=61.3853%。\n"
    text += table(["真实类 → 预测类", "SINGLE", "PARALLEL", "OTHER"],
                  [[c, *summary["confusion_matrix"][i]] for i, c in enumerate(runtime.CLASSES)])
    text += "\n" + table(["类别", "precision", "recall", "support"], [[c, percent(summary["per_class"][c]["precision"]),
                  percent(summary["per_class"][c]["recall"]), summary["per_class"][c]["support"]] for c in runtime.CLASSES])
    text += "\n主要错误是漏识别真实 SINGLE：22 个只认对 5 个，16 个被判 OTHER，1 个被判 PARALLEL。真实 PARALLEL → SINGLE 记录为 0/20；小样本观察不证明零风险或生产合并安全。OTHER → SINGLE 为 2/7。\n"
    text += "SINGLE 行动覆盖率为 8/50（16%），其中含 1 个 AMBIGUOUS 输出；定类样本中的 SINGLE 预测为 7 个，正确 5 个。不能把 8 个行动输出全部视为已确认正确。\n\n"
    text += "拒判与接受样本错误率（不挑最佳阈值；拒判分母全部50，错误率分母仅接受的定类样本，AMBIGUOUS 单列）：\n"
    threshold_rows = []
    for item in summary["abstention_coverage"]:
        accepted = item["selective_accuracy"]["denominator"]; errors = accepted - item["selective_accuracy"]["numerator"]
        threshold_rows.append([item["threshold"], f"{item['all_validation_abstention']['numerator']}/50", percent(item["all_validation_abstention"]["rate"]),
            f"{errors}/{accepted}", percent(errors / accepted if accepted else None), f"{item['SINGLE_action_coverage']['numerator']}/50",
            f"{item['FALSE_MERGE_RATE']['numerator']}/20", f"{item['ambiguous_rejected']['numerator']}/1"])
    text += table(["阈值", "拒判数", "拒判率", "接受定类错误数", "错误率", "SINGLE覆盖", "FMR", "AMBIG拒判"], threshold_rows)
    text += "0.95 仅接受4个定类样本且认对4个；不能据此选阈值或宣布安全。0.99/0.995 全拒判，接受错误率是 N/A，不能写成0%。\n"
    text += f"AMBIGUOUS 样本 {abstention['ambiguous_cases'][0]['sample_id']} 被输出 SINGLE，未校准分数0.919956；0.5/0.8/0.9接受，0.95/0.99/0.995拒判。仅1个观察案例，不证明拒判可靠。\n\n"
    for field in ("source_family_id", "source_drawing_id", "source_dpi", "target_kind"):
        text += "分组：" + field + "\n"
        text += table(["组", "全样本/定类", "认对/定类", "accuracy", "macro-F1", "balanced acc", "SINGLE认对/真实", "FMR"],
            [[name, f"{v['all_samples']}/{v['classification_samples']}", f"{v['overall_accuracy_auxiliary']['numerator']}/{v['classification_samples']}",
              percent(v["overall_accuracy_auxiliary"]["rate"]), f"{v['macro_F1']:.6f}" if v["macro_F1"] is not None else "N/A", percent(v["balanced_accuracy"]),
              f"{v['confusion_matrix'][0][0]}/{v['per_class'][runtime.CLASSES[0]]['support']}",
              f"{v['FALSE_MERGE_RATE']['numerator']}/{v['FALSE_MERGE_RATE']['denominator']}"] for name, v in metrics["by_" + field].items()]) + "\n"
    text += "诊断：以下由冻结数值输入与预测交叉核对得到，属于相关性和静态契约证据，不是原因实验。\n"
    text += "1. 来源/DPI完全混杂：未知DPI的13个验证样本全部来自A2-SG-008/US_NARA_BUILDING9；该来源真实SINGLE认对5/6。110 DPI组的16个真实SINGLE全部判OTHER。DPI、源图、成像风格与目标形态无法在这份划分中独立分离；不能断言DPI导致错误，也不能把未知DPI当成优越尺度。110指有效渲染DPI，不等于原扫描DPI。\n"
    text += "2. 目标形态与可用特征发生明显分布变化：训练真实SINGLE为22 PAIR＋13 SINGLE＋3 CONTROL，验证为2 PAIR＋20 SINGLE；PAIR不是训练标签，但pair_present进入18特征。训练94条中46条有profile，验证50条全部没有；真实SINGLE训练20/38有profile，验证0/22。距离/重叠与profile缺失时沿用零默认值。这个差异可能使模型依赖提名类型/缺失模式，但未经系数审查或受控实验不能证明。\n"
    text += "3. 归一化：重新计算原输入训练均值/方差/scale与冻结18维统计一致；原源码只对94条训练矩阵fit Pipeline，并在fit后检查scaler统计。没有发现输入包层面的标准化身份错误。这是静态源码和冻结数值核对，不能独立证明远端实际fit对象或只训练过一次。joblib未加载，其运行时scaler参数尚未独立核验。\n"
    text += "4. 像素尺度：原特征的距离/重叠除256、宽度除16、DPI除600是固定数值编码，不是工程物理单位归一化。灰度梯度按像素差统计。110组真实SINGLE的gradient_x/gradient_y均值约0.0500/0.0547，未知DPI组约0.0211/0.0221；按冻结训练统计换算均值z约1.68/1.20与-0.26/-0.53。这里只是特征分布差异，不能直接归因为DPI。没有改裁片或尺度。\n"
    text += "5. 信息区分度：验证SINGLE与OTHER的mean_gray均值约0.9337/0.9341，dark_fraction约0.0657/0.0650，profile均缺失，部分外观汇总特征相近。18维汇总是否足以表达被高亮的结构语义仍需后续受控研究；不在本轮改变特征或重新训练。\n"
    text += "6. 标注口径：V2要求判断被高亮目标；SINGLE是单个结构/规则笔画，OTHER是明确提名的字形、填充、图形或伪影等。PAIR/SINGLE/CONTROL是提名显示类型，不能等同三类真值。结果CSV当前标签与冻结有效标签逐样本一致；本轮没有打开原图做新的人工语义复核，也不宣布所有人类标签绝对正确。\n\n"
    text += "证据边界：\n- 直接验证：结果成员字节完整性；JSON/CSV指标一致性；当前包的输入、配置、标签和阈值身份；50条预测与冻结视图一致。\n"
    text += "- 静态验证：原本地/嵌入notebook的fit入口仅用训练集；冻结输入ID/图样/来源族/源SHA/裁片像素哈希不重叠。\n"
    text += "- 仍未独立验证：整个Colab会话的执行历史、确实只训练一次、远端是否修改过内存对象、模型实际scaler/系数、历史所有访问是否无泄漏、Drive持久化。用户报告首轮完成，本包与该报告一致；配置文件本身不是独立执行审计。\n"
    text += "本轮未fit、未调阈值、未训练CNN、未读blind文件、未修改标签/划分或生产几何/DXF/OCR。完整分组指标及特征均值证据保存在LOCAL-VERIFICATION.json。\n"
    return report, text, nb, anchors
