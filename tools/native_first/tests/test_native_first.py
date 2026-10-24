import json
from pathlib import Path

import ezdxf
import pymupdf as fitz
import pytest
from PIL import Image

from tools.native_first import byok
from tools.native_first.import_pdf import chains, export_page, inspect_page


def drawing(tmp_path, mode='paths'):
    path = tmp_path / (mode + '.pdf')
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.draw_line((20, 20), (140, 20), width=1)
    page.draw_rect((25, 45, 100, 95), color=(0, 0, 0), fill=(0.3, 0.3, 0.3))
    if mode == 'text':
        page.insert_text((20, 130), 'Unoutlined text')
    if mode == 'curve':
        page.draw_circle((180, 100), 30)
    if mode == 'image':
        import io
        image = Image.new('RGB', (10, 10), 'black')
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        page.insert_image((150, 50, 190, 90), stream=buffer.getvalue())
    if mode == 'rotate':
        page.set_rotation(90)
    if mode == 'opacity':
        page.draw_line((20, 150), (100, 150), stroke_opacity=0.5)
    if mode == 'dash':
        page.draw_line((20, 150), (100, 150), dashes='[3 2] 0')
    if mode == 'annotation':
        page.add_text_annot((160, 150), 'Note')
    doc.save(path)
    doc.close()
    return path


def test_plain_paths_preserve_coordinates_and_provenance(tmp_path):
    source = drawing(tmp_path)
    output = tmp_path / 'native.dxf'
    report = export_page(source, output)
    doc = ezdxf.readfile(output)
    assert report['supported'] and report['saved_readback'] == 'PASS'
    assert report['model_calls'] == report['ocr_calls'] == 0
    assert report['semantic_text_recovered'] == 0
    assert not doc.modelspace().query('TEXT IMAGE')
    line = doc.modelspace().query('LINE')[0]
    assert line.dxf.start.x == pytest.approx(20 * 25.4 / 72)
    assert line.dxf.start.y == pytest.approx(180 * 25.4 / 72)
    handles = [h for row in report['paths'] for h in row['handles']]
    assert len(handles) == len(set(handles)) == len(doc.modelspace())
    assert all(doc.entitydb[h].has_xdata('NATIVE_FIRST_SOURCE') for h in handles)
    assert json.loads(output.with_suffix('.manifest.json').read_text())['source_sha256'] == report['source_sha256']
    assert not doc.audit().errors


@pytest.mark.parametrize('mode', ['text', 'curve', 'image', 'rotate', 'opacity', 'dash', 'annotation'])
def test_unsupported_page_never_silently_partially_exports(tmp_path, mode):
    source = drawing(tmp_path, mode)
    assert not inspect_page(source)['supported']
    out = tmp_path / 'blocked.dxf'
    with pytest.raises(ValueError, match='Unsupported page'):
        export_page(source, out)
    assert not out.exists()
    assert not out.with_suffix('.manifest.json').exists()


def test_preserve_existing_files(tmp_path):
    source = drawing(tmp_path)
    out = tmp_path / 'existing.dxf'
    out.write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        export_page(source, out)
    assert out.read_bytes() == b'keep'


def test_coordinate_override(tmp_path):
    source = drawing(tmp_path)
    out = tmp_path / 'override.dxf'
    report = export_page(source, out, canvas=(600, 400), units_per_pixel=0.1)
    assert report['coordinate_scale_mm_per_pt_xy'] == [0.2, 0.2]
    line = ezdxf.readfile(out).modelspace().query('LINE')[0]
    assert line.dxf.start.x == pytest.approx(4)
    assert line.dxf.start.y == pytest.approx(36)
    with pytest.raises(ValueError):
        export_page(source, tmp_path / 'bad.dxf', canvas=(600, 400))


def test_subpath_gap_not_bridged():
    record = {'items': [('l', (0, 0), (1, 0)), ('l', (2, 0), (3, 0))]}
    assert chains(record) == [[(0, 0), (1, 0)], [(2, 0), (3, 0)]]


def config(tmp_path, fmt='openai_chat', **updates):
    data = {'api_format': fmt, 'base_url': 'https://example.invalid/v1',
            'model': 'test-vision-model', 'api_key_env': 'TEST_NATIVE_KEY', 'vision': True}
    data.update(updates)
    p = tmp_path / 'provider.json'
    p.write_text(json.dumps(data))
    return p


def picture(tmp_path):
    p = tmp_path / 'image.png'
    Image.new('RGB', (50, 30), 'white').save(p)
    return p


@pytest.mark.parametrize('fmt', ['openai_chat', 'anthropic_messages'])
def test_provider_payload_only_contains_explicit_image_and_model(tmp_path, fmt):
    c = byok.config_from_file(config(tmp_path, fmt))
    endpoint, body, info = byok.make_request(c, picture(tmp_path))
    assert info['image_size'] == [50, 30]
    assert body['model'] == 'test-vision-model'
    assert 'api_key' not in json.dumps(body)
    assert endpoint.endswith('/chat/completions' if fmt == 'openai_chat' else '/messages')
    assert info['input_sha256']


@pytest.mark.parametrize('changes', [
    {'vision': False}, {'base_url': 'http://example.invalid'},
    {'base_url': 'https://secret@example.invalid'}, {'api_key': 'forbidden'},
    {'max_tokens': 0}, {'timeout_seconds': 10000}, {'model': ''}, {'api_format': 'unsupported'}])
def test_bad_config(tmp_path, changes):
    with pytest.raises(ValueError):
        byok.config_from_file(config(tmp_path, **changes))


def test_dry_run_never_calls_network(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TEST_NATIVE_KEY', 'not-a-real-key')
    monkeypatch.setattr(byok, 'call_provider', lambda *_: pytest.fail('unexpected network'))
    monkeypatch.setattr('sys.argv', ['byok', '--config', str(config(tmp_path)), '--image', str(picture(tmp_path))])
    byok.main()
    text = capsys.readouterr().out
    assert 'DRY_RUN_NO_NETWORK' in text and 'not-a-real-key' not in text


def test_execute_requires_upload_consent(tmp_path, monkeypatch):
    monkeypatch.setattr(byok, 'call_provider', lambda *_: pytest.fail('unexpected network'))
    monkeypatch.setattr('sys.argv', ['byok', '--config', str(config(tmp_path)), '--image', str(picture(tmp_path)), '--execute'])
    with pytest.raises(SystemExit):
        byok.main()


def test_fake_provider_response_stays_unverified(tmp_path, monkeypatch):
    response = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
        'regions': [{'text': '1/8"', 'bbox_px': [1, 2, 20, 25], 'uncertain': False}]})}}]}
    monkeypatch.setattr(byok, 'call_provider', lambda *_: response)
    output = tmp_path / 'proposal.json'
    monkeypatch.setattr('sys.argv', ['byok', '--config', str(config(tmp_path)), '--image', str(picture(tmp_path)),
                                   '--execute', '--allow-upload', '--output', str(output)])
    byok.main()
    record = json.loads(output.read_text())
    assert record['status'] == 'PROPOSAL_UNVERIFIED'
    assert record['proposal']['human_verified'] is False
    assert record['proposal']['automatic_apply_allowed'] is False
    assert record['proposal']['regions'][0]['text'] == '1/8"'


@pytest.mark.parametrize('response', [
    '{"regions":[{"text":"x","bbox_px":[0,0,500,5],"uncertain":false}]}',
    '{"regions":[],"execute":"code"}',
    '{"regions":[{"text":"x","bbox_px":[0,0,20,5],"uncertain":"false"}]}',
    '{"regions":[{"text":"x","bbox_px":[0,0,NaN,5],"uncertain":false}]}',
])
def test_invalid_model_output_rejected(response):
    with pytest.raises(ValueError):
        byok.validate_proposal(response, [50, 30])


def test_redirect_never_forwards_auth():
    with pytest.raises(ValueError, match='Redirect refused'):
        byok.NoRedirect().redirect_request(None, None, 307, '', {}, 'https://other.invalid')


def test_truncated_model_reply_not_accepted():
    with pytest.raises(ValueError):
        byok.extract_text({'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]}, 'openai_chat')
