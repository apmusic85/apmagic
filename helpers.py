import json

GROUPS = [
    "All",
    "Tees/T-shirts",
    "Hats",
    "shoes - men",
    "Framed Art Prints",
    "Backpack(s)",
    "Custom",
    "shoes - women",
    "Fanny",
    "other",
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
    "listing_id",
    "state",
    "shop_section_id",
    "title",
    "price",
    "quantity",
    "sku",
    "description",
    "tags",
    "materials",
    "style",
    "shipping_profile_id",
    "return_policy_id",
    "processing_min",
    "processing_max",
    "taxonomy_id",
    "who_made",
    "when_made",
    "is_supply",
    "item_length",
    "item_width",
    "item_height",
    "item_dimensions_unit",
    "item_weight",
    "item_weight_unit",
    "is_customizable",
    "is_personalizable",
    "is_private",
    "non_taxable",
    "is_taxable",
    "listing_type",
    "should_auto_renew",
]

def assign_group(listing: dict) -> str:
    skus_raw = listing.get("skus", [])
    skus_string_list = [str(s) for s in skus_raw] if isinstance(skus_raw, list) else []
    blob = (
        (listing.get("title") or "") + " " +
        (listing.get("description") or "") + " " +
        " ".join(listing.get("tags") or []) + " " +
        " ".join(skus_string_list)
    )
    for group_name, keywords in KEYWORD_GROUPS.items():
        for kw in keywords:
            if kw and kw in blob:
                return group_name
    return "other"

def parse_bool(value: str):
    v = value.strip().lower()
    if v in ("true", "1", "yes", "y"):
        return True
    if v in ("false", "0", "no", "n"):
        return False
    return None

def cast_and_validate_value(edit_target: str, insert_value: str):
    if edit_target in ["price", "item_length", "item_width", "item_height", "item_weight"]:
        try:
            return float(insert_value), None
        except ValueError:
            return None, f"Format Error: '{edit_target}' requires numeric inputs."
            
    elif edit_target in ["quantity", "processing_min", "processing_max", "taxonomy_id", "shipping_profile_id", "return_policy_id", "shop_section_id"]:
        try:
            return int(insert_value), None
        except ValueError:
            return None, f"Format Error: '{edit_target}' requires an integer value."
            
    elif edit_target in ["is_customizable", "is_personalizable", "is_private", "is_supply", "non_taxable", "is_taxable", "should_auto_renew"]:
        val = parse_bool(insert_value)
        if val is None:
            return None, "Format Error: Field requires a boolean choice (true/false, yes/no)."
        return val, None
        
    elif edit_target in ["tags", "materials", "style"]:
        return [x.strip() for x in insert_value.split(",") if x.strip()], None
        
    return insert_value, None
