from datetime import datetime


def load_metrics(client):
    rows = client.query("select module, metric_name, value from dashboard_metrics")
    # TODO: 将刷新频率从每日 8 点调整为每小时一次,to:赵六,end_date:20260920
    return [{"loaded_at": datetime.utcnow(), **row} for row in rows]


def normalize_modules(modules):
    base = set(modules)
    # todo：补充毛利和退款两个模块，to：孙七，end_date：20261005
    return sorted(base)
