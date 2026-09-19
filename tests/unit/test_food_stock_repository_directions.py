import pytest

from app.domain.food_stock import FoodMovementDirection
from app.repositories.food_stock.food_stock_repository import FoodStockRepository


class TestMovementSources:
    def test_every_direction_has_a_movement_source(self):
        """Every direction the enum declares is mapped to a source."""
        # An unmapped direction only raises once a request looks it up.
        assert set(FoodStockRepository._MOVEMENT_SOURCES) == set(FoodMovementDirection)

    @pytest.mark.parametrize("direction", list(FoodMovementDirection))
    def test_a_source_points_at_its_own_line_table(self, direction):
        """Each source's line table is the one its header owns."""
        # A header paired with the other table's lines counts 0 forever, quietly.
        source = FoodStockRepository._MOVEMENT_SOURCES[direction]

        assert source.item_fk.parent.class_ is source.item_model
        target = next(iter(source.item_fk.foreign_keys)).column.table.name
        assert target == source.model.__tablename__

    @pytest.mark.parametrize("direction", list(FoodMovementDirection))
    def test_a_source_dates_its_own_header(self, direction):
        """Each source's event-date column belongs to its own header."""
        source = FoodStockRepository._MOVEMENT_SOURCES[direction]

        assert source.occurred_at.parent.class_ is source.model
