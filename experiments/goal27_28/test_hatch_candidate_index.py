"""Indexed lookup is a candidate superset, never an identity or geometry rule."""
from copy import deepcopy
from dataclasses import replace
import json
import math
import random
import ezdxf
import pytest
import cad_delta as d


def make_hatch(space, x, y, *, delta=0., hole=False, curved=False, color=256):
    h = space.add_hatch(dxfattribs={"color": color})
    if curved:
        p = h.paths.add_edge_path()
        p.add_arc((x + delta, y + delta), radius=1., start_angle=0., end_angle=360.)
    else:
        vs = [(x+delta,y+delta),(x+1.+delta,y+delta),
              (x+1.+delta,y+1.+delta),(x+delta,y+1.+delta)]
        h.paths.add_polyline_path(vs, is_closed=True)
        if hole:
            h.paths.add_polyline_path([(x+.2+delta,y+.2+delta),
                                      (x+.2+delta,y+.4+delta),
                                      (x+.4+delta,y+.3+delta)], is_closed=True)
    return h


def pair(tmp_path, specs, unit=4):
    docs = []
    for suffix, changes in (("before", False),("after", True)):
        doc = ezdxf.new("R2010"); doc.units = unit
        for x,y,delta,hole,curved,color in specs:
            make_hatch(doc.modelspace(),x,y,delta=delta if changes else 0.,
                       hole=hole,curved=curved,color=color if changes else 256)
        path = tmp_path / (suffix+'.dxf'); doc.saveas(path); docs.append(d.read(path))
    return docs


def same_decisions(a,b,monkeypatch):
    indexed = d.compare(a,b)
    with monkeypatch.context() as context:
        context.setattr(d,"_hatch_cell",lambda *args: None)
        exhaustive = d.compare(a,b)
    di = indexed.pop("matching_diagnostics")
    de = exhaustive.pop("matching_diagnostics")
    assert indexed == exhaustive
    assert indexed["summary"]["confirmed_historical_identities"] == 0
    assert all(m["identity"]=="NOT_PROVEN" and not m["source_automatic_operations"]
               for m in indexed["mappings"])
    return indexed, di, de


@pytest.mark.parametrize('seed',range(16))
def test_randomized_oracle_same_correspondences(tmp_path,monkeypatch,seed):
    rng=random.Random(seed)
    specs=[(rng.uniform(-5,5),rng.uniform(-5,5),rng.choice([0.,.0003,-.0003,.0011]),
            bool(rng.randrange(2)),i%11==0,rng.choice([256,256,1])) for i in range(42)]
    specs += [(-.004,0.,.0002,False,False,256)]*3
    a,b=pair(tmp_path,specs)
    report,_,_=same_decisions(a,b,monkeypatch)
    assert report['duplicate_groups'] or report['ambiguous']


@pytest.mark.parametrize('unit',[1,4,5,6])
@pytest.mark.parametrize('side',[-1,1])
def test_negative_coordinates_and_bin_edges(tmp_path,monkeypatch,unit,side):
    scale={1:25.4,4:1.,5:10.,6:1000.}[unit]
    t=d.MM_TOLERANCE/scale
    specs=[(side*(k*4*t+eps),-side*(k*4*t+eps),sign*.999*t,False,False,256)
           for k in [-100,-1,0,1,100] for eps in [0.,t*1e-6]
           for sign in [-1,1]]
    same_decisions(*pair(tmp_path,specs,unit),monkeypatch)


@pytest.mark.parametrize('curved',[False,True])
def test_holes_and_curved_boundaries_remain_conservative(tmp_path,monkeypatch,curved):
    a,b=pair(tmp_path,[(0,0,.0001,True,curved,1),(2,2,.0001,False,False,256)])
    result,diag,_=same_decisions(a,b,monkeypatch)
    assert diag['hatch_exhaustive_queries']==int(curved)
    if not curved:
        # A missing tiny hole is not equivalent merely because extents agree.
        row=deepcopy(b.rows[0]); row['content']['boundaries'].pop()
        row['content']['loop_count']-=1
        changed=replace(b,rows=[row,*b.rows[1:]])
        result,_,_=same_decisions(a,changed,monkeypatch)
        assert a.rows[0]['handle'] in result['removed_or_unmatched']


def test_high_magnitude_coordinates_use_legacy_path(tmp_path,monkeypatch):
    a,b=pair(tmp_path,[(1e12,1e12,.0001,False,False,256)])
    _,diag,_=same_decisions(a,b,monkeypatch)
    assert diag['hatch_exhaustive_queries']==1


def test_empty_unsupported_or_invalid_anchors_fall_back():
    for bounds in [[],[[]],[[['ArcEdge',{}]]],[[['BulgedEdge',[0,0,.5],[1,1,0]]]],
                   [[['LineEdge',[float('nan'),0],[1,1]]]],
                   [[['LineEdge',[True,0],[1,1]]]]]:
        assert d._linear_hatch_anchor({'type':'HATCH','boundaries':bounds}) is None
    assert d._hatch_cell({'type':'LINE'},.004) is None


def test_unchanged_hatch_is_not_granted_historical_identity(tmp_path,monkeypatch):
    a,b=pair(tmp_path,[(0,0,0.,False,False,256),(4,0,.0001,False,False,256)])
    result,_,_=same_decisions(a,b,monkeypatch)
    assert result['summary']['content_equal']==1
    assert result['summary']['functional_equal']==1
    assert not any(m['source_automatic_operations'] for m in result['mappings'])


def test_2000_isolated_hatches_have_linear_candidate_count(tmp_path):
    specs=[(i%100*2.,i//100*2.,.0001,False,False,256) for i in range(2000)]
    result=d.compare(*pair(tmp_path,specs))
    stats=result['matching_diagnostics']
    assert result['summary']['functional_equal']==2000
    assert stats['hatch_index_queries']==2000
    assert stats['candidate_pairs_evaluated']==2000
