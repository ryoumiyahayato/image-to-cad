"""Build a separate Drive-save notebook and read-only review. Never trains or mounts Drive."""

import argparse
import ast
import inspect
import json
import sys
import tempfile
import types
from unittest.mock import patch
from pathlib import Path

import jsonschema

import review
import drive_saver
import save_tests

PROJECT = review.PROJECT
HERE = Path(__file__).resolve().parent


def snapshot(paths):
    return {str(p.resolve()): review.runtime.sha(p) for p in paths if p.is_file()}


def production_paths():
    return [p for folder in (PROJECT / "cad_photo_to_dxf/app", PROJECT / "cad_photo_to_dxf/tests")
            for p in folder.rglob("*") if p.is_file() and p.suffix in (".py", ".json") and "__pycache__" not in p.parts]


def make_cell(kind, name, source):
    c = {"id": name, "cell_type": kind, "metadata": {"name": name}, "source": source.splitlines(keepends=True)}
    if kind == "code": c.update(execution_count=None, outputs=[])
    return c


def build_notebook(original, anchors, first_identity):
    a1 = "".join(next(c["source"] for c in original["cells"] if c["id"] == "A1-preflight"))
    tree = ast.parse(a1)
    anchor_node = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t,ast.Name) and t.id == "ANCHORS" for t in n.targets))
    helper = "".join(a1.splitlines(keepends=True)[:anchor_node.end_lineno])
    original_export = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name == "export_manual")
    exported = ast.parse(ast.get_source_segment(a1, original_export)).body[0]
    exported.name = "export_local_manual"
    exported.body = [n for n in exported.body if not (
        isinstance(n,ast.ImportFrom) and n.module == "google.colab") and not (
        isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute)
        and isinstance(n.value.func.value,ast.Name) and n.value.func.value.id == "files" and n.value.func.attr == "download")]
    for n in ast.walk(exported):
        if isinstance(n,ast.Constant) and n.value == "EXPORT PASS:": n.value = "EXPORT_LOCAL_READY:"
    helper = helper.replace(ast.get_source_segment(a1,original_export),ast.unparse(exported))
    saver = (HERE / "drive_saver.py").read_text(encoding="utf-8")
    # Byte/checksum-only first-result validator. Qualifier adaptation does not load a model.
    validator = inspect.getsource(review.verified_result_bytes)
    validator = validator.replace("runtime.require", "require").replace("runtime.sha", "sha").replace("runtime.hash_bytes", "hash_bytes")
    code = helper + "\n" + saver + "\nRESULT_SHA = " + repr(review.RESULT_SHA) + "\nRESULT_NAMES = set(" + repr(sorted(review.RESULT_NAMES)) + ")\n" + validator
    code += "\nFIRST_RESULT_IDENTITY = " + repr(first_identity) + '''
PREFLIGHT = globals().get("PREFLIGHT")
TRAIN_RUN = globals().get("TRAIN_RUN")
SAVE_SESSION = globals().get("SAVE_SESSION")
RESULT_ZIP = globals().get("RESULT_ZIP")
INPUT_ZIP = Path("/content/p3b-colab-inputs.zip")
FIRST_RESULT_ZIP = Path("/content/p3b-baseline-results.zip")
'''
    cells = [make_cell("markdown", "intro", "# P3B CPU 基线：独立 Drive 阶段保存版\n"
        "首次训练已完成。本版不会自动重训、改数据/参数/阈值或加载上传的joblib。\n"
        "**保留首次结果的推荐路径**：上传本notebook与已有 `p3b-baseline-results.zip` → A0/A0b → DRIVE_INIT → E1-archive-first-result。无需点击B1或C1。\n"
        "原输入 `p3b-colab-inputs.zip` 只在测试A1预检或以后明确手动运行基线时上传。选择CPU，逐格运行，不点全部运行。\n"
        "自动化仅针对保存；TRAIN / VALIDATE / EXPORT 均保留人工确认。\n"),
        make_cell("markdown", "dependencies", "## A0：依赖\n运行A0-install；如安装了版本，重启会话后运行A0b-helpers。安装失败必须停止。\n"),
        next(c for c in original["cells"] if c["id"] == "A0-install"),
        make_cell("code", "A0b-helpers", code),
        make_cell("markdown", "drive-notice", "## DRIVE_INIT：授权与唯一运行目录\n"
            "**挂载后notebook代码技术上可访问你的整个Drive，并非只授权输出目录。** 本程序仅写入 `MyDrive/Image-to-CAD-ML/P3B/runs/唯一run_id`，不改共享权限、不上传图纸/裁片/整个项目。\n"
            "输入DRIVE后由你在Colab界面完成授权。初始化会先写入并回读小文件；失败停止。\n"
            "只有 `DRIVE_INIT PASS` 才继续。完成标记仅说明挂载路径回读通过，独立Drive服务确认仍为NOT_RUN。\n"
            "环境回收/关闭风险仍存在；这不是保活或Logistic内部迭代恢复方案。\n"),
        make_cell("code", "DRIVE_INIT", '''if globals().get("SAVE_SESSION") is not None:
    raise RuntimeError("This session already has a unique run; do not reinitialize or overwrite it")
SAVE_SESSION = initialize_drive()
'''),
        make_cell("markdown", "existing-first-guide", "## E1：仅归档已完成的首次结果（推荐）\n"
            "上传24,353字节的原 `p3b-baseline-results.zip` 后运行本格，输入ARCHIVE。\n"
            "校验已审查ZIP哈希、全部成员清单、输入身份与配置后原样保存；只读字节，不加载模型，不训练。保存成功后本轮可停止。\n"),
        make_cell("code", "E1-archive-first-result", '''ensure_save_session(SAVE_SESSION)
require(not TRAIN_RUN and not SAVE_SESSION.completed, "Archive first result in an empty new run; do not mix with a future training run")
require(input("输入 ARCHIVE，原样归档已完成的首次结果（不训练）：") == "ARCHIVE", "Archive not started")
FIRST_PAYLOAD = verified_result_bytes(FIRST_RESULT_ZIP)
require(json.loads(FIRST_PAYLOAD["data-identity.json"]) == FIRST_RESULT_IDENTITY, "First-result input identity mismatch")
require(json.loads(FIRST_PAYLOAD["training-config.json"]) == ANCHORS["config"], "First-result configuration mismatch")
FIRST_CONTENT = {
    "p3b-baseline-results.zip": FIRST_RESULT_ZIP.read_bytes(),
    "archive-record.json": save_json_bytes({"original_zip_sha256": RESULT_SHA, "size_bytes": 24353,
        "archived_at_utc": save_time(), "model_deserialized": False, "training_run_here": False,
        "scope": "User's completed first Colab result, preserved byte-for-byte"})}
save_generated_stage(SAVE_SESSION, "FIRST_BASELINE", lambda: (FIRST_CONTENT, FIRST_RESULT_IDENTITY))
'''),
        make_cell("markdown", "preflight-guide", "## A1：预检后自动保存\n"
            "只做数据/环境预检，无模型训练。需要原输入ZIP，成功后保存预检报告、环境、输入哈希、特征及标签/配置契约。\n"
            "PRE-FLIGHT PASS之后还须看到 `SAVE_COMPLETE stage=A1`；保存失败会阻断后续阶段。\n"),
        make_cell("code", "A1-preflight-save", '''ensure_save_session(SAVE_SESSION)
PREFLIGHT = None
PREFLIGHT = preflight(INPUT_ZIP, ANCHORS)
save_generated_stage(SAVE_SESSION, "A1", lambda: preflight_save_content(PREFLIGHT, ANCHORS))
'''),
        make_cell("markdown", "train-guide", "## B1：仅在用户另行决定手动运行基线时使用\n"
            "本轮已完成首次基线，无需点击本格。A1保存成功后才能运行；保留TRAIN输入确认。\n"
            "完成后立即保存完整pipeline（含scaler）、配置和日志。SAVE_FAILED时只重试保存或下载，不重新fit。\n"),
        make_cell("code", "B1-train-save", '''ensure_save_session(SAVE_SESSION, previous="A1")
require("FIRST_BASELINE" not in SAVE_SESSION.completed, "First baseline already archived; do not retrain in this run")
require(TRAIN_RUN is None, "Training already completed; do not fit again. For SAVE_FAILED use save-only retry")
TRAIN_RUN = train_manual(PREFLIGHT, ANCHORS)
save_generated_stage(SAVE_SESSION, "B1", lambda: training_save_content(PREFLIGHT, ANCHORS, TRAIN_RUN))
'''),
        make_cell("markdown", "validate-guide", "## C1：人工验证后自动保存\n保留VALIDATE输入确认；只评估一次，不挑阈值。保存指标/分组、预测、混淆矩阵及全部固定阈值报告。\n"),
        make_cell("code", "C1-validate-save", '''ensure_save_session(SAVE_SESSION, previous="B1")
METRICS = validate_manual(PREFLIGHT, ANCHORS, TRAIN_RUN)
save_generated_stage(SAVE_SESSION, "C1", lambda: validation_save_content(PREFLIGHT, ANCHORS, TRAIN_RUN))
'''),
        make_cell("markdown", "export-guide", "## D1：人工导出后自动保存\n保留EXPORT输入确认。先生成临时结果ZIP，再保存ZIP/哈希清单到Drive。备用下载使用下方MANUAL_DOWNLOAD。\n"),
        make_cell("code", "D1-export-save", '''ensure_save_session(SAVE_SESSION, previous="C1")
require(RESULT_ZIP is None, "Final ZIP already generated; use save-only retry or MANUAL_DOWNLOAD")
RESULT_ZIP = export_local_manual(PREFLIGHT, ANCHORS, TRAIN_RUN)
save_generated_stage(SAVE_SESSION, "D1", lambda: export_save_content(RESULT_ZIP, TRAIN_RUN["identity"], SAVE_SESSION.completed))
'''),
        make_cell("markdown", "save-retry-guide", "## SAVE_RETRY_ONLY：可选，一次有依据的保存重试\n"
            "先根据报错修正挂载/网络/权限等原因，再运行本格并说明已修正事项。\n"
            "整个run最多一次重试，仅复制已生成并核对哈希的临时成果，创建新的attempt目录；不训练、不重新验证。\n"
            "若仍失败或临时哈希变化，请手动下载。不自动删除失败attempt或旧run。\n"),
        make_cell("code", "SAVE_RETRY_ONLY", "retry_pending_save_only(SAVE_SESSION)\n"),
        make_cell("markdown", "download-guide", "## MANUAL_DOWNLOAD：备用手动下载\n"
            "保存失败后临时成果仍保留。此格无需Drive成功：下载已生成的最终ZIP，或失败阶段的本地备份ZIP。\n"
            "也可用左侧文件区按打印路径下载。没有完整COMPLETE.json的attempt不能视为已保存成果。\n"),
        make_cell("code", "MANUAL_DOWNLOAD", "download_local_backup(globals().get('SAVE_SESSION'), globals().get('RESULT_ZIP'))\n")]
    return {"nbformat": 4, "nbformat_minor": 5, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"}, "colab": {"name": "p3b-colab-cpu-baseline-drive.ipynb", "provenance": []}}, "cells": cells}


def static_check(nb, original, anchors):
    schema = json.loads((HERE.parent / "colab_cpu_handoff/nbformat.v4.5.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft4Validator(schema).validate(nb)
    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            ast.parse("".join(cell["source"]), filename=cell["id"])
            review.runtime.require(cell["execution_count"] is None and not cell["outputs"], "Notebook must be unexecuted")
    helper = "".join(next(c["source"] for c in nb["cells"] if c["id"] == "A0b-helpers"))
    orig = "".join(next(c["source"] for c in original["cells"] if c["id"] == "A1-preflight"))
    def definitions(source):
        return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(source).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    new_defs, old_defs = definitions(helper), definitions(orig)
    preserved = [name for name in old_defs if name != "export_manual"]
    review.runtime.require(all(old_defs[name] == new_defs[name] for name in preserved), "Original data/training/validation functions changed")
    new_tree = ast.parse(helper)
    new_anchors = ast.literal_eval(next(n.value for n in new_tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ANCHORS' for t in n.targets)))
    review.runtime.require(new_anchors == anchors, "Data IDs/class mapping/config/threshold anchors changed")
    fit_calls = [n for n in ast.walk(new_tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='fit']
    review.runtime.require(len(fit_calls)==1, "Unexpected new fit call")
    # Only imports/definitions/constant assignments at helper top level; no stage action on helper loading.
    for node in new_tree.body:
        if isinstance(node,ast.Expr):
            review.runtime.require(isinstance(node.value,ast.Constant), "Unexpected helper top-level action")
        review.runtime.require(not isinstance(node, (ast.For,ast.While,ast.With,ast.Try)), "Unexpected top-level activity")
    return {"NOTEBOOK_SCHEMA": "PASS", "ALL_CODE_AST": "PASS", "CONTRACT_ANCHORS_UNCHANGED": "PASS",
            "ORIGINAL_FUNCTION_AST_IDENTICAL": preserved, "FIT_CALLS": "Only original train_manual; not executed locally",
            "COLAB_EXECUTION": "NOT_RUN", "REAL_DRIVE_AUTHORIZATION": "NOT_RUN", "REAL_DRIVE_READBACK": "NOT_RUN",
            "DRIVE_SERVICE_INDEPENDENT_CONFIRMATION": "NOT_RUN"}


def readme():
    return """P3B Drive阶段保存版 — 一页操作说明

首次基线已完成，本轮不需要再训练。
推荐保留首次成果：
1. 打开 https://colab.research.google.com/ ，上传 p3b-colab-cpu-baseline-drive.ipynb，选择CPU/硬件加速器无。
2. 上传原 p3b-baseline-results.zip 到左侧文件区，保留文件名。它在本机Downloads，24,353 bytes；不能用其他结果摘要替代。
3. 先点击 A0-install；若安装依赖，按提示重启会话，再运行 A0b-helpers。
4. 点击 DRIVE_INIT，输入 DRIVE，随后只在Colab界面完成授权。挂载技术上让notebook访问整个Drive，并非只授权输出目录；本程序只写指定run目录，不改共享权限。
5. 必须看到 DRIVE_INIT PASS。然后点击 E1-archive-first-result，输入 ARCHIVE；原结果ZIP经校验后原样保存，不加载模型、不训练。看到 SAVE_COMPLETE stage=FIRST_BASELINE 即可停止。

若要验证新版A1保存：另上传原 p3b-colab-inputs.zip，运行 A1-preflight-save。必须同时看到 PRE-FLIGHT PASS 和 SAVE_COMPLETE stage=A1。本轮无需点击B1/C1/D1。
保留给以后明确手动运行的入口：B1输入TRAIN，完成即保存pipeline/配置/日志；C1输入VALIDATE，完成即保存指标/预测/混淆矩阵/固定阈值报告；D1输入EXPORT，完成即保存最终ZIP及哈希清单。每阶段要求上一阶段已经保存。已归档首次结果的run不允许重新训练。

保存位置：MyDrive/Image-to-CAD-ML/P3B/runs/时间戳-UUID/阶段/attempt-UUID/
每个阶段先在Colab临时目录生成文件、大小和SHA256，再写新文件并回读核验，最后写COMPLETE.json。SAVE_COMPLETE只表示挂载路径回读通过；DRIVE_SERVICE_CONFIRMED=NOT_RUN，独立服务端持久化尚未确认。你可在Drive网页核对run/COMPLETE.json和文件，必要时下载后再校验；本程序不冒称这些检查已做过。

失败：SAVE_FAILED会显示阶段、原因、临时目录和备用ZIP路径，并阻断后续计算/保存。先点击MANUAL_DOWNLOAD，或从左侧文件区按打印路径下载。若已经明确修正故障，可点击SAVE_RETRY_ONLY并说明原因；整个run最多一次，只保存已有临时成果，不重训、不重新评估。失败attempt不视为完整成果，不自动清理旧目录。

临时结果可能随Colab回收而丢失；及时下载。Drive保存不保证Colab无限运行，不支持从Logistic内部迭代点恢复。不要点击全部运行。
存储仅含必要模型/契约/指标/预测/日志和最终ZIP，不上传工程、原图、裁片库、缓存、密码或token。B1单独pipeline用于尽早保住模型；D1最终ZIP包含同一模型供离线交接。C1分文件用于阶段审查，D1统一ZIP用于下载；成功阶段不重复保存，最多一次失败保存重试创建独立attempt。FIRST_BASELINE归档路径只保留一个原ZIP及归档记录，不另解包存储。
本版本地schema/语法/契约及保存故障模拟已通过；真实Colab授权、挂载、小文件回读、阶段保存仍须你在Colab确认。本机本轮没有训练或访问Drive。
"""


def embedded_archive_test(nb, result_path):
    module = types.ModuleType("p3b_embedded_notebook_test")
    sys.modules[module.__name__] = module
    namespace = module.__dict__
    helpers = "".join(next(c["source"] for c in nb["cells"] if c["id"] == "A0b-helpers"))
    exec(compile(helpers, "A0b-helpers-local-simulation", "exec"), namespace)
    calls = []
    def forbid(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Archive must not train, evaluate, serialize or load a model")
    for name in ("train_manual", "validate_manual", "model_bytes"):
        namespace[name] = forbid
    actual_mkdtemp = tempfile.mkdtemp
    with tempfile.TemporaryDirectory(prefix="p3b-embedded-save-test-") as tmp, patch.object(
        namespace["tempfile"], "mkdtemp", side_effect=lambda **kwargs: actual_mkdtemp(dir=tmp, **kwargs)):
        namespace["SAVE_SESSION"] = namespace["_initialize_store"](Path(tmp) / "simulated", lambda: True, "first-archive-test")
        namespace["FIRST_RESULT_ZIP"] = Path(result_path)
        namespace["input"] = lambda prompt: "ARCHIVE"
        code = "".join(next(c["source"] for c in nb["cells"] if c["id"] == "E1-archive-first-result"))
        exec(compile(code, "E1-archive-first-result-local-simulation", "exec"), namespace)
        marker = Path(namespace["SAVE_SESSION"].completed["FIRST_BASELINE"]["marker_path"])
        review.runtime.require(namespace["save_hash"](marker.parent / "p3b-baseline-results.zip") == review.RESULT_SHA and not calls,
                               "Embedded archive changed bytes or invoked model operation")
    return {"test": "exact embedded notebook E1 archives verified original ZIP without model operations",
            "status": "PASS", "scope": "LOCAL_SIMULATION_ONLY"}


def build(result_path, out):
    review.runtime.require(not out.exists(), "Choose a new delivery directory; no overwriting existing work")
    original_paths = [p for p in review.BASELINE.rglob("*") if p.is_file()]
    frozen = PROJECT / "docs/product-fix-p3b/FINAL-TRAINING-DATA-FREEZE.json"
    protected = snapshot(original_paths + [Path(result_path), frozen] + production_paths()
                         + list((HERE.parent / "colab_cpu_handoff").glob("*.*")))
    report, report_text, original, anchors = review.analyze(result_path)
    payload = review.verified_result_bytes(result_path)
    nb = build_notebook(original, anchors, json.loads(payload["data-identity.json"]))
    static = static_check(nb,original,anchors)
    tests = save_tests.run_tests(payload["metrics.json"])
    tests.append(embedded_archive_test(nb, result_path))
    review.runtime.require(snapshot([Path(p) for p in protected]) == protected, "Protected baseline/results/freeze/production changed")
    out.mkdir(parents=True)
    review.runtime.write_json(out / "p3b-colab-cpu-baseline-drive.ipynb", nb)
    (out / "FIRST-BASELINE-REVIEW.txt").write_text(report_text,encoding="utf-8")
    (out / "README-中文.txt").write_text(readme(),encoding="utf-8")
    report["local_checks"] = static
    report["save_simulations"] = tests
    report["protected_before_after"] = protected
    report["active_checkout"] = str(PROJECT)
    report["git_note"] = "Managed worktree instrumented-e03 on codex/source-support-lifecycle-instrumentation; outer index corrupt and untouched. Existing 7 modified files/untracked work preserved."
    report["AGENTS_INSTRUCTIONS"] = "NOT_FOUND after applicable parent/workspace/P3B path search"
    report["storage"] = "No baseline/result/input copies; local outputs only new notebook, compact reports, verification and hashes. No Drive operations here."
    review.runtime.write_json(out / "LOCAL-VERIFICATION.json",report)
    nb_path = out / "p3b-colab-cpu-baseline-drive.ipynb"
    handoff = "IMAGE TO CAD — P3B 首轮审查与Drive保存版交付\n\n"
    handoff += "原基线/输入/唯一结果ZIP/冻结manifest：本轮前后SHA256一致，无覆盖。\n"
    handoff += "主要错误：真实SINGLE 5/22认对，16/22判OTHER；FMR观察0/20，不证明零风险。\n"
    handoff += "保存阶段：DRIVE_INIT先小文件写读；A1预检/契约，B1模型/日志，C1指标/预测/全部固定阈值，D1最终ZIP。E1可原样归档首次结果且不训练。\n"
    handoff += "本地：结果ZIP清单/哈希/JSON/CSV重算PASS，notebook schema/语法/相同契约PASS，保存阻断/重试/哈希/作用域模拟PASS。\n"
    handoff += "未运行：本轮模型fit/CNN/Colab/Google授权/Drive挂载/真实阶段保存/独立Drive服务确认。无后台任务，无生产/DXF/OCR修改，无commit/push。\n"
    handoff += "必须由用户确认：Drive授权、小文件写读、实际阶段回读及COMPLETE标记；这不是持久化或保活保证。\n"
    handoff += f"活动目录：{PROJECT}\n结果ZIP：{Path(result_path).resolve()}\nSHA256：{review.RESULT_SHA}\n"
    handoff += f"新notebook：{nb_path}\n大小：{nb_path.stat().st_size} bytes\nSHA256：{review.runtime.sha(nb_path)}\n"
    handoff += "构建：使用项目已有Python环境执行 tools/p3b/colab_cpu_drive/build.py --results 原结果ZIP --out 尚不存在的新版本目录。构建只审查/打包，不fit或挂载。\n"
    handoff += "原历史冻结资源中绝对路径若被迁移，不重建项目或变更冻结记录；本版使用已校验原输入ZIP与当前明确定位的文件。\n"
    handoff += "依据：https://research.google.com/colaboratory/faq.html （Drive挂载访问范围、I/O与临时运行环境限制）；https://github.com/googlecolab/colabtools/blob/main/google/colab/drive.py （用户挂载接口）。\n"
    (out / "DRIVE-HANDOFF.txt").write_text(handoff,encoding="utf-8")
    # Include code in the checksum list by relative reference without duplicating it into local artifacts.
    files = sorted(p for p in out.iterdir() if p.is_file()) + sorted(p for p in HERE.glob("*.py") if p.is_file())
    (out / "checksums.sha256").write_text("".join(review.runtime.sha(p)+"  "+str(p.resolve())+"\n" for p in files),encoding="utf-8")
    print(json.dumps({"delivery":str(out),"notebook_sha256":review.runtime.sha(nb_path),"local_save_tests":len(tests),
        "MODEL_FIT":"NOT_RUN","REAL_DRIVE":"NOT_RUN","PROTECTED_FILES":"UNCHANGED"},indent=2))


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    build(args.results.resolve(),args.out.resolve())
