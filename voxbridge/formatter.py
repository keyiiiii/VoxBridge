"""Text formatting using local LLM via Ollama."""

import os


class Formatter:
    """Formats transcribed text using a local LLM (Ollama)."""

    def __init__(self, config: dict):
        self.model = config.get("model", "qwen2.5:7b")
        self.timeout = config.get("timeout", 30)
        self._prompt_template = self._load_prompt(config.get("prompt_file", ""))

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

    def format(self, text: str) -> str:
        """Format transcribed text using the local LLM.

        Falls back to raw text if Ollama is unavailable.
        """
        if not text.strip():
            return text

        try:
            import ollama

            prompt = self._prompt_template.replace("{text}", text)

            response = ollama.chat(
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
