"""Background inference worker for the AI pipeline.

Runs the same per-frame detection -> pose -> classification pipeline used by
the CLI (see civicsense.cli.classifier) in a worker thread so the GUI can
render live bounding boxes and log every classification event, not just
confirmed littering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from civicsense.ai.model_manager import ModelManager
from civicsense.cli.classifier import FrameResult, classify_frame
from civicsense.core.logging import get_logger

logger = get_logger("ai")


@dataclass
class InferenceResult:
    """Complete result of processing a single frame through the pipeline."""

    frame_idx: int
    frame: NDArray[np.uint8]
    frame_result: FrameResult
    fps: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


class InferenceWorker:
    """Runs the full AI inference pipeline on video frames.

    Delegates classification to civicsense.cli.classifier.classify_frame so
    the GUI reasons about frames identically to the CLI.
    """

    def __init__(self, model_manager: ModelManager) -> None:
        """Initialize the inference worker with a model manager.

        Args:
            model_manager: The shared ModelManager instance.
        """
        self._model_manager = model_manager
        self._frame_idx: int = 0
        self._last_fps: float = 0.0

    def process_frame(
        self,
        frame: NDArray[np.uint8],
    ) -> InferenceResult:
        """Process a single frame through the full inference pipeline.

        Args:
            frame: Input video frame as a BGR numpy array.

        Returns:
            InferenceResult with the frame and its classification.
        """
        self._frame_idx += 1

        frame_result = classify_frame(
            frame,
            self._model_manager.detector,
            self._model_manager.pose_detector,
            self._frame_idx,
        )

        return InferenceResult(
            frame_idx=self._frame_idx,
            frame=frame,
            frame_result=frame_result,
            fps=self._last_fps,
        )

    def reset(self) -> None:
        """Reset the inference pipeline state."""
        self._frame_idx = 0
