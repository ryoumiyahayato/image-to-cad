"""Only the offline feedback changes; no production/frozen-data checks."""

import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from common import ROOT, read_rows
from quality import inspect
from trial_sampling import pixel_center_to_pdf,pdf_to_pixel_center,render_explicit


class FeedbackRepairTests(unittest.TestCase):
    def test_real_hatched_pair_is_held_without_moving_it_and_clear_controls_survive(self):
        base=ROOT/'local-artifacts/product-fix-p3b/preview-trial-20261010-001'
        rows={r['sample_id']:r for r in read_rows(base/'manifest.jsonl')}
        for sid in ('preview-001','preview-005','preview-006','preview-007','preview-020'):
            row=copy.deepcopy(rows[sid]);x,y,_,_=row['source_bbox']
            original=copy.deepcopy(row['candidate_geometry'])
            gray=np.array(Image.open(base/row['preview_files']['crop']).convert('L'))
            row['source_bbox']=[0,0,256,256]
            for g in row['candidate_geometry']:
                g[1]=(np.asarray(g[1]).reshape(2,2)-[x,y]).flatten().tolist()
            before=inspect(row,gray)
            after=inspect(row,gray,require_directional_edge=True)
            self.assertTrue(before['HUMAN_QUEUE_ELIGIBLE'],sid)
            self.assertEqual(after['HUMAN_QUEUE_ELIGIBLE'],sid!='preview-006',sid)
            if sid=='preview-006':self.assertIn('EDGE_DIRECTION_UNCONFIRMED',after['rejection_reasons'])
            for old,new in zip(original,row['candidate_geometry']):
                np.testing.assert_allclose(np.asarray(new[1]).reshape(2,2)+[x,y],np.asarray(old[1]).reshape(2,2))

    def test_full_segment_gap_is_not_hidden_by_mean_or_endpoint_support(self):
        gray=np.full((256,256),255,np.uint8);gray[99:102,25:225]=0
        row={'source_bbox':[0,0,256,256],'candidate_geometry':[['a',[30,99,210,99],'test']]}
        self.assertTrue(inspect(row,gray,require_directional_edge=True)['HUMAN_QUEUE_ELIGIBLE'])
        gray[99:102,100:112]=255
        self.assertTrue(inspect(row,gray)['HUMAN_QUEUE_ELIGIBLE'])
        after=inspect(row,gray,require_directional_edge=True)
        self.assertIn('SOURCE_INK_GAP_IN_TARGET_EXTENT',after['rejection_reasons'])

    def test_rotated_cross_dpi_map_distinguishes_centres_and_box_edges(self):
        low={'pdf_origin':[1786.,3118.],'pdf_x_per_pixel':[0.,-.75],'pdf_y_per_pixel':[-.75,0.]}
        high={'pdf_origin':[1786.,3118.],'pdf_x_per_pixel':[0.,-.225],'pdf_y_per_pixel':[-.225,0.]}
        point=[3180.25,445.75]
        actual=pdf_to_pixel_center(pixel_center_to_pdf(point,low),high)
        np.testing.assert_allclose(actual,(np.asarray(point)+.5)*(.75/.225)-.5)
        np.testing.assert_allclose(pdf_to_pixel_center(pixel_center_to_pdf(actual,high),low),point)

    def test_current_locator_uses_this_candidates_file_without_opening_ui(self):
        from trial_labeling import RepairTrialApp
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)
            Image.new('L',(10,10),17).save(base/'current.png')
            Image.new('L',(10,10),230).save(base/'shared.png')
            shown=[]
            app=SimpleNamespace(index=0,base=base,rows=[{'sample_id':'preview-example','preview_files':{'page_position':'current.png','shared_page_position':'shared.png'}}],popup=lambda title,im:shown.append((title,im.getpixel((0,0)))))
            RepairTrialApp.whole_page(app)
            self.assertEqual(shown[0][1],17)
            self.assertIn('当前preview-example',shown[0][0])

    def test_pdf_endpoint_check_uses_centres_for_lines_and_boundaries_for_roi(self):
        from preview_trial import coordinate_check
        frame={'pdf_origin':[0,0],'pdf_x_per_pixel':[1,0],'pdf_y_per_pixel':[0,1],'render_size_px':[256,256]}
        row={'source_path':'not-opened.pdf','source_page':1,'coordinate_frame':frame,
             'candidate_geometry':[['a',[20,30,40,30],'test']]}
        class Document:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def __getitem__(self,key):return SimpleNamespace(close=lambda:None)
        inverse=lambda page,size,p:[round(v) for v in p]
        with patch('preview_trial.pdfium.PdfDocument',return_value=Document()),patch('preview_trial.pdf_to_device',side_effect=inverse):
            a=coordinate_check(row,np.full((256,256),255,np.uint8))
            self.assertEqual(a[0]['PDFium_page_point'],[20.5,30.5])
            row.update(candidate_geometry=[],target_roi=[20,30,4,8])
            b=coordinate_check(row,np.full((256,256),255,np.uint8))
            self.assertEqual(b[0]['PDFium_page_point'],[20.,30.])

    def test_cache_file_page_frame_mismatch_is_reported(self):
        unit={'resolved_path':str(ROOT/'example.pdf'),'page_or_layout':{'page_number':2},
              'source_render_cache':{'frame':'frame.json','image':'source.png'}}
        with patch('trial_sampling.read',return_value={'source_path':str(ROOT/'example.pdf'),'source_page':1,'frame':{'render_size_px':[10,10]}}),patch('trial_sampling.Image.open',return_value=Image.new('L',(10,10),255)):
            with self.assertRaisesRegex(ValueError,'cache does not match'):render_explicit(unit)


if __name__=='__main__':unittest.main()
