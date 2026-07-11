from __future__ import annotations

import unittest

from app.workflow_state import (
    WorkflowState,
    WorkflowStateError,
    WorkflowStateMachine,
)


class WorkflowStateTests(unittest.TestCase):
    def test_full_calibrated_workflow(self) -> None:
        workflow = WorkflowStateMachine()
        workflow.import_image()
        workflow.confirm_perspective()
        workflow.mark_preprocessed()
        workflow.mark_vectorized()
        workflow.mark_calibrated()
        workflow.mark_exported()

        self.assertEqual(workflow.state, WorkflowState.EXPORTED)
        self.assertTrue(workflow.calibrated)

    def test_unitless_export_does_not_claim_calibration(self) -> None:
        workflow = WorkflowStateMachine()
        workflow.import_image()
        workflow.confirm_perspective()
        workflow.mark_preprocessed()
        workflow.mark_vectorized()
        workflow.mark_exported()

        self.assertEqual(workflow.state, WorkflowState.EXPORTED)
        self.assertFalse(workflow.calibrated)

    def test_vectorization_before_perspective_is_rejected(self) -> None:
        workflow = WorkflowStateMachine()
        workflow.import_image()
        with self.assertRaises(WorkflowStateError):
            workflow.mark_vectorized()

    def test_invalidation_removes_downstream_calibration(self) -> None:
        workflow = WorkflowStateMachine()
        workflow.import_image()
        workflow.confirm_perspective()
        workflow.mark_preprocessed()
        workflow.mark_vectorized()
        workflow.mark_calibrated()
        workflow.invalidate_to(WorkflowState.PERSPECTIVE_CONFIRMED)

        self.assertEqual(workflow.state, WorkflowState.PERSPECTIVE_CONFIRMED)
        self.assertFalse(workflow.calibrated)

    def test_invalidation_cannot_move_forward(self) -> None:
        workflow = WorkflowStateMachine()
        workflow.import_image()
        with self.assertRaises(WorkflowStateError):
            workflow.invalidate_to(WorkflowState.VECTORIZED)


if __name__ == "__main__":
    unittest.main()
