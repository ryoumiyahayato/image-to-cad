"""Verbatim Goal14 parse_candidate/value functions; Goal11 literal VULGAR map."""
import re
from fractions import Fraction
ROLES = ('whole', 'numerator', 'denominator', 'relation', 'decimal_point', 'sign', 'unit', 'context')
VULGAR = {'¼': ('1', '4'), '½': ('1', '2'), '¾': ('3', '4')}

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
