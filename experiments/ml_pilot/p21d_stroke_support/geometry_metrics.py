from collections import deque
import numpy as np
from PIL import Image,ImageFilter

def dilate(mask):return np.asarray(Image.fromarray(mask.astype(np.uint8)*255).filter(ImageFilter.MaxFilter(3)))>0
def samples(points):
    result=[]
    for a,b in zip(points,points[1:]):
        n=max(2,int(np.hypot(b[0]-a[0],b[1]-a[1]))+1)
        result.extend(zip(np.rint(np.linspace(a[0],b[0],n)).astype(int),np.rint(np.linspace(a[1],b[1],n)).astype(int)))
    return np.array(result,dtype=int)
def bridge(pred,region,valid):
    x0,y0,x1,y1=map(int,region['box']);h,w=pred.shape
    if x0<0 or y0<0 or x1>w or y1>h or x1<=x0 or y1<=y0:return None
    if not valid[y0:y1,x0:x1].all():return None
    a=pred[y0:y1,x0:x1]
    if region.get('axis',0):a=a.T
    queue=deque((y,0) for y in range(a.shape[0]) if a[y,0]);seen=set(queue)
    while queue:
        y,x=queue.popleft()
        if x==a.shape[1]-1:return True
        for dy in [-1,0,1]:
            for dx in [-1,0,1]:
                yy,xx=y+dy,x+dx
                if 0<=yy<a.shape[0] and 0<=xx<a.shape[1] and a[yy,xx] and (yy,xx) not in seen:
                    seen.add((yy,xx));queue.append((yy,xx))
    return False

def geometry(meta,target,pred,valid):
    source=dilate(target);near=dilate(pred);h,w=target.shape;rows=[];end_total=end_hit=0
    for obj in meta['objects']:
        ps=samples(obj['points'])
        if not len(ps):continue
        good=(ps[:,0]>=0)&(ps[:,0]<w)&(ps[:,1]>=0)&(ps[:,1]<h);ps=ps[good]
        if len(ps)<2:continue
        xs,ys=ps[:,0],ps[:,1];visible=source[ys,xs]&valid[ys,xs]
        hit=near[ys,xs]&visible;den=int(visible.sum());complete_eligible=bool(visible.all())
        rows.append(dict(id=obj['id'],kind=obj['kind'],visible_points=den,
            coverage=float(hit.sum()/max(1,den)),complete_eligible=complete_eligible,
            complete_covered=bool(complete_eligible and hit.mean()>=.95)))
        for j in [0,-1]:
            if visible[j]:end_total+=1;end_hit+=int(near[ys[j],xs[j]])
    gaps=[bridge(pred,r,valid) for r in meta['openings']]
    pairs=[bridge(pred,r,valid) for r in meta['parallel_gaps']]
    return dict(objects=rows,complete_eligible=sum(r['complete_eligible'] for r in rows),
        complete_covered=sum(r['complete_covered'] for r in rows),visible_endpoints=end_total,
        supported_endpoints=end_hit,openings_evaluated=sum(v is not None for v in gaps),false_opening_bridges=sum(v is True for v in gaps),
        parallel_gaps_evaluated=sum(v is not None for v in pairs),parallel_merges=sum(v is True for v in pairs))
