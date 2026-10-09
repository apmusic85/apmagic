import os
import json
import requests

def generate_taxonomy_file():
    """
    Fetches the live seller taxonomy tree from the official Etsy Open API v3 endpoint
    using your combined keystring and shared secret as mandated by the platform.
    """
    keystring = os.environ.get("ETSY_KEYSTRING")
    shared_secret = os.environ.get("ETSY_SHARED_SECRET")
    
    if not keystring or not shared_secret:
        print("Taxonomy generator error: ETSY_KEYSTRING or ETSY_SHARED_SECRET missing in Render.")
        return False
        
    # Combines them to match the Etsy v3 security spec
    unified_api_key = f"{keystring}:{shared_secret}"
    
    # EXACT official API v3 seller taxonomy endpoint path
    url = "https://openapi.etsy.com/v3/application/seller-taxonomy/nodes"
    headers = {"x-api-key": unified_api_key}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])
            
            # Directly updates the file on your Render container
            current_file_path = __file__
            with open(current_file_path, "w", encoding="utf-8") as f:
                f.write(f"ETSY_TAXONOMY_TREE = {json.dumps(results, indent=4)}\n")
            print("Successfully populated taxonomy tree file.")
            return True
        else:
            print(f"Failed to fetch Etsy taxonomy. Status code: {response.status_code}")
            print(f"Server response: {response.text}")
            return False
    except Exception as e:
        print(f"Taxonomy generation exception occurred: {e}")
        return False

try:
    if "ETSY_TAXONOMY_TREE" not in globals():
        generate_taxonomy_file()
        from taxonomy_id_list_me import ETSY_TAXONOMY_TREE
except Exception:
    ETSY_TAXONOMY_TREE = []
