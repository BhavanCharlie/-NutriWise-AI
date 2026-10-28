"""Command-line entry point.

    python main.py                 # http://127.0.0.1:7860
    python main.py --port 8000 --open
    python main.py --share         # temporary public link (anyone with it can use your API keys!)
"""

import argparse
import logging

from app.ui import launch


def main():
    parser = argparse.ArgumentParser(description="Run the NutriWise AI calorie tracker.")
    parser.add_argument("--port", type=int, default=7860, help="port to serve on (default 7860)")
    parser.add_argument("--share", action="store_true", help="create a temporary public Gradio link")
    parser.add_argument("--open", action="store_true", help="open the app in your browser")
    parser.add_argument("--debug", action="store_true", help="show detailed logs")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpx2", "httpcore", "google_genai", "urllib3", "gradio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    launch(share=args.share, port=args.port, open_browser=args.open)


if __name__ == "__main__":  # only runs when executed directly, not when imported
    main()
