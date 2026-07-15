SEVERITY_WEIGHT = {"P0": 100, "P1": 70, "P2": 40, "P3": 10}
TAG_BONUS = {"payment": 18, "login": 12, "vip": 15, "batch": -5, "cosmetic": -12}


def route_incidents(incidents):
    routed = []
    for incident in incidents:
        score = SEVERITY_WEIGHT[incident["severity"]]
        score += max(0, 60 - incident["minutes_since_open"]) // 10
        score += sum(TAG_BONUS.get(tag, 0) for tag in incident["tags"])
        if incident["affected_users"] >= 10000:
            score += 20
        elif incident["affected_users"] >= 1000:
            score += 8

        if "payment" in incident["tags"]:
            team = "settlement"
        elif "login" in incident["tags"]:
            team = "identity"
        elif incident["severity"] in ("P0", "P1"):
            team = "sre"
        else:
            team = "product"
        routed.append((incident["id"], team, score))
    return sorted(routed, key=lambda item: (-item[2], item[0]))


if __name__ == "__main__":
    incidents = [
        {"id": "INC-41", "severity": "P1", "minutes_since_open": 25, "affected_users": 1500, "tags": ["login"]},
        {"id": "INC-42", "severity": "P2", "minutes_since_open": 5, "affected_users": 22000, "tags": ["payment", "vip"]},
        {"id": "INC-43", "severity": "P0", "minutes_since_open": 80, "affected_users": 800, "tags": ["batch"]},
        {"id": "INC-44", "severity": "P3", "minutes_since_open": 12, "affected_users": 300, "tags": ["cosmetic"]},
        {"id": "INC-45", "severity": "P1", "minutes_since_open": 10, "affected_users": 12000, "tags": ["vip"]},
    ]
    for incident_id, team, score in route_incidents(incidents):
        print(f"{incident_id}|{team}|{score}")
