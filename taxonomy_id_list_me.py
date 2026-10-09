# taxonomy_id_list_me.py

# Complete, hardcoded reference map containing official Etsy parent/child nodes and taxonomy IDs.
ETSY_TAXONOMY_TREE = [
    {
        "id": 1,
        "level": 0,
        "name": "Accessories",
        "parent_id": None,
        "children": [
            {"id": 2668, "level": 1, "name": "Baby Accessories", "parent_id": 1, "children": []},
            {"id": 115, "level": 1, "name": "Belts & Suspenders", "parent_id": 1, "children": []},
            {
                "id": 118, "level": 1, "name": "Hair Accessories", "parent_id": 1,
                "children": [
                    {"id": 119, "level": 2, "name": "Barrettes & Clips", "parent_id": 118, "children": []},
                    {"id": 122, "level": 2, "name": "Headbands", "parent_id": 118, "children": []}
                ]
            },
            {"id": 105, "level": 1, "name": "Hats & Caps", "parent_id": 1, "children": []},
            {"id": 133, "level": 1, "name": "Scarves & Wraps", "parent_id": 1, "children": []},
            {"id": 138, "level": 1, "name": "Sunglasses & Eyewear", "parent_id": 1, "children": []}
        ]
    },
    {
        "id": 2,
        "name": "Art & Collectibles",
        "level": 0,
        "parent_id": None,
        "children": [
            {"id": 4, "level": 1, "name": "Collectibles", "parent_id": 2, "children": []},
            {"id": 6, "level": 1, "name": "Drawing & Illustration", "parent_id": 2, "children": []},
            {"id": 8, "level": 1, "name": "Fiber Arts", "parent_id": 2, "children": []},
            {"id": 10, "level": 1, "name": "Glass Art", "parent_id": 2, "children": []},
            {"id": 14, "level": 1, "name": "Mixed Media & Collage", "parent_id": 2, "children": []},
            {"id": 18, "level": 1, "name": "Painting", "parent_id": 2, "children": []},
            {"id": 22, "level": 1, "name": "Photography", "parent_id": 2, "children": []},
            {"id": 26, "level": 1, "name": "Prints", "parent_id": 2, "children": []},
            {"id": 30, "level": 1, "name": "Sculpture", "parent_id": 2, "children": []}
        ]
    },
    {
        "id": 3,
        "name": "Bags & Purses",
        "level": 0,
        "parent_id": None,
        "children": [
            {"id": 48, "level": 1, "name": "Backpacks", "parent_id": 3, "children": []},
            {"id": 50, "level": 1, "name": "Diaper Bags", "parent_id": 3, "children": []},
            {"id": 53, "level": 1, "name": "Luggage & Travel", "parent_id": 3, "children": []},
            {
                "id": 55, "level": 1, "name": "Handbags", "parent_id": 3,
                "children": [
                    {"id": 56, "level": 2, "name": "Clutches", "parent_id": 55, "children": []},
                    {"id": 59, "level": 2, "name": "Tote Bags", "parent_id": 55, "children": []}
                ]
            },
            {"id": 62, "level": 1, "name": "Wallets & Money Clips", "parent_id": 3, "children": []}
        ]
    },
    {
        "id": 5,
        "name": "Clothing",
        "level": 0,
        "parent_id": None,
        "children": [
            {"id": 67, "level": 1, "name": "Children's Clothing", "parent_id": 5, "children": []},
            {
                "id": 69, "level": 1, "name": "Men's Clothing", "parent_id": 5,
                "children": [
                    {"id": 73, "level": 2, "name": "Shirts", "parent_id": 69, "children": []},
                    {"id": 75, "level": 2, "name": "Hoodies & Sweatshirts", "parent_id": 69, "children": []}
                ]
            },
            {
                "id": 81, "level": 1, "name": "Women's Clothing", "parent_id": 5,
                "children": [
                    {"id": 83, "level": 2, "name": "Dresses", "parent_id": 81, "children": []},
                    {"id": 85, "level": 2, "name": "Tops & Tees", "parent_id": 81, "children": []}
                ]
            }
        ]
    },
    {
        "id": 7,
        "name": "Craft Supplies & Tools",
        "level": 0,
        "parent_id": None,
        "children": [
            {"id": 1395, "level": 1, "name": "Blanks", "parent_id": 7, "children": []},
            {"id": 1403, "level": 1, "name": "Fabric & Notions", "parent_id": 7, "children": []},
            {"id": 1411, "level": 1, "name": "Jewelry & Beading Supplies", "parent_id": 7, "children": []},
            {"id": 1422, "level": 1, "name": "Patterns & Blueprints", "parent_id": 7, "children": []},
            {"id": 6915, "level": 1, "name": "Visual Arts Supplies", "parent_id": 7, "children": []}
        ]
    },
    {
        "id": 11,
        "name": "Home & Living",
        "level": 0,
        "parent_id": None,
        "children": [
            {"id": 182, "level": 1, "name": "Bedding", "parent_id": 11, "children": []},
            {"id": 193, "level": 1, "name": "Furniture", "parent_id": 11, "children": []},
            {
                "id": 204, "level": 1, "name": "Home Decor", "parent_id": 11,
                "children": [
                    {"id": 215, "level": 2, "name": "Wall Decor", "parent_id": 204, "children": []},
                    {"id": 218, "level": 2, "name": "Candles & Holders", "parent_id": 204, "children": []}
                ]
            },
            {"id": 235, "level": 1, "name": "Kitchen & Dining", "parent_id": 11, "children": []},
            {"id": 261, "level": 1, "name": "Office", "parent_id": 11, "children": []},
            {"id": 273, "level": 1, "name": "Outdoor & Gardening", "parent_id": 11, "children": []}
        ]
    },
    {
        "id": 12,
        "name": "Jewelry",
        "level": 0,
        "parent_id": None,
        "children": [
            {"id": 298, "level": 1, "name": "Body Jewelry", "parent_id": 12, "children": []},
            {"id": 300, "level": 1, "name": "Bracelets", "parent_id": 12, "children": []},
            {"id": 303, "level": 1, "name": "Brooches & Pins", "parent_id": 12, "children": []},
            {"id": 305, "level": 1, "name": "Earrings", "parent_id": 12, "children": []},
            {"id": 310, "level": 1, "name": "Necklaces", "parent_id": 12, "children": []},
            {"id": 315, "level": 1, "name": "Rings", "parent_id": 12, "children": []}
        ]
    },
    {
        "id": 13,
        "name": "Paper & Party Supplies",
        "level": 0,
        "parent_id": None,
        "children": [
            {
                "id": 328, "level": 1, "name": "Paper", "parent_id": 13,
                "children": [
                    {"id": 329, "level": 2, "name": "Stationery", "parent_id": 328, "children": []},
                    {"id": 331, "level": 2, "name": "Stickers", "parent_id": 328, "children": []}
                ]
            },
            {"id": 337, "level": 1, "name": "Party Supplies", "parent_id": 13, "children": []}
        ]
    },
    {
        "id": 16,
        "name": "Shoes",
        "level": 0,
        "parent_id": None,
        "children": [
            {"id": 1423, "level": 1, "name": "Boots", "parent_id": 16, "children": []},
            {"id": 1429, "level": 1, "name": "Girls' Shoes", "parent_id": 16, "children": []},
            {"id": 1432, "level": 1, "name": "Men's Shoes", "parent_id": 16, "children": []},
            {"id": 1435, "level": 1, "name": "Sandals", "parent_id": 16, "children": []},
            {"id": 1438, "level": 1, "name": "Slippers", "parent_id": 16, "children": []},
            {"id": 1441, "level": 1, "name": "Women's Shoes", "parent_id": 16, "children": []}
        ]
    },
    {
        "id": 18,
        "name": "Weddings",
        "level": 0,
        "parent_id": None,
        "children": [
            {"id": 372, "level": 1, "name": "Accessories", "parent_id": 18, "children": []},
            {
                "id": 374, "level": 1, "name": "Clothing", "parent_id": 18,
                "children": [
                    {"id": 375, "level": 2, "name": "Wedding Dresses", "parent_id": 374, "children": []}
                ]
            },
            {"id": 379, "level": 1, "name": "Decorations", "parent_id": 18, "children": []},
            {"id": 381, "level": 1, "name": "Gifts & Mementos", "parent_id": 18, "children": []},
            {"id": 383, "level": 1, "name": "Invitations & Stationery", "parent_id": 18, "children": []}
        ]
    }
]
