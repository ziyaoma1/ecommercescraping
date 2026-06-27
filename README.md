# Safco Dental Agent-Based Scraper Prototype

This repository contains a Python-based web scraping prototype. It is designed to navigate Safco Dental's dynamic, JavaScript-heavy catalog, extract complex parent-child product relationships, and output clean, validated, hierarchical JSON.

## Architecture Overview

This project uses a modular, **agent-based architecture** written in Python. It strictly separates concerns into distinct files to ensure maintainability and testability:
* `main.py` - The orchestrator that manages the BFS queue and execution loop.
* `models.py` - Data structures.
* `agents.py` - The "thinkers" (Classification, Extraction, Validation, Storage).
* `utils.py` - Infrastructure (Playwright browser context and State Checkpointing).

The core crawler operates on a Breadth-First Search (BFS) queue. It initializes from seed category URLs, dynamically executes JavaScript using a stateful browser context, identifies pagination/product links, and funnels raw HTML to an extraction pipeline. 

## Why I Chose This Approach

1. **Playwright over Requests/BeautifulSoup alone:** Safco Dental relies heavily on Algolia InstantSearch and Alpine.js. Category pages and product details are injected client-side. A standard HTTP client would only capture skeleton templates. Playwright ensures the DOM is fully rendered before extraction begins.
2. **Deeply Nested JSON over Flat CSV:** Dental supplies often have complex parent-child structures. Storing this in a flat CSV forces either massive column bloat or redundant parent rows. A nested JSON structure natively supports these hierarchical variations and deduplicates parent data.
3. **Regex Intercept over DOM parsing:** Instead of struggling with Alpine.js state timing in the DOM, the `ExtractorAgent` intercepts the raw `window.masterData` JSON blob directly from the `<script>` tags, ensuring 100% accurate extraction of all SKUs, specs, and complex tier-pricing without relying on brittle CSS selectors.
4. **Agent Separation:** By separating extraction from network requests, the extraction logic becomes easily unit-testable without requiring live network calls.

## Agent Responsibilities

* **`PlaywrightClient` (Navigator):** Manages the headless browser lifecycle. Handles exponential backoff retries, request timeouts, and waits for specific Algolia/Alpine.js DOM elements to render before returning HTML.
* **`PageClassifierAgent`:** Inspects URLs to route the crawler logic. Determines if a page requires category pagination logic or deep product extraction.
* **`ExtractorAgent`:** Parses raw HTML. Harvests product links and pagination. On product pages, it cleans descriptions, extracts breadcrumbs/images, and decodes the `masterData` blob to group all SKUs and their respective `price_variations` (base and tier pricing) under a single parent record.
* **`ValidatorAgent`:** Acts as a strict quality control gate. Runs post-crawl to ensure all records possess valid URLs, names, and at least one properly formatted SKU variation.
* **`StorageAgent`:** Enforces exact-match deduplication by URL and serializes the validated Python models into a clean, nested `products.json` file.
* **`CheckpointManager`:** Maintains crawler state (visited URLs, queue, and pending data) to allow for safe resumability if the script is interrupted.

## Setup & Execution Instructions

### Prerequisites
* Python 3.10+
* Playwright

### Installation
1. Clone the repository and ensure all 4 Python files (`main.py`, `models.py`, `utils.py`, `agents.py`) are in the same folder.
2. Install the required dependencies:
   ```bash
   pip install playwright beautifulsoup4
   playwright install chromium
   ```
3. Ensure `config.json` is present in the root directory and contains your target seeds and `max_pages` limit.

### Execution
Run the orchestrator script:
```bash
python main.py --config config.json
```
The scraper will output its progress to the console, save intermediate states to `data/checkpoint.json`, and output the final validated file to `output/products.json`.

## Sample Output Schema

The scraper outputs a hierarchical JSON array. Top-level attributes define the parent product, the `variations` array holds specific SKUs, and the `price_variations` array strictly maps price to quantity.

```json
[
  {
    "product_name": "Surgifoam",
    "manufacturer": "Ethicon",
    "product_url": "https://www.safcodental.com/product/surgifoam-reg",
    "category_hierarchy": [
      "Home",
      "Dental Supplies",
      "Sutures & surgical products",
      "Surgical medicaments and packing"
    ],
    "image_urls": [
      "https://www.safcodental.com/media/catalog/product/p/f/pfpjk.jpg?width=265&height=265&canvas=265,265&optimize=medium&fit=bounds"
    ],
    "description": "Sterile, water insoluble, malleable porcine gelatin absorbable sponge, intended for hemostatic use by applying to a bleeding surface. Use in oral surgery for the obliteration of dead space created by simple extraction, root amputation and removal of cysts, tumors and impacted teeth. Rapid hemostasis. Easy to handle: compressible, does not require any cutting. Absorbs up to 40 times its own weight. Bioresorbable. The sponge is porous and off-white in appearance.",
    "variations": [
      {
        "item_number": "2580512",
        "availability": "in-stock",
        "specifications": "2cm x 6cm x 0.7cm, 12/box",
        "price_variations": [
          {
            "price": "214.49",
            "quantity": "1"
          },
          {
            "price": "210.49",
            "quantity": "3"
          },
          {
            "price": "206.49",
            "quantity": "6"
          }
        ]
      },
      {
        "item_number": "2580524",
        "availability": "in-stock",
        "specifications": "1cm x 1cm x 1cm, 24/box",
        "price_variations": [
          {
            "price": "251.99",
            "quantity": "1"
          },
          {
            "price": "247.49",
            "quantity": "3"
          },
          {
            "price": "242.99",
            "quantity": "6"
          }
        ]
      }
    ]
  }
]
```

## Limitations
* **Compute Overhead:** Playwright is resource-intensive. Running this linearly on a single thread is bottlenecked by DOM rendering times.
* **IP Blocking:** The current prototype uses a simple exponential backoff. It does not implement proxy rotation or complex fingerprinting, meaning a full-site crawl from a single residential IP would likely be rate-limited eventually.
* **Alternative products and unit / pack size extraction:** I did not extract alternative products since there were no alternative products on the Product Page. I also chose not to extract Unit Type/ Pack Size as I believe that it is similar to specifications. It could be a good use of LLMs to find alternative products and decide whether something belongs in specifications or unit/pack sizes, but I do not have access to a free source of tokens at the moment, so I refrained from implementing such features.


## Failure Handling
* **Network Level:** The `PlaywrightClient` will retry after a network timeout, the number of attempts can be modified in config.json.
* **Process Level:** The `CheckpointManager` saves current progress to a json file.
  
## Scaling to Full-Site Crawling in Production
To scale this to crawl the entire Safco catalog reliably:
1. **Distributed Queues:** Replace the in-memory `deque` with a distributed message broker like RabbitMQ, Kafka, or Redis/Celery.
2. **Concurrency:** Deploy multiple containerized worker nodes running the `PlaywrightClient` and `ExtractorAgent` in parallel, pulling from the centralized queue.
3. **Proxy Rotation:** Integrate a proxy mesh (e.g., BrightData or Smartproxy) at the Playwright context level to distribute requests across thousands of IPs to avoid bot-mitigation bans.
4. **Streaming Storage:** Transition from holding records in memory to streaming JSONL directly to an S3 bucket or streaming inserts into a PostgreSQL database.

## Monitoring Data Quality
In a production environment, data quality must be monitored continuously:
1. **Schema Validation:** Expand the `ValidatorAgent` to use strict tools like `Pydantic`. Drop records that fail schema checks into a separate dead-letter queue (e.g., `invalid.jsonl`) for human review.
2. **Anomaly Detection Alerts:** Monitor aggregate metrics per run. If the total item count drops by >5%, or if the `null` rate for the `price` field suddenly spikes, trigger an automated alert. This usually indicates the target site deployed a UI change.
3. **Price Delta Checks:** Compare newly scraped prices against the previous database state. Flag any price variations greater than 50% as potential extraction errors before updating downstream systems.
