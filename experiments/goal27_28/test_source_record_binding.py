"""Exact file binding is independent of candidate object identity."""
import json
from pathlib import Path
from zipfile import ZipFile
import ezdxf
from PIL import Image
import pytest
import cad_delta as d


def pair(tmp_path):
    doc=ezdxf.new('R2010');doc.units=4
    doc.appids.add('SOURCE');text=doc.modelspace().add_text('before')
    text.set_xdata('SOURCE',[(1000,'original observed ink')])
    layer=doc.layers.new('SOURCE_FRAME_OUTLINE');layer.off();layer.freeze();layer.lock()
    h=doc.modelspace().add_hatch();h.paths.add_polyline_path([(0,0),(2,0),(2,2),(0,2)],is_closed=True)
    Image.new('RGBA',(2,2),(0,0,0,255)).save(tmp_path/'asset.png')
    definition=doc.add_image_def(filename='asset.png',size_in_pixel=(2,2))
    doc.modelspace().add_image(definition,insert=(10,10),size_in_units=(2,2))
    a=tmp_path/'a.dxf';b=tmp_path/'b.dxf';doc.saveas(a)
    text.dxf.text='user edit';text.discard_xdata('SOURCE');layer.on()
    doc.saveas(b)
    return a,b


def test_binding_exact_files_and_images(tmp_path):
    a,b=pair(tmp_path)
    record=d.source_record(d.read(a),d.read(b))
    result=d.validate_source_record_binding(record,b,baseline_path=a)
    assert result=={'files_match':True,'historical_identity':'NOT_PROVEN','source_automatic_operations':False}
    assert record['file_binding']['saved_sha256']!=record['file_binding']['baseline_sha256']
    assert not record['source_trace']['saved']['modelspace']
    assert len(record['source_trace']['baseline']['modelspace'])==1


@pytest.mark.parametrize('target',['saved','baseline','image'])
def test_wrong_pair_never_validates(tmp_path,target):
    a,b=pair(tmp_path);record=d.source_record(d.read(a),d.read(b))
    p={'saved':b,'baseline':a,'image':tmp_path/'asset.png'}[target]
    p.write_bytes(p.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='MISMATCH'):
        d.validate_source_record_binding(record,b,baseline_path=a)


def test_unchanged_visual_content_new_file_is_stale(tmp_path):
    a,b=pair(tmp_path);record=d.source_record(d.read(a),d.read(b))
    # A new save, even without edits, must be explicitly bound again.
    b.write_bytes(b.read_bytes()+b'\n')
    with pytest.raises(ValueError,match='SAVED_FILE_MISMATCH'):
        d.validate_source_record_binding(record,b)


def test_old_unbound_sidecar_is_not_silently_trusted(tmp_path):
    a,b=pair(tmp_path)
    with pytest.raises(ValueError,match='BINDING_MISSING'):
        d.validate_source_record_binding({'source_trace':{}},b)


def test_snapshot_change_after_read_blocks_record(tmp_path):
    a,b=pair(tmp_path);sa,sb=d.read(a),d.read(b)
    a.write_bytes(a.read_bytes()+b'\n')
    with pytest.raises(ValueError,match='INPUT_CHANGED'):
        d.source_record(sa,sb)


def test_change_during_read_detected(tmp_path,monkeypatch):
    a,_=pair(tmp_path);original=d.ezdxf.readfile
    def changing(path):
        doc=original(path);p=Path(path);p.write_bytes(p.read_bytes()+b'\n');return doc
    monkeypatch.setattr(d.ezdxf,'readfile',changing)
    with pytest.raises(ValueError,match='CHANGED_DURING_READ'):
        d.read(a)


def test_portable_record_binds_delivered_copy_and_keeps_user_edit(tmp_path):
    a,b=pair(tmp_path);original_a=a.read_bytes();original_b=b.read_bytes()
    manifest=d.package_delivery(a,b,tmp_path/'delivery.zip',restore_layer_states=True)
    out=tmp_path/'moved'
    with ZipFile(tmp_path/'delivery.zip') as z:z.extractall(out)
    target=out/manifest['dxf'];record=json.loads((out/manifest['source_record']).read_text())
    assert d.validate_source_record_binding(record,target,baseline_path=a)['files_match']
    doc=ezdxf.readfile(target)
    assert [e.dxf.text for e in doc.modelspace().query('TEXT')]==['user edit']
    assert doc.layers.get('SOURCE_FRAME_OUTLINE').is_off()
    assert not any(e.xdata for e in doc.modelspace())
    assert a.read_bytes()==original_a and b.read_bytes()==original_b
    assert not record['source_trace']['source_automatic_operations']
