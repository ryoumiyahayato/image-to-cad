"""Frozen structural OCR check. Never rewrites or adopts an engineering value."""
import re

UNICODE_FRACTIONS='¼½¾⅐⅑⅒⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞'

def fraction_expressed(text):
    # A malformed glyph followed immediately by a digit (e.g. ½4) is not reliable.
    return bool(re.search(r'(?<!\d)\d+\s*[/⁄]\s*\d+(?!\d)',text) or
                re.search('['+UNICODE_FRACTIONS+'](?!\\d)',text))

def risk_decision(state, ocr_text, truth_status='SOURCE_CONFIRMED'):
    expressed=fraction_expressed(ocr_text)
    if truth_status=='SOURCE_UNCERTAIN':result='ABSTAIN_SOURCE'
    elif state=='ABSTAIN':result='ABSTAIN_MODEL'
    elif state=='FRACTION_ABSENT':result='NO_FRACTION_SIGNAL'
    elif expressed:result='FRACTION_EXPRESSED_NOT_VALUE_VERIFIED'
    else:result='REVIEW_CANDIDATE_NO_AUTO_EDIT'
    return dict(risk_decision=result,review_candidate=result=='REVIEW_CANDIDATE_NO_AUTO_EDIT',
                ocr_fraction_expressed=expressed,ocr_text=ocr_text,adopted_value=None,
                automatic_numeric_correction=False,source_or_xdata_changes=False)
