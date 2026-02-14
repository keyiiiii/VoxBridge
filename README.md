# VoxBridge

macOS 向け完全ローカル音声入力ツール。ホットキーを押しながら話すだけで、文字起こし・整形されたテキストがアクティブなアプリに自動入力される。**音声データはすべてローカルで処理され、ネットワークに送信されない。**

## 特徴

- **完全ローカル処理** — 音声認識 (Whisper)・テキスト整形 (Ollama) ともにオンデバイス
- **自己完結型 .app** — Python.framework + 依存パッケージをすべて同梱。コピーするだけで動く
- **Push-to-talk** — 修飾キー (Option/Ctrl/Shift) を押している間だけ録音
- **どのアプリにも入力** — アクティブなアプリにクリップボード経由でペースト
- **ターミナル対応** — Terminal / iTerm2 等では自動で Enter も送信

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  VoxBridge.app (self-contained)                         │
│                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐          │
│  │  Hotkey   │───>│ Recorder │───>│   STT    │          │
│  │(NSEvent  │    │(sound-   │    │(faster-  │          │
│  │ global   │    │ device)  │    │ whisper) │          │
│  │ monitor) │    │ 16kHz    │    │ small    │          │
│  └──────────┘    │ mono     │    └────┬─────┘          │
│                   └──────────┘         │ text           │
│  ┌──────────┐    ┌──────────┐    ┌────▼─────┐          │
│  │ Overlay  │    │ Injector │<───│Formatter │          │
│  │(NSPanel  │    │(Clipboard│    │(Ollama   │          │
│  │ 状態表示) │    │ +Cmd+V + │    │ optional)│          │
│  └──────────┘    │ CGEvent) │    └──────────┘          │
│                   └────┬─────┘                          │
│                   ┌────▼────┐                           │
│                   │ Active  │                           │
│                   │  App    │                           │
│                   └─────────┘                           │
└─────────────────────────────────────────────────────────┘
```

## Requirements

- **macOS 14+** (Sonoma 以降、Apple Silicon 推奨)
- **Xcode Command Line Tools** (`xcode-select --install`)
- **Python 3.11+** (Homebrew: `brew install python`)

### Ollama (オプション)

[Ollama](https://ollama.com/) は音声認識結果のテキスト整形に使用するローカル LLM サーバー。**なくても動作する** (整形をスキップして STT の結果がそのまま入力される)。

```bash
# インストール
brew install ollama

# サーバー起動
ollama serve

# 整形用モデルをダウンロード (~4GB)
ollama pull qwen2.5:7b
```

Ollama がインストールされていない、またはサーバーが起動していない場合は、自動的に整形をスキップして音声認識の結果をそのまま入力する。`config.yaml` で `formatter.enabled: false` にすれば明示的に無効化もできる。

## macOS 権限

VoxBridge は以下の macOS 権限が必要。初回起動時にダイアログが表示される。

| 権限 | 必須 | 用途 | 未許可時の動作 |
|------|------|------|---------------|
| **マイク** | 必須 | 音声の録音 | 録音できない (アプリが動作しない) |
| **アクセシビリティ** | 推奨 | グローバルホットキー監視 + テキスト注入 (Cmd+V, Enter) | テキストがクリップボードにコピーされるが自動ペーストされない。手動で Cmd+V が必要 |

設定場所: **システム設定 > プライバシーとセキュリティ**

> **Note**: 以前のバージョンで必要だった「入力監視」権限は不要になった (pynput から NSEvent に移行したため)。

## Quick Start

### .app をビルドして起動 (推奨)

```bash
git clone https://github.com/keyiiiii/VoxBridge.git
cd VoxBridge

# .app をビルド (Python.framework + 依存パッケージを同梱、数分かかる)
python3 scripts/build_app.py

# 起動
open dist/VoxBridge.app
```

メニューバーに **VB** が表示されたら起動完了。

### /Applications にインストール

```bash
python3 scripts/build_app.py --install
open /Applications/VoxBridge.app
```

### CLI として起動 (開発用)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python -m voxbridge --preload
```

## Usage

1. **Right Option キー** (デフォルト) を **押し続ける** → 録音開始 (オーバーレイに "Recording..." 表示)
2. キーを **離す** → 録音停止 → 文字起こし → 整形 → アクティブなアプリにテキスト入力
3. Terminal / iTerm2 等のターミナルアプリでは、自動で Enter も送信

終了: メニューバーの **VB** > **Quit VoxBridge**

ログ: `~/Library/Logs/VoxBridge.log`

## .app の構成

ビルドされた `VoxBridge.app` は自己完結型 (~400MB)。他の Mac にコピーするだけで動作する。

```
VoxBridge.app/Contents/
├── MacOS/VoxBridge              # Mach-O ランチャー (相対パスで解決)
├── Frameworks/Python.framework/ # Python 本体
├── Resources/
│   ├── voxbridge/               # Python ソースコード
│   ├── config.yaml              # 設定ファイル
│   ├── prompts/                 # LLM プロンプト
│   └── venv/                    # Python 依存パッケージ
└── Info.plist
```

**同梱されるもの:**
- Python.framework (Python ランタイム)
- venv (faster-whisper, pyobjc, ollama 等の Python パッケージ)
- VoxBridge ソースコード、設定ファイル

**同梱されないもの (各 Mac で別途必要):**
- **Whisper モデル** — 初回起動時に `~/.cache/huggingface/` に自動ダウンロード (~500MB)
- **Ollama + LLM モデル** — テキスト整形を使う場合のみ (なくても動作する)

## Configuration

`config.yaml` を編集して設定を変更できる (.app の場合は `VoxBridge.app/Contents/Resources/config.yaml`)。

```yaml
# ホットキー (修飾キー名)
hotkey: "alt_r"       # Right Option (デフォルト)
# hotkey: "alt_l"     # Left Option
# hotkey: "ctrl_r"    # Right Control
# hotkey: "shift_r"   # Right Shift

# 音声認識の言語
language: "ja"

# STT モデル (大きいほど精度↑、速度↓)
stt:
  model: "small"       # tiny / base / small / medium / large-v3
  compute_type: "int8" # int8 / float16 / float32

# テキスト整形 (Ollama)
formatter:
  enabled: true        # false で整形をスキップ
  model: "qwen2.5:7b"  # Ollama モデル名

# Enter を送るアプリ
injector:
  send_enter_for:
    - "Terminal"
    - "iTerm2"
    - "Alacritty"
    - "kitty"
    - "Warp"
```

## Troubleshooting

### ホットキーが反応しない

- **アクセシビリティ** 権限を確認 (システム設定 > プライバシーとセキュリティ > アクセシビリティ)
- VoxBridge.app を追加して再起動

### 録音できない

- **マイク** 権限を確認 (システム設定 > プライバシーとセキュリティ > マイク)
- マイクデバイスの確認: `python3 -c "import sounddevice; print(sounddevice.query_devices())"`

### テキストが自動入力されない

- **アクセシビリティ** 権限を確認
- 権限がない場合、テキストはクリップボードにコピーされるので手動で Cmd+V でペースト可能
- オーバーレイに "Copied (要 Accessibility 許可)" と表示される場合は権限が未付与

### Ollama 関連

```bash
# Ollama が起動しているか確認
curl -s http://localhost:11434/api/tags | python3 -m json.tool

# モデルがダウンロード済みか確認
ollama list

# モデルを再ダウンロード
ollama pull qwen2.5:7b
```

Ollama が利用できない場合は自動的に整形をスキップするため、エラーにはならない。

### 入力が遅い

- STT モデルを `"tiny"` に変更 (精度は下がる)
- `formatter.enabled` を `false` に (整形をスキップ)
- .app の場合は `--preload` が自動で有効 (初回のモデルロード時間を排除)

### Whisper モデルのダウンロード

初回起動時に自動ダウンロードされる。手動で事前ダウンロードする場合:

```bash
python3 -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"
```

## Project Structure

```
VoxBridge/
├── README.md
├── requirements.txt
├── config.yaml                 # 設定ファイル
├── prompts/
│   └── format.txt              # 整形プロンプトテンプレート
├── scripts/
│   ├── build_app.py            # .app ビルドスクリプト
│   └── launch.sh               # CLI 起動ヘルパー
├── voxbridge/
│   ├── __init__.py
│   ├── __main__.py             # エントリーポイント
│   ├── app.py                  # メインアプリ (NSEvent + AppDelegate)
│   ├── config.py               # 設定読み込み
│   ├── recorder.py             # 音声録音 (sounddevice)
│   ├── stt.py                  # 音声認識 (faster-whisper)
│   ├── formatter.py            # テキスト整形 (Ollama, オプション)
│   ├── injector.py             # テキスト注入 (CGEvent + Clipboard)
│   └── overlay.py              # オーバーレイ UI + メニューバー (PyObjC)
└── tests/
    └── test_smoke.py           # スモークテスト
```

## License

MIT
