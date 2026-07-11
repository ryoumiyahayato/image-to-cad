from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class WorkflowState(IntEnum):
    EMPTY = 0
    IMPORTED = 1
    PERSPECTIVE_CONFIRMED = 2
    PREPROCESSED = 3
    VECTORIZED = 4
    CALIBRATED = 5
    EXPORTED = 6


class WorkflowStateError(RuntimeError):
    pass


@dataclass
class WorkflowStateMachine:
    state: WorkflowState = WorkflowState.EMPTY
    calibration_completed: bool = False

    def require(self, minimum: WorkflowState, action: str) -> None:
        if self.state < minimum:
            raise WorkflowStateError(
                f"{action} requires {minimum.name}, current state is {self.state.name}"
            )

    def clear(self) -> None:
        self.state = WorkflowState.EMPTY
        self.calibration_completed = False

    def import_image(self) -> None:
        self.state = WorkflowState.IMPORTED
        self.calibration_completed = False

    def confirm_perspective(self) -> None:
        self.require(WorkflowState.IMPORTED, "perspective confirmation")
        self.state = WorkflowState.PERSPECTIVE_CONFIRMED
        self.calibration_completed = False

    def mark_preprocessed(self) -> None:
        self.require(WorkflowState.PERSPECTIVE_CONFIRMED, "preprocessing")
        if self.state < WorkflowState.PREPROCESSED:
            self.state = WorkflowState.PREPROCESSED

    def mark_vectorized(self) -> None:
        self.require(WorkflowState.PREPROCESSED, "vectorization")
        if self.state < WorkflowState.VECTORIZED:
            self.state = WorkflowState.VECTORIZED

    def mark_calibrated(self) -> None:
        self.require(WorkflowState.VECTORIZED, "calibration")
        self.state = WorkflowState.CALIBRATED
        self.calibration_completed = True

    def mark_exported(self) -> None:
        self.require(WorkflowState.VECTORIZED, "export")
        self.state = WorkflowState.EXPORTED

    def invalidate_to(self, target: WorkflowState) -> None:
        if target > self.state:
            raise WorkflowStateError(
                f"cannot invalidate forward from {self.state.name} to {target.name}"
            )
        self.state = target
        if target < WorkflowState.CALIBRATED:
            self.calibration_completed = False

    @property
    def perspective_confirmed(self) -> bool:
        return self.state >= WorkflowState.PERSPECTIVE_CONFIRMED

    @property
    def vectorized(self) -> bool:
        return self.state >= WorkflowState.VECTORIZED

    @property
    def calibrated(self) -> bool:
        return self.calibration_completed
