def knots(*at: float, value: float = 1) -> list[dict[str, float]]:
    return [{"at": point, "value": value} for point in at]


def even_knots(count: int, value: float = 1) -> list[dict[str, float]]:
    # From 0 to 1, evenly apart; a single knot sits at 0.
    return knots(*[index / max(count - 1, 1) for index in range(count)], value=value)
