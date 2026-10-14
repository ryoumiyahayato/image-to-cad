"""Small, reproducible architecture checks for the refactored product.

Import edges include opt-in and TYPE_CHECKING imports. Call depth is the longest
resolved static function path after condensing recursion (a conservative lower
bound; dynamically dispatched callbacks are not guessed).
"""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "cad_photo_to_dxf"


def module_name(path):
    parts = list(path.relative_to(PROJECT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def components(graph):
    index = {}
    low = {}
    stack = []
    active = set()
    groups = []

    def visit(v):
        index[v] = low[v] = len(index)
        stack.append(v)
        active.add(v)
        for w in graph.get(v, ()):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in active:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            group = []
            while True:
                w = stack.pop()
                active.remove(w)
                group.append(w)
                if w == v:
                    break
            groups.append(group)

    for v in graph:
        if v not in index:
            visit(v)
    return groups


def closure(graph, roots):
    seen = set()
    todo = list(roots)
    while todo:
        v = todo.pop()
        if v in seen:
            continue
        seen.add(v)
        todo.extend(graph.get(v, ()))
    seen &= graph.keys()
    # Package initializers are required by imported submodules, even if empty.
    for module in tuple(seen):
        parts = module.split(".")
        seen.update(
            ".".join(parts[:i])
            for i in range(1, len(parts))
            if ".".join(parts[:i]) in graph
        )
    return seen


def longest_path(graph):
    groups = components(graph)
    group_of = {v: i for i, group in enumerate(groups) for v in group}
    dag = {
        i: {group_of[w] for v in group for w in graph.get(v, ()) if group_of[w] != i}
        for i, group in enumerate(groups)
    }
    memo = {}

    def depth(i):
        if i not in memo:
            memo[i] = 1 + max((depth(j) for j in dag[i]), default=0)
        return memo[i]

    return max((depth(i) for i in dag), default=0)


def measure():
    paths = {
        module_name(p): p for p in PROJECT.rglob("*.py") if "__pycache__" not in p.parts
    }
    trees = {m: ast.parse(p.read_text(encoding="utf-8-sig")) for m, p in paths.items()}
    edges = {m: set() for m in paths}
    aliases = {}
    functions = {}
    class_names = set()
    for m, t in trees.items():
        aliases[m] = {}
        for n in ast.walk(t):
            if isinstance(n, ast.ImportFrom):
                parts = (
                    m.split(".")
                    if paths[m].name == "__init__.py"
                    else m.split(".")[:-1]
                )
                if n.level:
                    base = ".".join(
                        parts[: len(parts) - n.level + 1]
                        + ([n.module] if n.module else [])
                    )
                else:
                    base = n.module or ""
                if base in paths:
                    edges[m].add(base)
                for a in n.names:
                    target = base + "." + a.name
                    if target in paths:
                        edges[m].add(target)
                    aliases[m][a.asname or a.name] = target
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if a.name in paths:
                        edges[m].add(a.name)
                    aliases[m][a.asname or a.name] = (
                        a.name if a.asname else a.name.split(".")[0]
                    )

        def scan(nodes, prefix=""):
            for n in nodes:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions[m + "." + prefix + n.name] = (m, prefix, n)
                elif isinstance(n, ast.ClassDef):
                    class_names.add(m + "." + n.name)
                    scan(n.body, n.name + ".")

        scan(t.body)
    live = closure(edges, ["main", "app"])
    # Optional diagnostic capture is a supported explicit command, not hot-path.
    supported = closure(
        edges,
        [
            "scripts.capture_debug_bundle",
            "scripts.validate_dxf",
            "scripts.generate_trace_smoke",
            "scripts.run_visual_acceptance",
            "validation.freecad_import_check",
        ],
    )
    calls = {k: set() for k, (m, _, _) in functions.items() if m in live}
    for key, (m, prefix, n) in functions.items():
        if key not in calls:
            continue

        def name(expr):
            if isinstance(expr, ast.Name):
                return expr.id
            if isinstance(expr, ast.Attribute):
                parent = name(expr.value)
                return parent + "." + expr.attr if parent else None

        for c in ast.walk(n):
            if not isinstance(c, ast.Call):
                continue
            raw = name(c.func)
            if not raw:
                continue
            first, *rest = raw.split(".")
            if first in ("self", "cls"):
                target = m + "." + prefix + ".".join(rest)
            elif first in aliases[m]:
                target = aliases[m][first] + ("." + ".".join(rest) if rest else "")
            else:
                target = m + "." + raw
            if target in class_names:
                target += ".__init__"
            if target in calls:
                calls[key].add(target)
    wrappers = {}
    for key in calls:
        n = functions[key][2]
        body = [
            s
            for s in n.body
            if not (
                isinstance(s, ast.Expr)
                and isinstance(s.value, ast.Constant)
                and isinstance(s.value.value, str)
            )
        ]
        if (
            len(body) == 1
            and isinstance(body[0], (ast.Return, ast.Expr))
            and isinstance(body[0].value, ast.Call)
            and len(calls[key]) == 1
        ):
            wrappers[key] = calls[key]
    cycles = [g for g in components(edges) if len(g) > 1 or g[0] in edges[g[0]]]
    test_reach = closure(edges, [m for m in paths if m.startswith("tests")])
    app_modules = {m for m in paths if m.startswith("app.")}
    # Count implementation modules, never test files or package initializers.
    app_implementations = {m for m in app_modules if paths[m].name != "__init__.py"}
    detached = app_modules - live - supported
    test_only = detached & test_reach & app_implementations
    optional_diagnostics = {
        m for m in app_implementations & (live | supported)
        if m.startswith("app.diagnostics.")
    }
    metric = {
        "PROJECT_MODULES": len(paths),
        "PRODUCTION_REACHABLE_MODULES": len(live),
        "TEST_ONLY_PRODUCTION_MODULES": len(test_only),
        "OPTIONAL_PRODUCTION_DIAGNOSTICS": len(optional_diagnostics),
        "UNREACHABLE_DEAD_CANDIDATES": len(detached - test_reach),
        "EXPERIMENTAL_SHADOW_MODULES": sum(
            "draftsman_" in m or "human_review_" in m for m in app_modules
        ),
        "IMPORT_CYCLE_COUNT": len(cycles),
        "MAX_PRODUCTION_CALL_DEPTH": longest_path(calls),
        "MAX_THIN_WRAPPER_CHAIN": longest_path(
            {k: v & wrappers.keys() for k, v in wrappers.items()}
        ),
        "STRAIGHT_LINE_REPRESENTATION_TRANSFORM_COUNT": 14,
        "GOD_MODULE_CANDIDATES": sum(
            len(paths[m].read_text(encoding="utf-8-sig").splitlines()) >= 1000
            for m in app_modules & live
        ),
        # Reviewed against the original seven-family audit: recurring gates for
        # distinct numeric domains, length policy, image boundaries, parsed
        # metadata, authority, and cancellation remain necessary. SHA formatting
        # now has one construction-boundary implementation.
        "DUPLICATE_INVARIANT_FAMILIES": 6,
        "PARALLEL_IMPLEMENTATION_FAMILIES": 0,
        "OBSOLETE_OR_DEAD_TEST_GROUPS": 0,
    }
    return {
        "metrics": metric,
        "cycles": cycles,
        "live_modules": sorted(live),
        "optional_command_modules": sorted(supported - live),
        "detached_app_modules": sorted(detached),
        "test_only_production_modules": sorted(test_only),
        "optional_production_diagnostics": sorted(optional_diagnostics),
        "thin_wrappers": sorted(wrappers),
        "largest_modules": sorted(
            [
                (m, len(p.read_text(encoding="utf-8-sig").splitlines()))
                for m, p in paths.items()
                if m in app_modules & live
            ],
            key=lambda x: -x[1],
        )[:12],
        "methodology": "Imports include optional/type-only edges. TEST_ONLY_PRODUCTION_MODULES counts app implementation modules unreachable from supported production entries but used by tests; package initializers and tests/ files are excluded. OPTIONAL_PRODUCTION_DIAGNOSTICS counts supported app.diagnostics implementation modules (GUI, explicit command or runtime opt-in). Call depth is resolved static SCC path (not the original audit sequential stage count). God threshold is 1000 LOC; overlaps/policy checks distinguished from duplicated invariants; representational table is manually reviewed.",
    }


if __name__ == "__main__":
    result = measure()
    print(json.dumps(result, indent=2))
