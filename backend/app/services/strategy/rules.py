OPERATORS = {
    "GREATER_THAN": lambda a,b: a > b,
    "LESS_THAN": lambda a,b: a < b,
    "EQUAL": lambda a,b: a == b,
    "GREATER_OR_EQUAL": lambda a,b: a >= b,
    "LESS_OR_EQUAL": lambda a,b: a <= b,
}

def evaluate(rule, values):
    op = rule["operator"]
    if op in OPERATORS:
        return OPERATORS[op](values[rule["left"]], values[rule["right"]])
    if op == "CROSS_ABOVE":
        return values[rule["left"]] > values[rule["right"]]
    if op == "CROSS_BELOW":
        return values[rule["left"]] < values[rule["right"]]
    if op == "AND":
        return all(evaluate(x, values) for x in rule["rules"])
    if op == "OR":
        return any(evaluate(x, values) for x in rule["rules"])
    raise ValueError(f"Unsupported operator: {op}")
