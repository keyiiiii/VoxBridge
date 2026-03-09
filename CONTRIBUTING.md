# Contributing to VoxBridge

Thank you for your interest in contributing to VoxBridge!

## Getting Started

1. Fork and clone the repository
2. Set up the development environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Run smoke tests to verify your setup:
   ```bash
   python -m tests.test_smoke
   ```

## Development

### Running Locally

```bash
python -m voxbridge --preload
```

### Building the .app

```bash
python3 scripts/build_app.py
open dist/VoxBridge.app
```

### Running Tests

```bash
python -m tests.test_smoke              # Quick tests (config + injector)
python -m tests.test_smoke config       # Specific test
python -m tests.test_smoke full         # Full pipeline (requires microphone)
```

## Pull Request Guidelines

- Create a feature branch from `main`
- Keep changes focused — one feature or fix per PR
- Run smoke tests before submitting
- Update README.md / README.ja.md if your change affects user-facing behavior

## Reporting Issues

- Use [GitHub Issues](https://github.com/keyiiiii/VoxBridge/issues)
- Include your macOS version and Apple Silicon / Intel
- Attach relevant logs from `~/Library/Logs/VoxBridge.log`

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
