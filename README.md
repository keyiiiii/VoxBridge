# VoxBridge

macOS 向け完全ローカル音声入力ツール。ホットキーで話すだけで、文字起こし・整形されたテキストがアクティブなアプリに入力される。ネットワーク通信なし。

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  VoxBridge (Python + PyObjC)                            │
│                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐          │
│  │  Hotkey   │───>│ Recorder │───>│   STT    │          │
│  │ (pynput)  │    │(sound-   │    │(faster-  │          │
│  │ push-to-  │    │ device)  │    │ whisper) │          │
│  │ talk      │    │ 16kHz    │    │ small/   │          │
│  └──────────┘    │ mono     │    │ medium   │          │
│                   └──────────┘    └────┬─────┘          │
│                                        │ text           │
│  ┌──────────┐    ┌──────────┐    ┌────▼─────┐          │
│  │ Overlay  │    │ Injector │<───│Formatter │          │
│  │ (PyObjC  │    │(Clipboard│    │(Ollama   │          │
│  │  NSPanel)│    │ +Cmd+V + │    │ local    │          │
│  │ 状態表示  │    │ CGEvent) │    │ LLM)     │          │
│  └──────────┘    └──────────┘    └──────────┘          │
│                        │                                │
│                   ┌────▼────┐                           │
│                   │ Active  │                           │
│                   │  App    │                           │
│                   │(+Enter  │                           │
│                   │ if term)│                           │
│                   └─────────┘                           │
└─────────────────────────────────────────────────────────┘
```

## Requirements

- macOS 14+ (Apple Silicon / M4 Max)
- Python 3.11+
- [Ollama](https://ollama.com/) (ローカル LLM サーバー)

## Setup

### 1. Ollama のインストールと準備

```bash
# Ollama をインストール (まだの場合)
brew install ollama

# Ollama サーバーを起動
ollama serve &

# テキスト整形用モデルをダウンロード
ollama pull qwen2.5:7b
```

### 2. Python 環境のセットアップ

```bash
cd VoxBridge

# 仮想環境を作成
python3 -m venv .venv
source .venv/bin/activate

# 依存パッケージをインストール
pip install -r requirements.txt
```

### 3. STT モデルの事前ダウンロード (オフライン利用のため)

```bash
# 初回のみ: Whisper モデルをダウンロード (インターネット接続が必要)
python3 -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"
```

### 4. macOS 権限の設定

**システム設定 > プライバシーとセキュリティ** で以下を許可:

| 権限 | 対象 | 用途 |
|------|------|------|
| **マイク** | Terminal / iTerm2 / Python | 音声録音 |
| **アクセシビリティ** | Terminal / iTerm2 / Python | キーストローク注入 (Cmd+V, Enter) |
| **入力監視** | Terminal / iTerm2 / Python | グローバルホットキー監視 |

> Python を直接実行する場合は Python.app (`/path/to/.venv/bin/python3`) を追加する。

## Usage

### Mac アプリとして起動 (推奨)

```bash
# .app をビルド (初回のみ / コード変更後)
source .venv/bin/activate
python scripts/build_app.py

# 起動
open dist/VoxBridge.app

# /Applications にインストールしたい場合
python scripts/build_app.py --install
open /Applications/VoxBridge.app
```

- メニューバーに **VB** が表示されたら起動完了
- 終了はメニューバーの **VB** > **Quit VoxBridge**
- ログ: `~/Library/Logs/VoxBridge.log`

### CLI として起動

```bash
source .venv/bin/activate
python -m voxbridge

# STT モデルを事前ロード (起動は遅いが初回認識が速い)
python -m voxbridge --preload

# カスタム設定ファイル
python -m voxbridge -c /path/to/config.yaml
```

### 操作方法

1. **Right Option キー** (デフォルト) を **押し続ける** → 録音開始
2. キーを **離す** → 録音停止 → 文字起こし → 整形 → テキスト入力
3. Terminal で Claude Code 実行中なら、自動で Enter も送信

### バックグラウンド起動 (CLI)

```bash
nohup python -m voxbridge --preload > /tmp/voxbridge.log 2>&1 &
echo $! > /tmp/voxbridge.pid
```

停止:
```bash
kill $(cat /tmp/voxbridge.pid)
```

## Configuration

`config.yaml` を編集:

```yaml
# ホットキー変更 (pynput の Key 名)
hotkey: "alt_r"       # Right Option
# hotkey: "f5"        # F5 キー
# hotkey: "ctrl_r"    # Right Control

# 言語
language: "ja"

# STT モデル (大きいほど精度↑、速度↓)
stt:
  model: "small"       # tiny / base / small / medium / large-v3
  compute_type: "int8" # int8 / float16 / float32

# 整形 LLM
formatter:
  enabled: true        # false で整形をスキップ (STT 結果をそのまま入力)
  model: "qwen2.5:7b"  # Ollama モデル名
  prompt_file: "prompts/format.txt"

# Enter を送るアプリ
injector:
  send_enter_for:
    - "Terminal"
    - "iTerm2"
```

## Smoke Tests

```bash
# 基本テスト (設定読み込み + アプリ検出)
python -m tests.test_smoke

# 個別テスト
python -m tests.test_smoke config      # 設定のみ
python -m tests.test_smoke recorder    # マイク録音 (2秒)
python -m tests.test_smoke stt         # STT のみ
python -m tests.test_smoke formatter   # 整形のみ (Ollama 必要)
python -m tests.test_smoke injector    # アプリ検出のみ

# フルパイプライン (録音→STT→整形、注入はしない)
python -m tests.test_smoke full
```

## Troubleshooting

### ホットキーが反応しない

- **入力監視** 権限を確認 (システム設定 > プライバシーとセキュリティ > 入力監視)
- Terminal / Python を追加して再起動

### 録音できない / 音が取れない

- **マイク** 権限を確認
- `python -m tests.test_smoke recorder` でテスト
- `python3 -c "import sounddevice; print(sounddevice.query_devices())"` でデバイス確認

### テキストが入力されない

- **アクセシビリティ** 権限を確認
- Cmd+V のペーストが動作するか手動で確認

### Ollama エラー

```bash
# Ollama が起動しているか確認
curl -s http://localhost:11434/api/tags | python3 -m json.tool

# モデルがダウンロード済みか確認
ollama list

# モデルを再ダウンロード
ollama pull qwen2.5:7b
```

### STT モデルのダウンロードエラー

```bash
# モデルキャッシュを確認
ls ~/.cache/huggingface/hub/

# 手動で再ダウンロード
python3 -c "from faster_whisper import WhisperModel; WhisperModel('small')"
```

### 入力が遅い

- `stt.model` を `"tiny"` に変更 (精度は下がる)
- `formatter.enabled` を `false` に (整形をスキップ)
- `--preload` フラグで起動 (初回のモデルロード時間を排除)

## Project Structure

```
VoxBridge/
├── README.md
├── requirements.txt
├── config.yaml              # 設定ファイル
├── prompts/
│   └── format.txt           # 整形プロンプトテンプレート
├── voxbridge/
│   ├── __init__.py
│   ├── __main__.py          # エントリーポイント
│   ├── app.py               # メインアプリ (オーケストレーション)
│   ├── config.py            # 設定読み込み
│   ├── recorder.py          # 音声録音 (sounddevice)
│   ├── stt.py               # 音声認識 (faster-whisper)
│   ├── formatter.py         # テキスト整形 (Ollama)
│   ├── injector.py          # テキスト注入 (CGEvent)
│   └── overlay.py           # オーバーレイ UI (PyObjC)
└── tests/
    └── test_smoke.py        # スモークテスト
```

## Future Improvements

- **リアルタイム文字起こし**: 録音中にストリーミングで部分結果を表示
- **CoreML / MLX 対応**: Apple Neural Engine を活用した高速 STT
- **文脈推定**: Claude Code のチャット履歴を読み取り、文脈に合わせた整形
- **ノイズ抑制**: RNNoise / DeepFilterNet でマイク入力を前処理
- **ウェイクワード**: 「ヘイ、ブリッジ」等でハンズフリー起動
- **マルチ言語自動検出**: 日本語と英語の混在入力を自動判定
- **カスタムショートカット**: 複数のホットキーで異なるモード (コード指示 / 自然文 / 翻訳)
- **音声フィードバック**: 録音開始・完了時にサウンドで通知
- **LaunchAgent 登録**: macOS ログイン時に自動起動
- **Whisper.cpp + Metal**: faster-whisper の代わりに whisper.cpp の Metal バックエンドで GPU 活用
