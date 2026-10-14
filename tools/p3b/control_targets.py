"""Finite CONTROL ink-extent evidence; no OCR, class or object reconstruction."""

import cv2
import numpy as np


class ControlContext:
    """Reuse the existing threshold/8-connected components and native LSD lines.

    All distances are input-raster pixels. Isolation at this threshold supports
    a separable ink candidate, never an exclusive glyph or engineering meaning.
    """

    def __init__(self, gray, lines):
        self.gray = gray
        _, self.labels, self.stats, self.centers = cv2.connectedComponentsWithStats(
            (gray < 160).astype(np.uint8), 8)
        self.lines = [(g[0], np.asarray(g[1], float).reshape(2, 2)) for g in lines]

    @classmethod
    def from_saved_rows(cls, gray, rows):
        """Recover recorded parent LSD segments; no new line detection."""
        parents={}
        for row in rows:
            w,h=row['coordinate_frame']['render_size_px']
            pw,ph=row['coordinate_frame']['page_size_points']
            for gid,g in zip(row['candidate_geometry_ids'],row['display_parent_geometry']):
                parents[gid]=[g[0]*w/pw,g[1]*h/ph,g[2]*w/pw,g[3]*h/ph]
        return cls(gray,[(gid,g,'PROPOSAL_ONLY') for gid,g in parents.items()])

    def nominations(self):
        # Same raw proposals/order as extract.nominations([], gray).
        for x, y, w, h, area in self.stats[1:]:
            if 6 <= max(w, h) <= 180 and area >= 6:
                yield {'kind':'untyped_ink_control', 'center':[float(x+w/2), float(y+h/2)],
                       'geometry':[], 'features':{}, 'ink_bbox':[int(x),int(y),int(w),int(h)],
                       'target_extent_basis':'8-connected pixels below 160; not an exclusive glyph/entity boundary'}

    def assess(self, roi):
        evidence = {'status':'uncertain_extent', 'queue_eligible':False,
                    'coordinate_unit':'native source-raster px',
                    'semantic_identity_confirmed':False, 'glyph_identity_confirmed':False}
        x,y,w,h = map(int, roi)
        if x < 0 or y < 0 or x+w > self.gray.shape[1] or y+h > self.gray.shape[0]:
            return {**evidence,'reason':'component_range_out_of_source'}
        patch = self.labels[y:y+h,x:x+w]
        ids = np.unique(patch); ids = ids[ids>0]
        # Bounding boxes enclosing multiple disconnected objects are not exclusive.
        if len(ids) != 1:
            return {**evidence,'reason':'multiple_or_missing_components_in_nomination'}
        cid = int(ids[0]); sx,sy,sw,sh,area = map(int,self.stats[cid])
        evidence.update(component_box=[sx,sy,sw,sh], component_ink_pixels=area,
                        component_range_matches=(sx,sy,sw,sh)==(x,y,w,h))
        if not evidence['component_range_matches']:
            return {**evidence,'reason':'nomination_is_only_part_of_connected_ink'}
        yy,xx = np.where(patch==cid); points=np.column_stack((xx+x,yy+y)).astype(float)
        if len(points)<6:
            return {**evidence,'reason':'insufficient_object_extent'}
        eigen,vectors = np.linalg.eigh(np.cov(points,rowvar=False))
        tangent,normal = vectors[:,-1],vectors[:,0]
        centered=points-points.mean(0)
        linear = float(np.quantile(np.abs(centered@normal),.9)) <= 1
        evidence.update(line_like_ink=linear,minor_spread_px=float(np.sqrt(max(0,eigen[0]))))
        # A connected bend can still be part of a dashed carrier. Require thin
        # orthogonal arms AND repeated source components on an arm's phase.
        mask=patch==cid
        arms=[np.flatnonzero(mask.sum(axis=0)>=.75*h),
              np.flatnonzero(mask.sum(axis=1)>=.75*w)]
        if (w>=4 and h>=4 and all(0<len(arm)<=2 for arm in arms)
                and float(mask.mean())<=.6):
            for axis,arm in enumerate(arms):
                across_axis=axis;along_axis=1-axis
                anchor=(x,y)[across_axis]+float(arm.mean())+.5
                extent=(w,h)[along_axis]
                other_extent=self.stats[:,2+along_axis]
                other_width=self.stats[:,2+across_axis]
                candidates=(np.arange(len(self.stats))>0)&(np.arange(len(self.stats))!=cid)
                candidates &= np.abs(self.centers[:,across_axis]-anchor)<=1.5
                candidates &= (other_width<=max(2,len(arm)*1.5))
                candidates &= (other_extent>=.7*extent)&(other_extent<=1.5*extent)
                offsets=self.stats[:,along_axis]-(x,y)[along_axis]
                candidates &= (np.abs(offsets)<=6*extent)&(np.abs(offsets)>extent)
                positions=np.sort(np.r_[0,offsets[candidates]])
                steps=np.diff(positions);steps=steps[steps>extent]
                if len(steps)<2:continue
                pitch=float(np.median(steps))
                phased=np.abs(positions/pitch-np.rint(positions/pitch))*pitch<=1.5
                if int(phased.sum())>=4:
                    return {**evidence,'status':'line_fragment',
                            'reason':'bent_fragment_on_repeated_dash_carrier',
                            'dash_arm_axis':'vertical' if axis==0 else 'horizontal',
                            'series_step_px':pitch,'series_phase_members':int(phased.sum()),
                            'meaning_limit':'source dash repetition at a bend; no glyph or engineering label'}
        # A repeated collinear series is evidence beyond a skinny bounding box.
        delta=self.centers-self.centers[cid]
        along=delta@tangent; across=np.abs(delta@normal)
        ext=max(w,h)
        neighbors=(np.arange(len(self.stats))!=cid)&(np.arange(len(self.stats))>0)
        neighbors &= (across<=1)&(np.abs(along)<=4*ext)
        neighbors &= (self.stats[:,2]>=max(1,w*.5))&(self.stats[:,2]<=max(2,w*1.5))
        neighbors &= (self.stats[:,3]>=max(1,h*.5))&(self.stats[:,3]<=max(2,h*1.5))
        positions=np.sort(np.r_[0,along[neighbors]])
        steps=np.diff(positions)
        periodic=(linear and len(positions)>=4 and len(steps)>0 and
                  float(np.median(steps))>0 and
                  bool(np.all(np.abs(steps-np.median(steps))<=.25*np.median(steps))))
        evidence['collinear_series_members']=int(len(positions))
        if periodic:
            return {**evidence,'status':'line_fragment','reason':'repeated_collinear_dash_sequence',
                    'series_step_px':float(np.median(steps)),
                    'meaning_limit':'geometric series evidence; no printed-symbol/engineering semantic label'}
        matches=[]
        if linear:
            for gid,g in self.lines:
                lo=g.min(0)-2.5;hi=g.max(0)+2.5
                if hi[0]<x or lo[0]>x+w or hi[1]<y or lo[1]>y+h:continue
                direction=g[1]-g[0];length=float(np.linalg.norm(direction))
                if length<40 or abs(float(tangent@(direction/length)))<np.cos(np.deg2rad(3)):continue
                u=np.clip((points-g[0])@direction/max(length**2,1e-9),0,1)
                distances=np.linalg.norm(points-(g[0]+u[:,None]*direction),axis=1)
                fraction=float((distances<=2.5).mean())
                if fraction>=.9:matches.append((gid,fraction))
        evidence['overlapping_detected_lines']=[{'member':g,'ink_fraction':f} for g,f in matches[:4]]
        if matches:
            return {**evidence,'status':'line_fragment','reason':'ink_on_detected_long_line_carrier',
                    'meaning_limit':'line-carrier overlap; a possible linear printed symbol is unresolved, not relabeled'}
        if linear:
            # An isolated 一 / minus / underline is not invalid just because it is flat.
            return {**evidence,'reason':'linear_print_or_line_fragment_unresolved'}
        if min(w,h)<3 or evidence['minor_spread_px']<1:
            return {**evidence,'reason':'possible_ink_fragment_not_complete_object_evidence'}
        return {**evidence,'status':'separable_ink_candidate','queue_eligible':True,
                'reason':'full_threshold_component_with_two_dimensional_extent',
                'extent_limit':'reasonable connected-ink candidate only; disconnected glyph parts and semantic completeness remain unconfirmed'}
