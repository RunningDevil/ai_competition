from decimal import Decimal, ROUND_HALF_UP


def money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def reconcile(accounts, payments, credit_limits):
    ledger = {}
    for account_id, invoices in accounts.items():
        total = sum((money(item["amount"]) for item in invoices), Decimal("0.00"))
        paid = sum((money(p["amount"]) for p in payments if p["account_id"] == account_id), Decimal("0.00"))
        overdue_days = max((item["overdue_days"] for item in invoices), default=0)
        late_fee = money(total * Decimal("0.015")) if overdue_days > 30 else Decimal("0.00")
        outstanding = money(total + late_fee - paid)
        limit = money(credit_limits.get(account_id, 0))
        status = "BLOCK" if outstanding > limit else "WATCH" if overdue_days > 15 else "OK"
        ledger[account_id] = {
            "total": total,
            "paid": paid,
            "late_fee": late_fee,
            "outstanding": outstanding,
            "status": status,
        }
    return ledger


if __name__ == "__main__":
    accounts = {
        "AC-1001": [
            {"amount": "18200.00", "overdue_days": 42},
            {"amount": "3200.50", "overdue_days": 8},
        ],
        "AC-1002": [
            {"amount": "7600.25", "overdue_days": 0},
            {"amount": "1180.40", "overdue_days": 0},
        ],
        "AC-1003": [
            {"amount": "9900.00", "overdue_days": 18},
        ],
    }
    payments = [
        {"account_id": "AC-1001", "amount": "5000.00"},
        {"account_id": "AC-1001", "amount": "1400.00"},
        {"account_id": "AC-1002", "amount": "9000.00"},
        {"account_id": "AC-1003", "amount": "1000.00"},
    ]
    limits = {"AC-1001": "12000.00", "AC-1002": "2000.00", "AC-1003": "9000.00"}
    result = reconcile(accounts, payments, limits)
    for account_id in sorted(result):
        row = result[account_id]
        print(f"{account_id}|{row['outstanding']}|{row['late_fee']}|{row['status']}")
