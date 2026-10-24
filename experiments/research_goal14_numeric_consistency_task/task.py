"""Bounded annotation task and scorer support. This module is NOT a vision model."""
import ast
import functools
import json
import re
from fractions import Fraction
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'local-artifacts/research-goal14-numeric-consistency-task-20261023'
ROLES = ('whole', 'numerator', 'denominator', 'relation', 'decimal_point', 'sign', 'unit', 'context')
STATES = ('CONSISTENT', 'CONTRADICTION', 'INSUFFICIENT', 'NOT_APPLICABLE')

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def reused_primitives():
    """Reuse only the two pure P21-C render helpers, without importing its torch common."""
    path = ROOT / 'experiments/ml_pilot/p21c_fraction_guard/generate.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('font', 'text_image')]
    assert len(nodes) == 2
    ns = {'functools': functools, 'Image': Image, 'ImageDraw': ImageDraw}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), ns)
    return ns['font'], ns['text_image']

def vulgar_mapping():
    # Reuse Goal11's literal fraction map only; no model or inference module imported.
    path = ROOT / 'experiments/research_goal11_formula_model/parse_formula.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VULGAR' for t in n.targets))
    return ast.literal_eval(node.value)

VULGAR = vulgar_mapping()

def parts(spec):
    return dict(whole=spec.get('whole'), numerator=spec.get('numerator'),
                denominator=spec.get('denominator'), relation=spec['kind'],
                decimal_point='.' if spec['kind'] == 'decimal' else None,
                sign=spec.get('sign'), unit=spec.get('unit'), context=spec.get('context'))

def value(p):
    try:
        k = p['relation']; sign = -1 if p['sign'] == '-' else 1
        if k in ('integer', 'decimal'): v = Fraction(p['whole'])
        elif k == 'fraction': v = Fraction(int(p['numerator']), int(p['denominator']))
        elif k == 'mixed': v = int(p['whole']) + Fraction(int(p['numerator']), int(p['denominator']))
        else: return None
        return str(v * sign)
    except (ValueError, TypeError, ZeroDivisionError):
        return None

def parse_candidate(raw):
    """Exact bounded candidate grammar. No correction, joining digits, or answer selection."""
    s = raw.strip(); context = None
    if s.startswith('exceeding '): context = 'exceeding'; s = s[len('exceeding '):]
    for suffix in ('DIA. HOLE', '(typ.)'):
        if s.endswith(suffix): context = suffix; s = s[:-len(suffix)].rstrip(); break
    unit = None
    for suffix, name in [('inch.', 'inch'), ('inch', 'inch'), ('mm', 'mm'), ('"', 'inch'), ('″', 'inch'), ('”', 'inch')]:
        if s.endswith(suffix): unit = name; s = s[:-len(suffix)].rstrip(); break
    sign = None
    if s[:1] in ('+', '-'): sign, s = s[0], s[1:]
    p = {r: None for r in ROLES}; p.update(sign=sign, unit=unit, context=context)
    m = re.fullmatch(r'(\d+) +(\d+)/(\d+)', s)
    if m: p.update(whole=m[1], numerator=m[2], denominator=m[3], relation='mixed')
    elif re.fullmatch(r'\d*/?[^\x00-\x7f]', s) and s[-1:] in VULGAR:
        a, b = VULGAR[s[-1]]; w = s[:-1]
        if w and not w.isdecimal(): return {'raw': raw, 'parts': p, 'supported': False, 'numeric_value': None}
        p.update(whole=w or None, numerator=a, denominator=b, relation='mixed' if w else 'fraction')
    elif (m := re.fullmatch(r'(\d+)/(\d+)', s)): p.update(numerator=m[1], denominator=m[2], relation='fraction')
    elif re.fullmatch(r'\d+\.\d+', s): p.update(whole=s, decimal_point='.', relation='decimal')
    elif re.fullmatch(r'\d+', s): p.update(whole=s, relation='integer')
    supported = p['relation'] is not None and value(p) is not None
    return {'raw': raw, 'parts': p, 'supported': supported, 'numeric_value': value(p)}

def aggregate(statuses, supported=True):
    vals = list(statuses.values())
    return dict(overall='CONTRADICTION' if 'CONTRADICTION' in vals else
                'INSUFFICIENT' if 'INSUFFICIENT' in vals or not supported else 'CONSISTENT',
                has_contradiction='CONTRADICTION' in vals,
                has_insufficient='INSUFFICIENT' in vals or not supported,
                full_expression_match=supported and all(v in ('CONSISTENT', 'NOT_APPLICABLE') for v in vals))

def label(source_parts, candidate, unknown=(), scope='NUMBER_UNIT_CONTEXT'):
    """Annotation comparison supplied with visible-source labels. Never reads pixels."""
    parsed = parse_candidate(candidate); statuses = {}; reasons = {}
    source_supported = source_parts['relation'] in ('integer','decimal','fraction','mixed') and value(source_parts) is not None
    for role in ROLES:
        a, b = source_parts[role], parsed['parts'][role]
        if role == 'context' and scope == 'NUMBER_UNIT':
            statuses[role] = 'NOT_APPLICABLE'; reasons[role] = 'outside_declared_scope'
        elif role in unknown:
            statuses[role] = 'INSUFFICIENT'; reasons[role] = 'not_resolvable_from_final_visible_input'
        elif (not parsed['supported'] or not source_supported) and role not in ('unit', 'context'):
            statuses[role] = 'INSUFFICIENT'; reasons[role] = 'unsupported_candidate_syntax'
        elif a == b:
            statuses[role] = 'NOT_APPLICABLE' if a is None else 'CONSISTENT'; reasons[role] = 'visible_agreement_or_confirmed_absence'
        else:
            statuses[role] = 'CONTRADICTION'; reasons[role] = 'visible_disagreement'
    numeric_unknown = set(unknown).intersection(ROLES[:6])
    return dict(**aggregate(statuses, parsed['supported'] and source_supported), parts=statuses, reasons=reasons,
                scope_status='UNSUPPORTED_SOURCE' if not source_supported else 'SUPPORTED' if parsed['supported'] else 'UNSUPPORTED_CANDIDATE',
                numeric_equivalent=None if numeric_unknown or not parsed['supported'] or not source_supported else value(source_parts) == parsed['numeric_value'])

def model_input(row):
    # Paths identify bytes for the loader. Only decoded pixels, candidate_raw, scope reach the model.
    return {k: row[k] for k in ('image', 'candidate_raw', 'scope')}

def load_model_input(row, base):
    """Future model adapter allowlist. Returns pixels, not the filename or provenance."""
    x=model_input(row)
    with Image.open(Path(base)/x['image']) as image:
        return {'pixels':image.convert('L').copy(),'candidate_raw':x['candidate_raw'],'scope':x['scope']}

PAIR_SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object',
    'required': ['pair_id','image','candidate_raw','scope','provenance','annotation'],
    'additionalProperties': False,
    'properties': {
        'pair_id': {'type':'string'}, 'image': {'type':'string'}, 'candidate_raw': {'type':'string'},
        'scope': {'enum':['NUMBER_UNIT','NUMBER_UNIT_CONTEXT']},
        'provenance': {'type':'object','required':['source_object','input_role','group','assessment','human_reviewed']},
        'annotation': {'type':'object','required':['overall','parts','has_contradiction','has_insufficient','full_expression_match','scope_status'],
            'properties': {'overall': {'enum':list(STATES[:3])}, 'parts': {'type':'object','required':list(ROLES),'additionalProperties':False,
                'properties': {r:{'enum':list(STATES)} for r in ROLES}},
                'has_contradiction':{'type':'boolean'},'has_insufficient':{'type':'boolean'},'full_expression_match':{'type':'boolean'},
                'scope_status':{'enum':['SUPPORTED','UNSUPPORTED_CANDIDATE','UNSUPPORTED_SOURCE']}}}
    }
}

if __name__ == '__main__':
    write(OUT / 'pair.schema.json', PAIR_SCHEMA)
    print(json.dumps(parse_candidate('1 3/16" DIA. HOLE'), ensure_ascii=False))
