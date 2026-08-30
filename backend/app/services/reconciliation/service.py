class ReconciliationService:
    def compare(self, internal_orders, broker_orders, internal_positions, broker_positions):
        issues=[]
        if len(internal_orders) != len(broker_orders):
            issues.append("order count mismatch")
        if len(internal_positions) != len(broker_positions):
            issues.append("position count mismatch")
        return issues
