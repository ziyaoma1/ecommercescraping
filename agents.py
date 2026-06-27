import json
import re
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from dataclasses import asdict

from models import ProductRecord


class PageClassifierAgent:
    """Responsible for determining the routing logic based on a URL's structure."""

    def classify(self, url):
        """
        Evaluates a URL to determine its page type.

        Args:
            url (str): The web address to classify.

        Returns:
            str: 'product' if it is a detail page, otherwise 'category'.
        """
        if '/product/' in url: return 'product'
        return 'category'


class ExtractorAgent:
    """Responsible for parsing HTML and extracting structured product data."""

    def extract_list_page(self, html, base_url):
        """
        Parses a category page to harvest product links, basic metadata, and pagination.

        Args:
            html (str): The raw rendered HTML of the category page.
            base_url (str): The root domain used to resolve relative links.

        Returns:
            tuple: A dictionary of partial product records keyed by URL, and the next page URL (if any).
        """
        soup = BeautifulSoup(html, 'html.parser')
        partial_records = {}

        for hit in soup.select('.ais-Hits-item'):
            mfg_node = hit.select_one('.product-manufacturer')
            manufacturer = mfg_node.get_text(strip=True) if mfg_node else None

            name_node = hit.select_one('.product-name')
            product_name = name_node.get_text(strip=True) if name_node else None

            img_node = hit.select_one('img')
            image_url = img_node['src'] if img_node and img_node.get('src') else None

            link_node = hit.select_one(r'.h-full-result a[href], .h-full\.result a[href], [class*="h-full"] a[href]')
            if not link_node:
                link_node = hit.select_one('a[href]')
            if not link_node: continue
            product_url = urljoin(base_url, link_node['href'])

            partial_records[product_url] = {
                'manufacturer': manufacturer,
                'product_name': product_name,
                'image_url': image_url,
                'product_url': product_url
            }

        next_page = None
        for a in soup.select('.ais-Pagination-item--next a[href], a[aria-label*="Next"]'):
            href = a.get('href', '').strip()
            if href:
                next_page = urljoin(base_url, href)
                break

        return partial_records, next_page

    def extract_product_page(self, url, html, partial_data):
        """
        Parses a deep product page, intercepting the masterData blob for strict variation accuracy.

        Args:
            url (str): The product's URL.
            html (str): The raw rendered HTML of the product page.
            partial_data (dict): Metadata previously collected from the category page.

        Returns:
            list[ProductRecord]: A single-item list containing the populated parent record.
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Grab Hierarchy
        crumbs = [n.get_text(" ", strip=True) for n in
                  soup.select("nav.breadcrumb a, .breadcrumbs a, [aria-label='breadcrumb'] a") if
                  n.get_text(" ", strip=True)]
        if crumbs: crumbs = crumbs[1:]

        # Grab Single Image
        image_url = partial_data.get('image_url')
        if not image_url:
            for img in soup.select('.gallery img, .product-image img, #main-image, img.product-image-photo'):
                if img.get('src') and not img['src'].endswith('.gif'):
                    image_url = img['src']
                    break

        # Clean description
        desc_node = soup.select_one('section#description')
        if desc_node:
            description = desc_node.get_text(' ', strip=True)
            description = re.sub(r'\s+', ' ', description).strip()
            if description.lower().startswith('description'):
                description = description[len('description'):].strip()
        else:
            description = None

        # Grab Variations purely from the masterData blob
        blob_records = {}
        fallback_name = None
        m = re.search(r'window\.masterData\s*=\s*"(.*?)"\s*;', html, re.S)
        if m:
            try:
                escaped_string = m.group(1).replace('\\/', '/')
                decoded = escaped_string.encode('utf-8', 'ignore').decode('unicode_escape')
                master_json = json.loads(decoded)

                for sku_key, var_data in master_json.items():
                    if not fallback_name and var_data.get('name'):
                        fallback_name = var_data.get('name')

                    raw_prices = []
                    base_price = var_data.get('product_price')
                    if base_price:
                        raw_prices.append({"price": f"{float(base_price):.2f}", "quantity": "1"})

                    tier_prices = var_data.get('tier_price', {})
                    if isinstance(tier_prices, dict):
                        for tier_data in tier_prices.values():
                            if isinstance(tier_data, dict) and tier_data.get('price') and tier_data.get('price_qty'):
                                clean_qty = str(int(float(tier_data['price_qty'])))
                                clean_price = f"{float(tier_data['price']):.2f}"
                                combo = {"price": clean_price, "quantity": clean_qty}
                                if combo not in raw_prices:
                                    raw_prices.append(combo)

                    final_price_variations = sorted(raw_prices, key=lambda x: int(x['quantity']))

                    avail = var_data.get('stock_availability_label', '')
                    if avail: avail = re.sub(r'\s+', '-', avail).lower()

                    actual_sku = str(var_data.get('sku', sku_key)).strip()
                    blob_records[actual_sku] = {
                        "item_number": actual_sku,
                        "availability": avail,
                        "specifications": var_data.get('description', ''),
                        "price_variations": final_price_variations
                    }
            except Exception as e:
                print(f"   -> Failed to decode masterData blob: {e}")

        parent_record = ProductRecord(
            product_name=partial_data.get('product_name') or fallback_name,
            manufacturer=partial_data.get('manufacturer'),
            product_url=url,
            category_hierarchy=crumbs,
            image_url=image_url,
            description=description,
            variations=list(blob_records.values())
        )
        return [parent_record]


class ValidatorAgent:
    """Enforces data quality rules on extracted records before final storage."""

    def validate(self, record: ProductRecord) -> bool:
        """
        Checks a single ProductRecord against required fields.

        Args:
            record (ProductRecord): The record to inspect.

        Returns:
            bool: True if the record is valid, False otherwise.
        """
        if not record.product_url or not record.product_url.startswith('http'):
            print(f"   [!] VALIDATION FAILED: Invalid or missing URL.")
            return False

        if not record.product_name or not record.product_name.strip():
            print(f"   [!] VALIDATION FAILED: Missing product name for {record.product_url}")
            return False

        if not record.variations or len(record.variations) == 0:
            print(f"   [!] VALIDATION FAILED: No variations/SKUs found for {record.product_url}")
            return False

        for var in record.variations:
            if not var.get('item_number') or str(var.get('item_number')).strip() == "":
                print(f"   [!] VALIDATION FAILED: A variation is missing an item_number for {record.product_url}")
                return False

        return True

    def filter_valid(self, records: list[ProductRecord]) -> list[ProductRecord]:
        """
        Filters a list of records, returning only those that pass validation.

        Args:
            records (list[ProductRecord]): A list of unvalidated records.

        Returns:
            list[ProductRecord]: A list containing only valid records.
        """
        return [r for r in records if self.validate(r)]


class StorageAgent:
    """Handles the final deduplication and JSON serialization of validated records."""

    def __init__(self, out):
        """
        Initializes the storage agent and creates output directories.

        Args:
            out (str | Path): The directory path for final output.
        """
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)

    def persist(self, records):
        """
        Deduplicates parent records by URL and saves them to a JSON file.

        Args:
            records (list[ProductRecord]): The valid records to save.
        """
        deduped = {r.product_url: r for r in records}
        rows = [asdict(r) for r in deduped.values()]
        (self.out / 'products.json').write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf-8')