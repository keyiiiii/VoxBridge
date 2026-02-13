"""Audio recording using sounddevice (push-to-talk)."""

import threading
import time

import numpy as np
import sounddevice as sd


class Recorder:
    """Records audio from the default microphone."""

    def __init__(self, sample_rate: int = 16000, max_duration: int = 60):
        self.sample_rate = sample_rate
        self.max_duration = max_duration
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._max_timer: threading.Timer | None = None

    def start(self) -> None:
        """Start recording audio."""
        with self._lock:
            self._frames = []
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                callback=self._audio_callback,
            )
            self._stream.start()

            # Auto-stop after max_duration
            self._max_timer = threading.Timer(self.max_duration, self.stop)
            self._max_timer.daemon = True
            self._max_timer.start()

    def stop(self) -> np.ndarray | None:
        """Stop recording and return audio as numpy array (float32, mono, 16kHz)."""
        with self._lock:
            if self._max_timer:
                self._max_timer.cancel()
                self._max_timer = None

            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
                self._stream = None

            if not self._frames:
                return None

            audio = np.concatenate(self._frames, axis=0).flatten()
            self._frames = []
            return audio

    def _audio_callback(self, indata, frames, time_info, status):
        """Sounddevice callback - collects audio frames."""
        if status:
            print(f"[Recorder] {status}")
        self._frames.append(indata.copy())

    @property
    def is_recording(self) -> bool:
        return self._stream is not None and self._stream.active
