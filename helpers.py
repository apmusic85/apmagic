import json

GROUPS = [
    "All", "Tees/T-shirts", "Hats", "shoes - men", 
    "Framed Art Prints", "Backpack(s)", "Custom", 
    "shoes - women", "Fanny", "other"
]

KEYWORD_GROUPS = {
    "Tees/T-shirts": ["Tees/T-shirts"],
    "Hats": ["Hats"],
    "shoes - men": ["shoes - men"],
    "Framed Art Prints": ["Framed Art Prints"],
    "Backpack(s)": ["Backpack(s)"],
    "Custom": ["Custom"],
    "shoes - women": ["shoes - women"],
    "Fanny": ["Fanny"],
}

ORDERED_COLUMNS = [
    "listing_id", "state", "shop_section_id", "title", "price", 
    "quantity", "sku", "description", "tags", "materials", 
    "style", "shipping_profile_id", "return_policy_id", 
    "processing_min", "processing_max", "taxonomy_id", 
    "who_made", "when_made", "is_supply", "item_length", 
    "item_width", "item_height", "item_dimensions_unit", 
    "item_weight", "item_weight_unit", "is_customizable", 
    "is_personalizable", "is_private", "non_taxable", 
    "is_taxable", "listing_type", "should_auto_renew"
]

def assign_group(listing: dict) -> str:
    skus_raw = listing.get("skus", [])
    skus_str = [str(s) for s in skus_raw] if isinstance(skus_raw, list) else []
    blob = (
        (listing.get("title") or "") + " " + 
        (listing.get("description") or "") + " " + 
        " ".join(listing.get("tags") or []) + " " + 
        " ".join(skus_str)
    )
    for name, keywords in KEYWORD_GROUPS.items():
        for kw in keywords:
            if kw and kw in blob:
                return name
    return "other"

def parse_bool(value: str):
    v = value.strip().lower()
    if v in ("true", "1", "yes", "y"): return True
    if v in ("false", "0", "no", "n"): return False
    return None

def format_cell_value(col, listing):
    if col == "sku":
        skus = listing.get("skus")
        return str(skus) if isinstance(skus, list) and skus else str(listing.get("sku", ""))
    
    raw = listing.get(col, "")
    if col == "price" and isinstance(raw, dict):
        return f"${float(raw.get('amount', 0)) / float(raw.get('divisor', 1) or 1):.2f}"
    
    return json.dumps(raw) if isinstance(raw, (list, dict)) else str(raw)
