"""Run one frozen, local source experiment; never run OCR or write production DXF."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / 'cad_photo_to_dxf'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def array_sha(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def native_json(value):
    if isinstance(value, dict):
        return {str(key):native_json(item) for key,item in value.items()}
    if isinstance(value, (tuple,list)):
        return [native_json(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def run(inputs: Path, output: Path, independent: Path, controls: Path):
    from proposal import recover_shared_core_tracks
    from app.geometry.compound_straight_parts import chains_from_source
    sys.path.insert(0,str(independent))
    from independent_native_pen import audit_candidate_centers
    # The independently written control report, not a producer's own assertion,
    # is a required input. Its full original bytes are retained in the delivery.
    control_report = json.loads(controls.read_text())
    if not control_report.get('all_passed'):
        raise RuntimeError('Independent counterexamples have not passed; no real sweep')
    output.mkdir(parents=True, exist_ok=False)
    manifest_path = inputs / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    frozen_paths = sorted(HERE.glob('*.py')) + sorted(HERE.glob('*.json'))
    frozen_paths += sorted((REPO / 'cad_photo_to_dxf/app').rglob('*.py'))
    frozen_paths += sorted(independent.glob('*.py')) + [manifest_path, controls]
    frozen = {str(path):sha(path) for path in frozen_paths}
    environment = dict(python=sys.version,platform=platform.platform(),packages={})
    for name in ('numpy','scipy','opencv-python-headless','shapely','Pillow','ezdxf'):
        environment['packages'][name] = importlib.metadata.version(name)
    freeze = dict(schema='shared-core-real-execution-freeze-v1', source_files=frozen,
                  independent_controls_sha256=sha(controls), input_manifest_sha256=sha(manifest_path),
                  environment=environment, source_mode='PRESERVED_LOCAL_STAGE_ONLY',
                  production_entry_modified=False, full_page_conversion_executed=False)
    (output/'freeze_before.json').write_text(json.dumps(freeze,indent=2)+'\n')
    rows=[]
    started=time.time()
    for row in manifest['rows']:
        p=inputs/row['input']
        assert sha(p)==row['input_sha256']
        with np.load(p,allow_pickle=False) as archive:
            values={key:archive[key].copy() for key in archive.files}
        before={key:array_sha(value) for key,value in values.items()}
        assert all(before[key]==value['sha256'] for key,value in row['arrays'].items())
        tic=time.perf_counter()
        failure=None
        graph=None
        try:
            result=recover_shared_core_tracks(values['gray'],values['component'],values['foreign'],
                native_gray=values.get('native_gray'),native_scale=row['native_scale'],dpi=row['dpi'],
                binary=values['binary'],visible_binary=values['visible_binary'],
                protected_masks=(values['protected'],))
            parent=np.repeat(np.repeat(values['component'],row['native_scale'],0),row['native_scale'],1)
            parent &= values['native_gray']==0
            if not any(row['production_guards'].values()):
                _, adjacency, chains, covered, total=chains_from_source(parent)
                graph=dict(skeleton_nodes=len(adjacency),skeleton_edges=total,
                           explicitly_traversed_edges=covered,untraversed_cycle_edges=total-covered,
                           chain_count=len(chains),pixel_degree_three_or_more=sum(len(peers)>=3 for peers in adjacency.values()),
                           pixel_endpoints=sum(len(peers)==1 for peers in adjacency.values()),
                           role='READ_ONLY_PROPOSAL_DIAGNOSTIC_NOT_NODE_OR_OWNERSHIP_AUTHORITY',
                           junction_distance_merging=False,branch_pruning=False)
            audit=audit_candidate_centers(result,native_original=parent,
                                         scale=row['native_scale'],working_dpi=row['dpi'])
        except Exception as exc:
            # Record an exception as failure, never as an ordinary empty result.
            failure=dict(type=type(exc).__name__,message=str(exc))
            result=dict(status='EXCEPTION',candidates=[],reason='UNRESOLVED_EXCEPTION')
            audit=dict(passed=False,exception=failure)
        elapsed=time.perf_counter()-tic
        after={key:array_sha(value) for key,value in values.items()}
        unchanged=before==after
        directory=output/row['page']/row['name']
        directory.mkdir(parents=True)
        (directory/'result.json').write_text(json.dumps(native_json(result),indent=2,allow_nan=False)+'\n')
        (directory/'independent_center_audit.json').write_text(json.dumps(native_json(audit),indent=2,allow_nan=False)+'\n')
        item={key:row[key] for key in ('page','name','component_id','bbox','origin_work_px','original_cohort_index','production_guards')}
        item.update(status=result.get('status'),reason=result.get('reason'),
                    proposals=len(result.get('source_proposed_bands',[])),
                    candidates=len(result.get('candidates',[])),
                    retired_pixels=sum(part.get('native_retired_source_pixels',0) for part in result.get('candidates',[])),
                    decision_reasons=dict(Counter(value.get('reason','UNKNOWN') for value in result.get('decisions',[]))),
                    exclusive_interval_reasons=dict(Counter(interval.get('reason','UNKNOWN')
                        for band in result.get('source_proposed_bands',[]) for interval in band.get('exclusive_intervals',[]))),
                    source_graph_diagnostic=graph,
                    independent_centers_passed=audit['passed'],input_unchanged=unchanged,
                    elapsed_seconds=elapsed,exception=failure,
                    result_path=(directory/'result.json').relative_to(output).as_posix(),
                    result_sha256=sha(directory/'result.json'),audit_sha256=sha(directory/'independent_center_audit.json'))
        rows.append(item)
        print(json.dumps({key:item[key] for key in ('page','name','original_cohort_index','reason','proposals','candidates','elapsed_seconds')}) ,flush=True)
    unchanged={path:sha(path)==digest for path,digest in frozen.items()}
    pages=[]
    for page in manifest['pages']:
        subset=[row for row in rows if row['page']==page['page']]
        pages.append(dict(page=page['page'],local_parent_calls=len(subset),
                          original_scan_available=page['original_scan_available'],
                          proposals=sum(row['proposals'] for row in subset),
                          candidates=sum(row['candidates'] for row in subset),
                          retired_pixels=sum(row['retired_pixels'] for row in subset),
                          reasons=dict(Counter(row['reason'] for row in subset)),
                          preparation_filters=page['filter_rejections']))
    summary=dict(schema='shared-core-local-source-results-v1',rows=rows,pages=pages,
        original_24=[row for row in rows if row['original_cohort_index'] is not None and row['original_cohort_index']<=24],
        historical_parent=[row for row in rows if row['original_cohort_index']==25],
        proposed_bands=sum(row['proposals'] for row in rows),
        candidates=sum(row['candidates'] for row in rows),
        native_retired_source_pixels=sum(row['retired_pixels'] for row in rows),
        exceptions=[row for row in rows if row['exception']],
        all_inputs_unchanged=all(row['input_unchanged'] for row in rows),
        all_independent_centers_passed=all(row['independent_centers_passed'] for row in rows),
        frozen_sources_unchanged=all(unchanged.values()),changed_frozen_sources=[p for p,v in unchanged.items() if not v],
        elapsed_seconds=time.time()-started,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        full_page_conversion_executed=False,production_retirement_authorized=False,
        human_edit_savings='NOT_MEASURED',target_CAD='NOT_RUN',native_PDF='OUT_OF_SCOPE')
    (output/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    print(json.dumps({key:value for key,value in summary.items() if key not in ('rows','original_24','historical_parent')},indent=2))
    if summary['exceptions'] or not summary['all_inputs_unchanged'] or not summary['all_independent_centers_passed'] or not summary['frozen_sources_unchanged']:
        raise SystemExit(2)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--inputs',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--independent-tools',type=Path,required=True)
    p.add_argument('--controls',type=Path,required=True)
    args=p.parse_args()
    run(args.inputs,args.out,args.independent_tools,args.controls)
