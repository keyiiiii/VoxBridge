"""Audio recording using sounddevice (push-to-talk)."""

import threading
import time

import numpy as np
import sounddevice as sd

# PortAudio's stream teardown can deadlock against CoreAudio (see _teardown).
DEFAULT_STOP_TIMEOUT_SEC = 3.0


class Recorder:
    """Records audio from the default microphone.

    Callers must keep start() / stop() off the main thread: both enter
    PortAudio, which blocks for as long as CoreAudio takes to hand the device
    over — and can block forever (see _teardown).
    """

    def __init__(self, sample_rate: int = 16000, max_duration: int = 60,
                 on_max_reached=None,
                 stop_timeout: float = DEFAULT_STOP_TIMEOUT_SEC):
        self.sample_rate = sample_rate
        self.max_duration = max_duration
        self.stop_timeout = stop_timeout
        self._on_max_reached = on_max_reached
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._max_timer: threading.Timer | None = None
        self._start_time: float | None = None

    def get_elapsed(self) -> float:
        """Return elapsed recording time in seconds."""
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    def start(self) -> None:
        """Start recording audio."""
        with self._lock:
            frames: list[np.ndarray] = []
            self._frames = frames
            self._start_time = time.time()
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                callback=self._make_callback(frames),
            )
            self._stream.start()

            # Auto-stop after max_duration
            self._max_timer = threading.Timer(
                self.max_duration, self._on_max_duration
            )
            self._max_timer.daemon = True
            self._max_timer.start()

    def stop(self) -> np.ndarray | None:
        """Stop recording and return audio as numpy array (float32, mono, 16kHz)."""
        with self._lock:
            if self._max_timer:
                self._max_timer.cancel()
                self._max_timer = None

            stream = self._stream
            frames = self._frames
            self._stream = None
            self._frames = []
            self._start_time = None

        # Teardown runs outside the lock: a stop that never returns must not
        # keep the next start() (or a live preview snapshot) waiting.
        if stream is not None:
            self._teardown(stream)

        frames = list(frames)
        if not frames:
            return None
        return np.concatenate(frames, axis=0).flatten()

    def get_audio_snapshot(self) -> np.ndarray | None:
        """Return a copy of the current audio buffer without stopping recording."""
        with self._lock:
            if not self._frames:
                return None
            return np.concatenate(self._frames, axis=0).flatten()

    def _teardown(self, stream) -> None:
        """Close the stream, abandoning it if PortAudio does not come back.

        stream.stop() enters AudioOutputUnitStop holding the AudioUnit mutex and
        then wants the HAL ProxyIOContext mutex, while the CoreAudio IO thread
        holds ProxyIOContext and — via PortAudio's startStopCallback ->
        AudioUnitGetProperty — wants the AudioUnit mutex. A default-input device
        change (headset connect/disconnect, device sleep) landing mid-stop closes
        that cycle and neither side ever returns. Waiting on it is what froze the
        whole app, so time the teardown out and leak the stream instead; the
        recorded frames are already in hand and each session owns its own buffer.
        """
        def _close():
            try:
                stream.stop()
                stream.close()
            except Exception as e:
                print(f"[Recorder] Stream close error: {e}")

        worker = threading.Thread(
            target=_close, daemon=True, name="voxbridge-audio-teardown"
        )
        worker.start()
        worker.join(self.stop_timeout)
        if worker.is_alive():
            print(
                f"[Recorder] WARNING: stream stop did not return within "
                f"{self.stop_timeout}s (CoreAudio deadlock) - abandoning stream"
            )

    def _on_max_duration(self) -> None:
        """Called when max recording duration is reached."""
        audio = self.stop()
        if self._on_max_reached:
            self._on_max_reached(audio)

    def _make_callback(self, frames: list[np.ndarray]):
        """Build the sounddevice callback for one recording session.

        The buffer is bound per session so a stream abandoned by _teardown
        cannot append into the next recording.
        """
        def _callback(indata, frame_count, time_info, status):
            if status:
                print(f"[Recorder] {status}")
            frames.append(indata.copy())

        return _callback

    @property
    def is_recording(self) -> bool:
        return self._stream is not None and self._stream.active
