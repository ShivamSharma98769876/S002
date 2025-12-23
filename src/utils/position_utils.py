"""
Position Utility Functions
"""

from typing import List, Dict, Any
from src.database.models import Position


def calculate_position_pnl(
    entry_price: float,
    current_price: float,
    quantity: int,
    lot_size: int = 1
) -> float:
    """
    Calculate unrealized P&L for a position
    For BUY positions (quantity > 0): P&L = (current_price - entry_price) * quantity * lot_size
    For SELL positions (quantity < 0): P&L = (entry_price - current_price) * abs(quantity) * lot_size
    """
    if quantity > 0:
        # BUY position
        return (current_price - entry_price) * quantity * lot_size
    else:
        # SELL position
        return (entry_price - current_price) * abs(quantity) * lot_size


def filter_options_positions(positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter only options positions from position list"""
    options_positions = []
    for pos in positions:
        symbol = pos.get('tradingsymbol', '').upper()
        # Options typically have 'CE' or 'PE' suffix
        if 'CE' in symbol or 'PE' in symbol:
            options_positions.append(pos)
    return options_positions


def aggregate_positions_pnl(positions: List[Position]) -> float:
    """Calculate total unrealized P&L from list of positions"""
    return sum(pos.unrealized_pnl for pos in positions if pos.is_active)

