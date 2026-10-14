"""Focused checks using this batch's real assets and isolated decision states."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import tkinter as tk

import numpy as np
from PIL import Image

from common import ROOT,read
from trial_labeling import TrialStore,RepairTrialApp,load_trial,CLASSES
from target_view import target_overlay,annotated_zoom,target_zoom

BASE=ROOT/"local-artifacts/product-fix-p3b/preview-trial-20261010-001"


class TrialLabelingTests(unittest.TestCase):
    def setUp(self):
        self.rows,self.base=load_trial(BASE/"manifest.jsonl")
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/"test-trial-labels.json"
        self.store=TrialStore(self.path,self.rows,"isolated-test")

    def tearDown(self):self.temp.cleanup()

    def test_members_and_order_match_the_current_sources(self):
        self.assertEqual(len(self.rows),20)
        self.assertNotIn("preview-004",[r["sample_id"] for r in self.rows])
        self.assertNotIn("preview-022",[r["sample_id"] for r in self.rows])

    def test_defer_without_reason_restore_and_modify_keep_history(self):
        self.store.answer(0,"deferred")
        restored=TrialStore(self.path,self.rows,"isolated-test")
        answer=restored.state["answers"][self.rows[0]["sample_id"]]
        self.assertTrue(answer["processed"])
        self.assertIsNone(answer["category"])
        self.assertIsNone(answer["optional_reason"])
        self.assertEqual(restored.counts()["classified"],0)
        self.assertEqual(restored.state["cursor_index"],1)
        restored.navigate(0)
        restored.answer(0,"classified",1,note="test observation")
        restored.navigate(0)
        restored.answer(0,"classified",2)
        final=TrialStore(self.path,self.rows,"isolated-test")
        self.assertEqual(final.state["answers"][self.rows[0]["sample_id"]]["category"],CLASSES[2])
        self.assertEqual(final.counts()["processed"],1)
        self.assertEqual(final.counts()["classified"],1)
        self.assertEqual(final.state["history"][-1]["previous_answer"]["category"],CLASSES[1])

    def test_error_candidate_is_not_other_and_removes_prior_class(self):
        self.store.answer(0,"classified",3)
        self.store.navigate(0)
        self.store.answer(0,"invalid_nomination")
        answer=self.store.state["answers"][self.rows[0]["sample_id"]]
        self.assertIsNone(answer["category"])
        self.assertFalse(answer["category_assigned"])
        self.assertEqual(self.store.counts()["invalid_candidates"],1)

    def test_pending_scope_records_observation_not_a_hard_label(self):
        index=next(i for i,r in enumerate(self.rows) if r["sample_id"]=="preview-011")
        self.store.answer(index,"classified",1)
        answer=self.store.state["answers"]["preview-011"]
        self.assertEqual(answer["observation_code"],1)
        self.assertEqual(answer["status"],"rule_pending_observation")
        self.assertIsNone(answer["category"])
        self.assertEqual(self.store.counts()["processed"],1)
        self.assertEqual(self.store.counts()["classified"],0)

    def test_atomic_failure_does_not_advance_or_change_answers(self):
        self.store.startup(False)
        old_memory=copy.deepcopy(self.store.state);old_disk=read(self.path)
        with patch("trial_labeling.atomic_json",side_effect=OSError("simulated save failure")):
            with self.assertRaises(OSError):self.store.answer(0,"classified",1)
        self.assertEqual(self.store.state,old_memory)
        self.assertEqual(read(self.path),old_disk)

    def test_geometry_change_cannot_silently_accept_existing_answers(self):
        self.store.answer(0,"deferred")
        changed=copy.deepcopy(self.rows);changed[0]["candidate_geometry"][0][1][0]+=1
        with self.assertRaises(ValueError):TrialStore(self.path,changed,"isolated-test")
        self.assertEqual(read(self.path)["answers"][self.rows[0]["sample_id"]]["category"],None)

    def test_finish_keeps_draft_cursor_without_creating_an_answer(self):
        self.store.navigate(3)
        self.store.finish("unfinished observation",None)
        state=TrialStore(self.path,self.rows,"isolated-test").state
        self.assertEqual(state["cursor_index"],3)
        self.assertEqual(state["drafts"][self.rows[3]["sample_id"]]["observation"],"unfinished observation")
        self.assertEqual(state["answers"],{})

    def test_real_pixels_layers_and_zoom_do_not_mutate_the_target(self):
        before=copy.deepcopy(self.rows)
        for row in self.rows:
            with Image.open(self.base/row["preview_files"]["crop"]) as im:gray=im.convert("L")
            plain=target_overlay(gray,row,1,trial=True,members="none")
            self.assertTrue(np.array_equal(np.array(gray),np.array(plain)[:,:,0]))
            for mode in ("A","B","all"):
                view=target_overlay(gray,row,1.5,trial=True,members=mode)
                self.assertEqual(view.size,(384,384))
            if len(row["candidate_geometry"])<2:
                b=target_overlay(gray,row,1,trial=True,members="B")
                self.assertTrue(np.array_equal(np.array(plain),np.array(b)))
            for factor in (4,8):
                self.assertEqual(target_zoom(gray,row,factor).size,(512,512))
                self.assertEqual(annotated_zoom(gray,row,factor,trial=True,members="all").size,(512,512))
        self.assertEqual(self.rows,before)

    def test_tk_callbacks_all_real_members_resume_and_save_failure(self):
        root=tk.Tk();root.withdraw()
        try:
            def isolated_store(path,rows,annotator):return TrialStore(self.path,rows,"isolated-test")
            with patch("trial_labeling.TrialStore",side_effect=isolated_store):
                app=RepairTrialApp(root,BASE/"manifest.jsonl",BASE/"trial-labels.json","isolated-test")
            ids=[]
            for i,row in enumerate(self.rows):
                app.store.navigate(i);app.show();ids.append(row["sample_id"])
                self.assertIn(row["sample_id"],app.title.get())
                app.layer("none");app.layer("A")
                if len(row["candidate_geometry"])==2:
                    app.layer("B");self.assertEqual(app.mode,"B")
                else:self.assertEqual(str(app.layer_buttons["B"]["state"]),"disabled")
                app.layer("all")
                with patch.object(app,"popup") as popup:
                    app.zoom(8)
                    self.assertEqual(popup.call_args[0][1].size,(1024,512))
            self.assertEqual(ids,[r["sample_id"] for r in self.rows])
            app.store.navigate(0);app.show();app.choose("deferred")
            self.assertEqual(app.index,1)
            app.navigate(-1);self.assertEqual(app.index,0)
            with patch("trial_labeling.atomic_json",side_effect=OSError("simulated failure")),patch("trial_labeling.messagebox.showerror"):
                app.choose("classified",1)
            self.assertEqual(app.index,0)
            self.assertIn("保存失败",app.saved.get())
            self.assertEqual(app.store.state["answers"]["preview-001"]["status"],"deferred")
            restored=TrialStore(self.path,self.rows,"isolated-test")
            self.assertEqual(restored.state["cursor_index"],0)
            self.assertIsNone(restored.state["answers"]["preview-001"]["category"])
            print("Hidden Tk actual-asset checks: 20 displayed IDs; required height",root.winfo_reqheight(),"window",root.winfo_height())
        finally:root.destroy()


if __name__=="__main__":unittest.main()
