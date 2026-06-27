import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright


class PlaywrightClient:
    """Manages the lifecycle and execution of a headless Chromium browser."""

    def __init__(self, cfg):
        """Initializes the Playwright environment and browser context using config settings."""
        self.cfg = cfg
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True)
        self.context = self.browser.new_context(user_agent=cfg.get('user_agent'))

    def get(self, url, is_category=False):
        """
        Navigates to a URL and returns the fully rendered HTML.
        Implements exponential backoff for retries and waits for specific JS elements.

        Args:
            url (str): The target webpage URL.
            is_category (bool): Adjusts the DOM wait selectors based on page type.

        Returns:
            str | None: The rendered HTML string, or None if all retries fail.
        """
        for attempt in range(self.cfg['max_retries']):
            page = self.context.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=self.cfg['request_timeout_seconds'] * 1000)
                if is_category:
                    try:
                        page.wait_for_selector('.ais-Hits-item', timeout=30000)
                        page.wait_for_selector('.ais-Pagination-list', timeout=30000)
                        page.wait_for_timeout(500)
                    except Exception:
                        pass
                else:
                    try:
                        page.wait_for_selector('.product-item-sku, section#product-grouped-info', timeout=30000)
                        page.wait_for_timeout(30000)
                    except Exception:
                        pass
                html = page.content()
                page.close()
                return html
            except Exception as e:
                print(f"Playwright error on {url}: {e}")
                page.close()
                time.sleep(2 ** attempt)
        return None

    def close(self):
        """Safely shuts down the browser and stops Playwright."""
        self.browser.close()
        self.playwright.stop()


class CheckpointManager:
    """Handles saving and loading the crawler's state to disk for resumability."""

    def __init__(self, p):
        """
        Initializes the manager with a file path.

        Args:
            p (str | Path): Path to the checkpoint JSON file.
        """
        self.p = Path(p)
        self.p.parent.mkdir(parents=True, exist_ok=True)

    def load(self):
        """
        Loads the crawler state from disk.

        Returns:
            dict: The saved state containing visited URLs, the queue, and extracted data.
        """
        return json.loads(self.p.read_text(encoding='utf-8')) if self.p.exists() else {'visited': [], 'queue': [],
                                                                                       'products': [],
                                                                                       'pending_products': {}}

    def save(self, visited, queue, products, pending_products):
        """
        Serializes and writes the current crawler state to disk.

        Args:
            visited (set): URLs already scraped.
            queue (deque): URLs waiting to be scraped.
            products (list): Extracted product dictionaries.
            pending_products (dict): Partial product data waiting for deep extraction.
        """
        self.p.write_text(json.dumps({
            'visited': sorted(visited),
            'queue': list(queue),
            'products': products,
            'pending_products': pending_products
        }, indent=2), encoding='utf-8')
