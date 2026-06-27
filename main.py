import argparse
import json
from pathlib import Path

from agents import NavigatorAgent


def main():
    """CLI entry point. Parses command-line arguments and initiates the crawl process."""
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='config.json')
    args = ap.parse_args()
    nav = NavigatorAgent(json.loads(Path(args.config).read_text(encoding='utf-8')))
    nav.crawl()


if __name__ == '__main__':
    main()