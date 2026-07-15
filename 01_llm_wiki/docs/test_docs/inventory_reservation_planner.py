from collections import defaultdict


def reserve_inventory(orders, warehouses):
    stock = {w["name"]: dict(w["stock"]) for w in warehouses}
    rank = {w["name"]: (w["priority"], w["distance_km"]) for w in warehouses}
    allocations = []
    backorders = defaultdict(int)

    for order in sorted(orders, key=lambda item: (-item["vip"], item["created_at"])):
        sku = order["sku"]
        remaining = order["qty"]
        candidates = sorted(
            (name for name, items in stock.items() if items.get(sku, 0) > 0),
            key=lambda name: rank[name],
        )
        for warehouse_name in candidates:
            if remaining == 0:
                break
            picked = min(remaining, stock[warehouse_name].get(sku, 0))
            stock[warehouse_name][sku] -= picked
            remaining -= picked
            allocations.append((order["id"], sku, warehouse_name, picked))
        if remaining:
            backorders[(order["id"], sku)] += remaining

    return allocations, dict(backorders)


if __name__ == "__main__":
    warehouses = [
        {"name": "W-North", "priority": 1, "distance_km": 18, "stock": {"SKU-7": 4, "SKU-9": 2}},
        {"name": "W-East", "priority": 2, "distance_km": 9, "stock": {"SKU-7": 6, "SKU-9": 1}},
        {"name": "W-South", "priority": 2, "distance_km": 30, "stock": {"SKU-7": 1, "SKU-9": 5}},
    ]
    orders = [
        {"id": "SO-3003", "sku": "SKU-7", "qty": 5, "vip": 0, "created_at": "09:10"},
        {"id": "SO-3001", "sku": "SKU-7", "qty": 4, "vip": 1, "created_at": "09:00"},
        {"id": "SO-3002", "sku": "SKU-9", "qty": 6, "vip": 0, "created_at": "09:05"},
        {"id": "SO-3004", "sku": "SKU-7", "qty": 4, "vip": 1, "created_at": "09:12"},
    ]
    allocations, backorders = reserve_inventory(orders, warehouses)
    for item in allocations:
        print("|".join(map(str, item)))
    for key in sorted(backorders):
        print(f"BACKORDER|{key[0]}|{key[1]}|{backorders[key]}")
