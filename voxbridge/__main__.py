"""Entry point for `python -m voxbridge`."""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        description="VoxBridge - Local voice input for macOS"
    )
    parser.add_argument(
        "-c", "--config",
        default=None,
        help="Path to config.yaml (default: ./config.yaml)",
    )
    parser.add_argument(
        "--preload",
        action="store_true",
        help="Pre-load STT model on startup (slower start, faster first use)",
    )
    args = parser.parse_args()

    from .app import VoxBridgeApp

    app = VoxBridgeApp(config_path=args.config)

    if args.preload:
        print("[VoxBridge] Pre-loading STT model...")
        app.stt.preload()

    app.run()


if __name__ == "__main__":
    main()
