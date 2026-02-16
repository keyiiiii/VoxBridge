"""Speech-to-Text using faster-whisper (local, offline)."""

import os

import numpy as np
from faster_whisper import WhisperModel


class STT:
    """Transcribes audio using faster-whisper."""

    def __init__(self, config: dict):
        self.model_name = config.get("model", "small")
        self.device = config.get("device", "cpu")
        self.compute_type = config.get("compute_type", "int8")
        self._model: WhisperModel | None = None

    def _ensure_model(self) -> WhisperModel:
        """Lazy-load the Whisper model."""
        if self._model is None:
            print(f"[STT] Loading model: {self.model_name} (device={self.device}, compute={self.compute_type})")
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
            print("[STT] Model loaded.")
        return self._model

    def is_model_cached(self) -> bool:
        """Check if the Whisper model is already downloaded locally."""
        cache_dir = os.path.join(
            os.path.expanduser("~"), ".cache", "huggingface", "hub"
        )
        if not os.path.isdir(cache_dir):
            return False
        # faster-whisper models are stored under "models--Systran--faster-whisper-<model>"
        expected_prefix = f"models--Systran--faster-whisper-{self.model_name}"
        for entry in os.listdir(cache_dir):
            if entry == expected_prefix:
                return True
        return False

    def preload(self) -> None:
        """Eagerly load the Whisper model (called with --preload)."""
        self._ensure_model()

    def transcribe(self, audio: np.ndarray, language: str = "ja") -> str:
        """Transcribe audio numpy array to text.

        Args:
            audio: float32 numpy array, mono, 16kHz
            language: Language code (ISO 639-1)

        Returns:
            Transcribed text string
        """
        model = self._ensure_model()

        segments, info = model.transcribe(
            audio,
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        text = "".join(segment.text for segment in segments)
        return text.strip()
