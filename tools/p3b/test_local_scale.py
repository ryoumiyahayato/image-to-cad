"""Only native local source, unit conversion and replay-mode regressions."""

import copy
import unittest

import numpy as np

from measurement import SourceWindow,measure_row,stroke_profile_scaled
from local_detection import confined_to_crop_border
from quality import sample_line,ink_distance,inspect
from queue_dedup import deduplicate
from test_trial_sampling import candidate


class LocalScaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from common import ROOT
        import sys
        sys.path.insert(0,str(ROOT/'cad_photo_to_dxf'))
        from app.geometry.line_detect import LineSegment
        from app.geometry.source_presentation import stroke_profile
        cls.Line=LineSegment;cls.legacy=staticmethod(stroke_profile)

    def test_reference_scale_one_preserves_existing_dark_run_profile(self):
        gray=np.full((256,256),255,np.uint8);gray[80:84,20:220]=0
        line=self.Line(30,81,210,81)
        self.assertEqual(self.legacy(gray,line),stroke_profile_scaled(gray,line,pixel_scale=1,reference_shape=gray.shape))

    def test_native_thin_line_is_not_lost_to_sparse_grid_and_units_are_explicit(self):
        gray=np.full((512,512),255,np.uint8);gray[104:105,20:490]=0
        line=self.Line(30,100,460,100)
        self.assertIsNone(self.legacy(gray,line))
        value=stroke_profile_scaled(gray,line,pixel_scale=4,reference_shape=(128,128))
        self.assertEqual(value['source_width_px'],1)
        self.assertEqual(value['samples'],19)

    def test_source_outside_allowed_physical_seed_distance_is_not_borrowed(self):
        gray=np.full((512,512),255,np.uint8);gray[111:112,20:490]=0
        self.assertIsNone(stroke_profile_scaled(gray,self.Line(30,100,460,100),pixel_scale=4,reference_shape=(128,128)))

    def test_real_cross_window_line_is_not_a_crop_border(self):
        self.assertFalse(confined_to_crop_border(np.array([[1,50],[198,50]]),[200,100],5))
        self.assertTrue(confined_to_crop_border(np.array([[20,1],[180,1]]),[200,100],5))
        self.assertFalse(confined_to_crop_border(np.array([[50,1],[50,98]]),[200,100],5))

    def test_gap_length_tracks_sampling_spacing_instead_of_just_failed_count(self):
        gray=np.full((30,10000),255,np.uint8);gray[14:17,10:9990]=0;gray[14:17,5000:5030]=255
        metric=sample_line(gray,ink_distance(gray),[20,15,9980,15])
        self.assertGreater(metric['SAMPLING_STEP_PX'],1)
        self.assertAlmostEqual(metric['MAX_UNSUPPORTED_RUN_PX'],metric['UNSUPPORTED_RUN_FAILED_SAMPLES']*metric['SAMPLING_STEP_PX'])

    def test_opposite_edge_polarities_can_both_pass(self):
        gray=np.full((256,256),255,np.uint8);gray[80:85,20:230]=0
        row={'source_bbox':[0,0,256,256],'candidate_geometry':[['a',[30,80,220,80],'test'],['b',[30,84,220,84],'test']]}
        self.assertTrue(inspect(row,gray,require_directional_edge=True)['HUMAN_QUEUE_ELIGIBLE'])

    def test_ordinary_sampling_still_excludes_history_and_replay_is_explicit(self):
        old=candidate('old');new=candidate('new');new['purpose']='development_local_scale_replay'
        self.assertEqual(len(deduplicate([copy.deepcopy(new)],None,preview_policy={},history=[old])[0]),0)
        result=deduplicate([copy.deepcopy(new)],None,preview_policy={},history=[old],preview_mode='development_replay')
        self.assertEqual(len(result[0]),1);self.assertFalse(result[2]['new_information_claimed'])
        new['purpose']='ordinary_preview'
        with self.assertRaises(ValueError):deduplicate([new],None,preview_policy={},preview_mode='development_replay')

    def test_missing_window_pixels_are_not_profile_zero(self):
        frame={'pdf_origin':[0,0],'pdf_x_per_pixel':[1,0],'pdf_y_per_pixel':[0,1],'render_size_px':[512,512],'effective_dpi':110}
        row={'source_dpi':110,'coordinate_frame':frame,'measurement_reference_frame':frame,
             'candidate_geometry':[['a',[200,200,400,200],'test']]}
        value=measure_row(row,SourceWindow(np.full((10,10),255,np.uint8),(0,0),(512,512)))
        self.assertEqual(value['measurement_status'],'read_or_coordinate_error')
        self.assertIsNone(value['current_p3a_measurement'][0]['profile'])


if __name__=='__main__':unittest.main()
