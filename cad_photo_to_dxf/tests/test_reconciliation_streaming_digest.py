"""Digest identity, error behavior and bounded encoding, not a quality score."""
import hashlib
import json
import random
import pytest
from app.geometry.source_stroke_reconciliation import _digest_payload
from app.geometry.source_stroke_reconciliation import (
    _digest_without_gap_extent,
    _payload_without_gap_extent,
    GAP_EXTENT_MEASUREMENT_SLOT,
)


def reference(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()


def examples():
    out=[None,True,False,0,-0.0,1e-300,1e300,[],{},'文字\\\n\r\t\ud800',
         {'b':None,'a':(1,2.5,'签章')},{2:'b',1:'a'},{False:1,True:2},
         [[{'a':i,'b':[str(i),None]} for i in range(10)]]]
    rng=random.Random(17)
    for i in range(150):
        out.append({'idx':i,'float':rng.uniform(-1e8,1e8),
                    'points':[[rng.random(),rng.randint(-99,99)] for _ in range(i%10)]})
    return out


@pytest.mark.parametrize('value',examples())
def test_identical_canonical_sha256(value):
    assert _digest_payload(value)==reference(value)


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-float('inf'),{'nested':[float('nan')]},set([1,2]),object()])
def test_same_invalid_input_rejection(value):
    try:
        reference(value)
    except Exception as error:
        expected=type(error)
    else:
        raise AssertionError('invalid reference fixture')
    with pytest.raises(expected):
        _digest_payload(value)


def test_circular_reference_rejected():
    value=[]
    value.append(value)
    for function in (reference,_digest_payload):
        with pytest.raises(ValueError):
            function(value)


def test_no_one_shot_serialization(monkeypatch):
    value={'evidence':[{'x':i,'role':'来源'} for i in range(500)]}
    expected=reference(value)
    def forbidden(*args,**kwargs):raise AssertionError('Whole payload serialization is forbidden in digest')
    monkeypatch.setattr(json,'dumps',forbidden)
    assert _digest_payload(value)==expected



@pytest.mark.parametrize('count',[0,1,9,125,1000])
def test_projected_base_digest_identical_without_mutating_evidence(count):
    payload={
        'representations':[{'id':i,'geometry':(i+.125, i/7),'source':'签'} for i in range(count)],
        'evidence':[
            {'artifact':'kept', 'measurements':{GAP_EXTENT_MEASUREMENT_SLOT:{'keep':True}}},
            {'artifact':'runtime-route-ledger-snapshot','measurements':{
                GAP_EXTENT_MEASUREMENT_SLOT:{'large':['unchanged']*25},'keep':{'value':list(range(count))}}},
            {'artifact':'runtime-route-ledger-snapshot','measurements':None},
        ],
    }
    before=json.dumps(payload,sort_keys=True)
    assert _digest_without_gap_extent(payload)==reference(_payload_without_gap_extent(payload))
    assert json.dumps(payload,sort_keys=True)==before
    assert GAP_EXTENT_MEASUREMENT_SLOT in payload['evidence'][1]['measurements']


def test_projection_does_not_roundtrip_entire_ledger(monkeypatch):
    payload={'evidence':[{'artifact':'runtime-route-ledger-snapshot','measurements':{
        GAP_EXTENT_MEASUREMENT_SLOT:{'x':1},'other':['a','b']}}], 'complete':['keep']*1000}
    expected=reference(_payload_without_gap_extent(payload))
    def forbidden(*args,**kwargs):raise AssertionError('Do not serialize a second complete ledger')
    monkeypatch.setattr(json,'dumps',forbidden)
    monkeypatch.setattr(json,'loads',forbidden)
    assert _digest_without_gap_extent(payload)==expected


def test_projection_keeps_invalid_value_rejection():
    payload={'evidence':[], 'invalid':float('inf')}
    with pytest.raises(ValueError):
        _digest_without_gap_extent(payload)

@pytest.mark.parametrize("value", [float("inf"), float("nan"), {"a":set([1])}])
def test_invalid_excluded_extension_is_still_rejected(value):
    payload={"evidence":[{"artifact":"runtime-route-ledger-snapshot","measurements":{GAP_EXTENT_MEASUREMENT_SLOT:value}}]}
    with pytest.raises((ValueError,TypeError)):
        _payload_without_gap_extent(payload)
    with pytest.raises((ValueError,TypeError)):
        _digest_without_gap_extent(payload)
