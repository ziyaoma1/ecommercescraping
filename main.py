import argparse
import json
from collections import deque
from pathlib import Path
from dataclasses import asdict

from models import ProductRecord
from utils import PlaywrightClient, CheckpointManager
from agents import PageClassifierAgent, ExtractorAgent, ValidatorAgent, StorageAgent


def crawl(cfg):
    """
    The main orchestrator loop. Implements Breadth-First Search (BFS) to traverse
    the target site based on configuration parameters, dispatching work to the respective agents.

    Args:
        cfg (dict): The configuration dictionary loaded from JSON.
    """
    root = Path(__file__).resolve().parent
    ck = CheckpointManager(root / cfg['checkpoint_file'])
    saved = ck.load()

    visited = set(saved['visited'])
    q = deque(saved['queue'])
    records = [ProductRecord(**r) for r in saved['products']]
    pending_products = saved.get('pending_products', {})

    if not q:
        for u in cfg['category_seeds']: q.append(u)

    client = PlaywrightClient(cfg)
    classifier = PageClassifierAgent()
    ext = ExtractorAgent()

    try:
        while q and len(visited) < cfg['max_pages']:
            url = q.popleft()
            if url in visited: continue

            page_type = classifier.classify(url)
            print(f"Scraping [{page_type.upper()}] ({len(visited)}/{cfg['max_pages']}): {url}")

            html = client.get(url, is_category=(page_type == 'category'))
            visited.add(url)

            if not html:
                ck.save(visited, q, [asdict(r) for r in records], pending_products)
                continue

            if page_type == 'category':
                partial_recs, next_page = ext.extract_list_page(html, cfg['base_url'])
                for p_url, p_data in partial_recs.items():
                    pending_products[p_url] = p_data
                    if p_url not in visited and p_url not in q:
                        q.append(p_url)

                if next_page and next_page not in visited and next_page not in q:
                    q.append(next_page)

            elif page_type == 'product':
                partial_data = pending_products.pop(url, {})
                try:
                    records.extend(ext.extract_product_page(url, html, partial_data))
                except Exception as e:
                    print(f"Failed extracting {url}: {e}")

            ck.save(visited, q, [asdict(r) for r in records], pending_products)
    finally:
        client.close()

    print("\nRunning post-crawl validation...")
    validator = ValidatorAgent()
    clean_records = validator.filter_valid(records)
    print(f"Validation complete: {len(clean_records)} valid records out of {len(records)}.")

    StorageAgent(root / cfg['output_dir']).persist(clean_records)
    print(
        f"Finished writing to JSON. Total distinct valid master products: {len(set(r.product_url for r in clean_records))}")


def main():
    """CLI entry point. Parses command-line arguments and initiates the crawl process."""
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='config.json')
    args = ap.parse_args()
    crawl(json.loads(Path(args.config).read_text(encoding='utf-8')))


if __name__ == '__main__':
    main()