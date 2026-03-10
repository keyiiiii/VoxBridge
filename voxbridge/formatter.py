"""Text formatting using local LLM via Ollama."""

import os
import shutil
import subprocess
import threading


class Formatter:
    """Formats transcribed text using a local LLM (Ollama)."""

    def __init__(self, config: dict):
        self.model = config.get("model", "qwen3:8b")
        self.timeout = config.get("timeout", 30)
        self._bundled_prompt_path = config.get("prompt_file", "")
        self._prompt_template = self._load_prompt(self._bundled_prompt_path)
        self._user_prompt_path = None  # Set by ensure_user_prompt()
        self._client = None

        # Translation prompt paths (resolved in _load_prompt)
        self._translate_prompts = {}
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for key, filename in [("ja_en", "translate_ja_en.txt"), ("en_ja", "translate_en_ja.txt")]:
            path = os.path.join(project_root, "prompts", filename)
            if os.path.exists(path):
                self._translate_prompts[key] = self._load_prompt(path)

    def _get_client(self):
        """Get or create an Ollama client with timeout."""
        if self._client is None:
            import ollama
            self._client = ollama.Client(timeout=self.timeout)
        return self._client

    def _fetch_tags(self) -> list | None:
        """Fetch model list from Ollama. Returns None if unreachable."""
        try:
            import httpx
            r = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
            if r.status_code == 200:
                return r.json().get("models", [])
        except Exception:
            pass
        return None

    def is_available(self) -> bool:
        """Check if Ollama server is reachable."""
        return self._fetch_tags() is not None

    def is_model_available(self) -> bool:
        """Check if the configured model is downloaded in Ollama."""
        models = self._fetch_tags()
        if models is None:
            return False
        return self._has_model(models)

    def check_status(self) -> tuple[bool, bool]:
        """Check Ollama and model availability in a single call.

        Returns:
            (ollama_available, model_available)
        """
        tags = self._fetch_tags()
        ollama_ok = tags is not None
        model_ok = ollama_ok and self._has_model(tags)
        return ollama_ok, model_ok

    def _has_model(self, models: list) -> bool:
        """Check if the configured model exists in the model list."""
        return any(
            m.get("name", "") == self.model
            or m.get("name", "").startswith(self.model + "-")
            for m in models
        )

    def _load_prompt(self, path: str) -> str:
        """Load the formatting prompt template."""
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        # Fallback inline prompt
        return (
            "音声認識テキストを自然な書き言葉に整形してください。"
            "フィラーを除去し、句読点を追加してください。"
            "整形結果のみを出力してください。\n\n"
            "入力テキスト:\n{text}"
        )

    def ensure_user_prompt(self, user_prompt_path: str) -> str:
        """Ensure user prompt file exists; copy bundled template if not.

        Returns the path to the user prompt file. Subsequent format() calls
        will always re-read from this file so edits take effect immediately.
        """
        if not os.path.exists(user_prompt_path):
            os.makedirs(os.path.dirname(user_prompt_path), exist_ok=True)
            if self._bundled_prompt_path and os.path.exists(self._bundled_prompt_path):
                shutil.copy2(self._bundled_prompt_path, user_prompt_path)
            else:
                with open(user_prompt_path, "w", encoding="utf-8") as f:
                    f.write(self._prompt_template)
        self._user_prompt_path = user_prompt_path
        return user_prompt_path

    def format(self, text: str, mode: str = "format") -> str:
        """Format or translate transcribed text using the local LLM.

        Args:
            text: Transcribed text to process.
            mode: "format", "translate_ja_en", or "translate_en_ja".

        Falls back to raw text if Ollama is unavailable.
        """
        if not text.strip():
            return text

        try:
            if mode in ("translate_ja_en", "translate_en_ja"):
                key = mode.replace("translate_", "")
                template = self._translate_prompts.get(key, self._prompt_template)
            elif self._user_prompt_path:
                template = self._load_prompt(self._user_prompt_path)
            else:
                template = self._prompt_template
            prompt = template.replace("{text}", text)
            client = self._get_client()

            response = client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.3, "num_predict": 1024},
            )

            result = response["message"]["content"].strip()
            return result if result else text

        except ImportError:
            print("[Formatter] ollama package not installed, skipping formatting")
            return text
        except Exception as e:
            print(f"[Formatter] Ollama error (using raw text): {e}")
            return text

    @staticmethod
    def _find_ollama_bin() -> str:
        """Find the ollama binary in common install locations."""
        for path in ("/opt/homebrew/bin/ollama", "/usr/local/bin/ollama"):
            if os.path.isfile(path):
                return path
        return "ollama"  # fallback to PATH lookup by subprocess

    def pull_model(self, model_name: str | None = None,
                   on_progress=None, on_complete=None, on_error=None) -> None:
        """Pull an Ollama model in a background thread.

        Args:
            model_name: Model to pull (defaults to self.model).
            on_progress: Callback(status_str) called with progress text.
            on_complete: Callback() called when pull finishes successfully.
            on_error: Callback(error_str) called on failure.
        """
        if model_name is None:
            model_name = self.model

        ollama_bin = shutil.which("ollama") or self._find_ollama_bin()


        def _run():
            try:
                proc = subprocess.Popen(
                    [ollama_bin, "pull", model_name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                for line in proc.stdout:
                    line = line.strip()
                    if line and on_progress:
                        on_progress(line)
                proc.wait()
                if proc.returncode == 0:
                    if on_complete:
                        on_complete()
                else:
                    if on_error:
                        on_error(f"ollama pull exited with code {proc.returncode}")
            except Exception as e:
                if on_error:
                    on_error(str(e))

        threading.Thread(target=_run, daemon=True).start()
