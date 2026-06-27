from dataclasses import dataclass

@dataclass
class ProductRecord:
    """
    Represents a complete, hierarchical product record extracted from the catalog.
    Stores parent-level product details and a nested list of SKU variations.
    """
    product_name: str | None
    manufacturer: str | None
    product_url: str
    category_hierarchy: list[str]
    image_url: str | None
    description: str | None
    variations: list[dict]