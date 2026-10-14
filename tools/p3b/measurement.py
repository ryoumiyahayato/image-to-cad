"""One final-target measurement path for future train/validation nominations."""

import copy
import ast
import inspect as python_inspect
import math
import sys

import numpy as np

from common import ROOT

VERSION = "final-target-profile-v2-canonical"


class MissingSourceWindow(ValueError):
    pass


class SourceWindow:
    """Read-through source window, with the real page shape and coordinates.

    Unknown pixels raise an error. No full-page array, padding or fabricated
    source pixels are created. This lets saved grey crops reuse exactly the
    original page sampling span without rendering the PDF again.
    """
    def __init__(self, pixels, origin, page_size_px):
        self.pixels = pixels
        self.origin = origin
        self.shape = (page_size_px[1], page_size_px[0])

    def __getitem__(self, key):
        ys, xs = key
        xx, yy = np.asarray(xs)-self.origin[0], np.asarray(ys)-self.origin[1]
        if (np.any(xx<0) or np.any(yy<0) or np.any(xx>=self.pixels.shape[1])
                or np.any(yy>=self.pixels.shape[0])):
            raise MissingSourceWindow("sampling probe requires source pixels outside saved grey crop")
        return self.pixels[yy, xx]



def traced_profile(gray,line,profile_function):
    """Capture actual intermediate branches of the existing profile routine."""
    traced_function=getattr(profile_function,'func',profile_function)
    source,start=python_inspect.getsourcelines(traced_function)
    reasons={}
    for node in ast.walk(ast.parse(''.join(source))):
        if isinstance(node,ast.If):
            for child in node.body:
                if isinstance(child,ast.Continue):
                    reasons[start+child.lineno-1]=ast.unparse(node.test)
    failures=[];final={}
    def trace(frame,event,value):
        if frame.f_code!=traced_function.__code__:return None
        loc=frame.f_locals
        if event=='line' and frame.f_lineno in reasons:
            item={'fraction':float(loc['t']),'branch':reasons[frame.f_lineno]}
            if 'seed' in loc:item['seed_offset_in_algorithm_pixels']=int(loc['seed']-loc['span'])
            failures.append(item)
        if event=='return':
            final.update(valid_probes=len(loc.get('widths',[])),widths_in_algorithm_pixels=list(loc.get('widths',[])),
                         stable_fraction=loc.get('stable'),normal_span_in_algorithm_pixels=loc.get('span'),
                         algorithm_pixel_scale=loc.get('pixel_scale',1))
        return trace
    previous=sys.gettrace();sys.settrace(trace)
    try:profile=profile_function(gray,line)
    finally:sys.settrace(previous)
    from collections import Counter
    final['failed_probe_branches']=dict(Counter(p['branch'] for p in failures))
    final['failed_probes']=failures
    final['result_reason']=('measured' if profile else 'target_length_below_8_reference_px' if line.length<8*final.get('algorithm_pixel_scale',1) else
                            'valid_probes_below_12' if final['valid_probes']<12 else 'stable_fraction_below_0.75')
    return profile,final


def stroke_profile_scaled(gray,line,*,pixel_scale,reference_shape):
    """Offline unit adapter for the existing connected-dark-run algorithm.

    Same 19 probes, thresholds, splitting and stability rule. Unlike a sparse
    resized grid, normal samples stay one actual source pixel apart. Only
    length quantities gain an explicit reference-to-source conversion.
    """
    dx,dy=line.x2-line.x1,line.y2-line.y1
    length=math.hypot(dx,dy)
    if length<8*pixel_scale:return None
    normal=np.array([-dy,dx])/length
    reference_span=max(12,min(48,int(min(reference_shape)*.008)))
    span=math.ceil(reference_span*pixel_scale)
    max_seed_offset=2*pixel_scale
    offsets=np.arange(-span,span+1)
    widths,dark,centers,contrasted=[],[],[],[]
    for t in np.linspace(.12,.88,19):
        point=np.array([line.x1+dx*t,line.y1+dy*t])
        samples=point+offsets[:,None]*normal
        xs,ys=np.rint(samples[:,0]).astype(int),np.rint(samples[:,1]).astype(int)
        if xs.min()<0 or ys.min()<0 or xs.max()>=gray.shape[1] or ys.max()>=gray.shape[0]:
            continue
        values=gray[ys,xs]
        candidates=np.where(values<128)[0]
        if not len(candidates):
            continue
        seed=int(candidates[np.argmin(abs(candidates-span))])
        if abs(seed-span)>max_seed_offset:
            continue
        a=b=seed
        while a>0 and values[a-1]<128:a-=1
        while b+1<len(values) and values[b+1]<128:b+=1
        if a==0 or b==len(values)-1:
            continue
        run=values[a:b+1];band=max(1,len(run)//3)
        middle=float(np.median(run[band:len(run)-band])) if len(run)>=3 else 0.
        flanks=max(float(run[:band].min()),float(run[-band:].min()))
        split_fill=len(run)>=3 and middle-flanks>8
        if split_fill:
            level=(middle+flanks)/2
            candidates=np.where(values<=level)[0]
            seed=int(candidates[np.argmin(abs(candidates-span))])
            if abs(seed-span)>max_seed_offset:
                continue
            a=b=seed
            while a>0 and values[a-1]<=level:a-=1
            while b+1<len(values) and values[b+1]<=level:b+=1
            if a==0 or b==len(values)-1:
                continue
        widths.append(b-a+1);centers.append((a+b)/2-span)
        dark.append(float(np.mean(values[a:b+1]<64)));contrasted.append(bool(split_fill))
    if len(widths)<12:return None
    median=float(np.median(widths))
    stable=float(np.mean(abs(np.asarray(widths)-median)<=max(pixel_scale,median*.25)))
    if stable<.75:return None
    return {'source_width_px':median,'stable_fraction':stable,'dark_core_fraction':float(np.median(dark)),
            'center_offset_px':float(np.median(centers)),'samples':len(widths),
            'contrast_separated_fraction':float(np.mean(contrasted))}


def canonical_geometry(geometry):
    members = []
    for gid, line, origin in geometry:
        a, b = tuple(line[:2]), tuple(line[2:])
        if b<a:
            a,b=b,a
        members.append((gid,list(a+b),origin))
    return sorted(members,key=lambda g:(tuple(g[1]),g[0]))


def measure_row(row, gray):
    """Measure after trimming, in source coordinates, without inherited cache values."""
    package = str(ROOT / "cad_photo_to_dxf")
    if package not in sys.path:
        sys.path.insert(0, package)
    from app.geometry.line_detect import LineSegment
    from app.geometry.source_presentation import stroke_profile, lineweight_record

    measurements = []
    display = {g[0]: "AB"[i] for i,g in enumerate(row.get("candidate_geometry", []))}
    for gid, line, _ in canonical_geometry(row.get("candidate_geometry", [])):
        length = math.hypot(line[2] - line[0], line[3] - line[1])
        measured_source=gray;measured_line=LineSegment(*line);factor=1.;trace_values=None;reference_profile=None;profile_function=stroke_profile
        reference=row.get('measurement_reference_frame')
        if reference:
            from trial_sampling import pixel_center_to_pdf,pdf_to_pixel_center
            mapped=sum([pdf_to_pixel_center(pixel_center_to_pdf(line[k:k+2],row['coordinate_frame']),reference) for k in (0,2)],[])
            reference_line=LineSegment(*mapped)
            matrix=np.linalg.solve(np.column_stack((row['coordinate_frame']['pdf_x_per_pixel'],row['coordinate_frame']['pdf_y_per_pixel'])),
                                   np.column_stack((reference['pdf_x_per_pixel'],reference['pdf_y_per_pixel'])))
            dx,dy=reference_line.x2-reference_line.x1,reference_line.y2-reference_line.y1
            factor=float(np.linalg.norm(matrix@(np.array([-dy,dx])/max(reference_line.length,1e-9))))
            # Bind parameters through defaults so the diagnostic tracer still
            # observes the actual algorithm function, not a wrapper's locals.
            import functools
            profile_function=functools.partial(stroke_profile_scaled,pixel_scale=factor,reference_shape=tuple(reversed(reference['render_size_px'])))
        try:
            if row.get('diagnostic_profile_trace'):
                profile,trace_values=traced_profile(measured_source,measured_line,profile_function)
            else:profile=profile_function(measured_source,measured_line)
            if profile and reference:
                reference_profile={**profile,'source_width_px':profile['source_width_px']/factor,'center_offset_px':profile['center_offset_px']/factor}
            status = "measured" if profile else "attempted_no_valid_profile"
            reason = None if profile else (
                "target_length_below_8_reference_px" if reference and length < 8*factor else
                "target_length_below_8px" if length < 8 else
                "no_stable_supported_profile: fewer_than_12_valid_probes_or_stability_below_0.75"
            )
        except (MissingSourceWindow, IndexError, ValueError) as error:
            profile,status,reason=None,"read_or_coordinate_error",str(error)
        measurements.append({
            "geometry_id": gid,
            "display_member": display[gid],
            "source_line_px": list(line),
            "profile": profile,
            "lineweight": lineweight_record(profile, row.get("source_dpi"))
            if profile and row.get("source_dpi") else None,
            "profile_status": status,
            "missing_reason": reason,
            "intermediate_profile_trace":trace_values,
            "reference_grid_profile":reference_profile if reference else None,
            "actual_source_pixels_per_algorithm_pixel":factor,
        })
    row["current_p3a_measurement"] = measurements
    row["measurement_rule"] = VERSION
    row["measurement_status"] = (
        "measured" if any(m["profile"] for m in measurements) else
        "read_or_coordinate_error" if any(m["profile_status"]=="read_or_coordinate_error" for m in measurements)
        else "attempted_no_valid_profile" if measurements else "not_applicable"
    )
    row["measurement_missing_reason"] = (
        "target_has_no_line_geometry" if not measurements else None
    )
    row["profile_member_rule"] = "canonical endpoint direction and geometric member order, then first valid profile; no averaging or new features"
    row["feature_profile_geometry_id"] = next((m["geometry_id"] for m in measurements if m["profile"]),None)
    row["sampling_conditions"] = {"source_shape_px":list(gray.shape),
                                  "normal_span_px":math.ceil(max(12,min(48,int(min(reference['render_size_px'])*.008)))*factor) if row.get('measurement_reference_frame') and measurements else max(12,min(48,int(min(gray.shape)*.008))),
                                  "normal_span_unit":"actual source pixels, explicit reference length converted" if row.get('measurement_reference_frame') else "actual source pixels",
                                  "normal_step_source_px":1,
                                  "max_seed_offset_source_px":2*factor if row.get('measurement_reference_frame') and measurements else 2,
                                  "reference_grid_dpi":row.get('measurement_reference_frame',{}).get('effective_dpi'),
                                  "source_sampling":"native 1px normal steps; reference lengths converted, no resampling or source replacement" if row.get('measurement_reference_frame') else "native integer pixels",
                                  "probe_count":19,"fractional_extent":[.12,.88]}
    if row.get('measurement_reference_frame'):row['measurement_rule']=VERSION+'+explicit-reference-lengths-native-probes-v1'
    return row


def measure_trial_targets(rows, windows):
    """Both offline trial entries use the same actual final targets/windows."""
    result=[]
    for original in rows:
        row=copy.deepcopy(original)
        pixels,origin,size=windows[row["sample_id"]]
        measure_row(row,SourceWindow(pixels,origin,size))
        result.append(row)
    return result
