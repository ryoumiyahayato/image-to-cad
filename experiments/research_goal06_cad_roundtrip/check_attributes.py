"""Directed Goal05 attribute checks, separate from width hypothesis. No real geometry writes."""
import sys
sys.dont_write_bytecode=True
from prepare import OUT,G5,V2,load,save
import ezdxf
from ezdxf.addons.drawing.properties import RenderContext

def main():
    result=[]
    for name in ['B-G19','A-G38']:
        original=ezdxf.readfile(V2/name/'experimental.dxf');saved=ezdxf.readfile(G5/'gui'/name/'gui-no-edit-saved.dxf')
        audit=load(G5/'gui'/name/'source-vs-gui-serialization.json');contexts=[RenderContext(d) for d in [original,saved]]
        colors=[]
        for change in audit['attribute_changes']:
            if 'color' not in change['changes']:continue
            a,b=original.entitydb[change['input_handle']],saved.entitydb[change['gui_handle']];row={'input_handle':a.dxf.handle,'gui_handle':b.dxf.handle,'fields':change['changes']['color'],'resolved':{}}
            for background in ['#ffffff','#000000']:
                for ctx in contexts:ctx.current_layout_properties.set_colors(background)
                values=[ctx.resolve_color(e) for ctx,e in zip(contexts,[a,b])]
                row['resolved'][background]={'input':values[0],'saved':values[1],'equal':values[0]==values[1]}
            colors.append(row)
        images=[]
        for d,path in [(original,V2/name/'experimental.dxf'),(saved,G5/'gui'/name/'gui-no-edit-saved.dxf')]:
            for e in d.modelspace().query('IMAGE'):
                from pathlib import Path
                f=Path(d.entitydb[e.dxf.image_def_handle].dxf.filename);f=f if f.is_absolute() else path.parent/f
                images.append({'dxf':str(path),'flags':e.dxf.flags,'show_when_not_screen_aligned':bool(e.dxf.flags&2),'transparency_on':bool(e.dxf.flags&8),
                    'clipping':e.dxf.clipping,'filename':str(f.resolve()),'file_exists':f.exists(),
                    'visual_status':'NOT_VERIFIED_MISSING_EXTERNAL_IMAGE' if not f.exists() else 'AVAILABLE_NOT_GUI_VERIFIED'})
        styles=[]
        for d in [original,saved]:
            s=d.styles.get('wqy-unicode');styles.append({'style':'wqy-unicode','font':s.dxf.font,'active_entities':sum(e.dxf.get('style','')=='wqy-unicode' for e in d.modelspace().query('TEXT'))})
        result.append({'case':name,'color_changes':colors,'font_styles':styles,'font_finding':'TEXT style name unchanged; installed wqy-unicode.lff exists; release imports TEXT by style name and ignores addTextStyle table. Local basename resolution is explained, not a cross-editor glyph equivalence claim.',
            'IMAGE':images,'XDATA':{'original_entities':sum(e.xdata is not None for e in original.modelspace()),'GUI_entities':sum(e.xdata is not None for e in saved.modelspace()),'old_sidecar_rebinding':'REFUSED_UNVERIFIED_EXTERNAL_EDITS'},
            'paper_color_equivalence_scope':'ezdxf independent resolved color on the specified white background only, not complete GUI display acceptance'})
    save(OUT/'directed-attribute-check.json',result)
    print([{'case':r['case'],'changed_colors':len(r['color_changes']),'white_equal':sum(c['resolved']['#ffffff']['equal'] for c in r['color_changes']),'black_equal':sum(c['resolved']['#000000']['equal'] for c in r['color_changes']),'images':r['IMAGE']} for r in result])
if __name__=='__main__':main()
