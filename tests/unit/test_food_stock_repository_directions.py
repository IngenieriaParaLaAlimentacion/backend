from app.domain.food_stock import FoodMovementDirection
from app.repositories.food_stock.food_stock_repository import FoodStockRepository


class TestMovementSources:
    def test_every_direction_has_a_movement_source(self):
        """`_build_movements_subquery` iterates `FoodMovementDirection` and looks
        each member up in the table, so a direction added to the enum but not
        mapped here would raise a KeyError at request time. Fail at test speed
        instead."""
        assert set(FoodStockRepository._MOVEMENT_SOURCES) == set(FoodMovementDirection)
