"""
Instrument selection utilities for Live Trader.

Provides ATM/ITM strike calculation and basic lot size / pyramiding config
per segment.
"""

from dataclasses import dataclass
from typing import Dict, Tuple, Optional, List, Any

from src.utils.logger import get_logger

logger = get_logger("live_trader")


def calculate_atm_strike(spot_price: float, segment: str) -> int:
    """
    Calculate ATM strike for a given segment.

    Rules mirror BacktestEngine._calculate_atm_strike.
    """
    seg = segment.upper()
    if seg == "NIFTY":
        return round(spot_price / 50) * 50
    if seg == "BANKNIFTY":
        return round(spot_price / 100) * 100
    if seg == "SENSEX":
        return round(spot_price / 100) * 100
    # Default
    return round(spot_price / 50) * 50


def select_itm_strike(spot_price: float, segment: str, itm_offset: float, option_type: str) -> int:
    """
    Select ITM strike for CE/PE given spot and offset in points.

    - For CE (buy call): ITM strike = ATM - offset
    - For PE (buy put):  ITM strike = ATM + offset
    """
    atm = calculate_atm_strike(spot_price, segment)
    opt = option_type.upper()
    if opt == "CE":
        strike = atm - itm_offset
    elif opt == "PE":
        strike = atm + itm_offset
    else:
        raise ValueError(f"Unsupported option_type: {option_type}")

    strike_int = int(round(strike))
    logger.debug(f"ITM selection: segment={segment}, spot={spot_price}, atm={atm}, "
                 f"offset={itm_offset}, opt={opt}, strike={strike_int}")
    return strike_int


def select_strike_by_delta(
    kite_client,
    segment: str,
    option_type: str,
    expiry: str,
    min_delta: float,
    max_delta: float,
    spot_price: Optional[float] = None,
    prefer_closest_to_atm: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Select strike based on Delta range instead of fixed ITM offset.
    
    This method fetches the option chain, filters by Delta range, and selects
    the best strike within that range.
    
    Args:
        kite_client: Authenticated KiteClient instance
        segment: Trading segment (NIFTY, BANKNIFTY, SENSEX)
        option_type: CE or PE
        expiry: Expiry date in YYYY-MM-DD format
        min_delta: Minimum Delta value (e.g., 0.3)
        max_delta: Maximum Delta value (e.g., 0.4)
        spot_price: Optional spot price (used for ATM preference if provided)
        prefer_closest_to_atm: If True, prefer strikes closest to ATM when multiple options match
    
    Returns:
        Dict with strike details (strike, delta, premium, tradingsymbol, etc.) or None if no match
    """
    try:
        # Get option chain with Delta values
        option_chain = kite_client.get_option_chain_with_delta(
            segment=segment,
            option_type=option_type,
            expiry=expiry
        )
        
        if not option_chain:
            logger.warning(f"No option chain found for {segment} {option_type} expiry {expiry}")
            return None
        
        # Filter by Delta range
        # Note: For PE options, Delta is negative, so we need to handle absolute values
        matching_options = []
        for opt in option_chain:
            delta = opt['delta']
            # For PE, Delta is negative, so use absolute value for comparison
            delta_abs = abs(delta)
            
            if min_delta <= delta_abs <= max_delta:
                matching_options.append(opt)
        
        if not matching_options:
            logger.warning(
                f"No options found in Delta range [{min_delta}, {max_delta}] for "
                f"{segment} {option_type} expiry {expiry}. Available Delta range: "
                f"[{min(abs(o['delta']) for o in option_chain):.3f}, "
                f"{max(abs(o['delta']) for o in option_chain):.3f}]"
            )
            return None
        
        # Select best option from matching ones
        if prefer_closest_to_atm and spot_price is not None:
            # Prefer strike closest to ATM
            atm = calculate_atm_strike(spot_price, segment)
            best_option = min(
                matching_options,
                key=lambda x: abs(x['strike'] - atm)
            )
        else:
            # Prefer option with Delta closest to middle of range
            target_delta = (min_delta + max_delta) / 2.0
            best_option = min(
                matching_options,
                key=lambda x: abs(abs(x['delta']) - target_delta)
            )
        
        logger.info(
            f"Delta-based strike selection: {segment} {option_type} expiry {expiry} - "
            f"Selected strike={best_option['strike']}, Delta={best_option['delta']:.3f}, "
            f"Premium=₹{best_option['premium']:.2f} "
            f"(Range: [{min_delta}, {max_delta}], {len(matching_options)} matches)"
        )
        
        return best_option
        
    except Exception as e:
        logger.error(f"Error selecting strike by Delta: {e}", exc_info=True)
        return None


@dataclass
class SegmentConfig:
    """Configuration for a trading segment used by Live Trader."""

    lot_size: int
    pyramid_points: float
    lot_addition: int
    max_quantity: int
    itm_offset: float  # ITM offset in points (can be negative for OTM)
    stop_loss: float  # Stop loss: points for Buy regime, percentage (%) for Sell regime (per segment)
    # Delta-based strike selection (alternative to itm_offset)
    min_delta: Optional[float] = None  # Minimum Delta value (e.g., 0.3)
    max_delta: Optional[float] = None  # Maximum Delta value (e.g., 0.4)
    # If min_delta and max_delta are set, they take precedence over itm_offset


DEFAULT_SEGMENT_CONFIGS: Dict[str, SegmentConfig] = {
    # Values derived from LIVE_TRADER_SYSTEM.md examples
    "NIFTY": SegmentConfig(
        lot_size=75,
        pyramid_points=5.0,
        lot_addition=5,
        max_quantity=1500,
        itm_offset=-200.0,  # OTM offset for NIFTY
        stop_loss=30.0,  # Stop loss for NIFTY: 30 points (Buy) or 30% (Sell)
    ),
    "BANKNIFTY": SegmentConfig(
        lot_size=35,
        pyramid_points=20.0,
        lot_addition=10,
        max_quantity=1000,
        itm_offset=-300.0,  # OTM offset for BANKNIFTY
        stop_loss=40.0,  # Stop loss for BANKNIFTY: 40 points (Buy) or 40% (Sell)
    ),
    "SENSEX": SegmentConfig(
        lot_size=20,
        pyramid_points=20.0,
        lot_addition=10,
        max_quantity=1000,
        itm_offset=-500.0,  # OTM offset for SENSEX
        stop_loss=50.0,  # Stop loss for SENSEX: 50 points (Buy) or 50% (Sell)
    ),
}


def get_segment_config(segment: str) -> SegmentConfig:
    """
    Get per-segment configuration with sensible defaults.

    In future this can be extended to read from admin_config.
    """
    key = segment.upper()
    if key not in DEFAULT_SEGMENT_CONFIGS:
        raise ValueError(f"Unsupported segment: {segment}")
    return DEFAULT_SEGMENT_CONFIGS[key]


def compute_pyramiding(
    segment: str,
    current_quantity: int,
    unrealized_profit: float,
    custom_config: Optional[SegmentConfig] = None,
) -> Tuple[bool, int]:
    """
    Decide whether to add lots based on pyramiding rules from spec.

    Uses:
    - pyramid_points (per segment)
    - lot_addition (per segment)
    - max_quantity (per segment)

    Logic:
      - threshold = current_quantity * pyramid_points
      - if unrealized_profit >= threshold, add lot_addition lots
      - but never exceed max_quantity

    Args:
        segment: Segment name (used for logging if custom_config not provided)
        current_quantity: Current position quantity
        unrealized_profit: Current unrealized profit
        custom_config: Optional custom SegmentConfig to use instead of defaults
    """
    cfg = custom_config if custom_config is not None else get_segment_config(segment)
    if current_quantity <= 0:
        return False, 0

    threshold = current_quantity * cfg.pyramid_points
    if unrealized_profit < threshold:
        return False, 0

    # Calculate how many lots we can safely add without breaching max_quantity
    remaining_qty = cfg.max_quantity - current_quantity
    if remaining_qty <= 0:
        return False, 0

    qty_to_add = min(cfg.lot_addition * cfg.lot_size, remaining_qty)
    if qty_to_add <= 0:
        return False, 0

    logger.info(
        f"Pyramiding signal for {segment}: quantity={current_quantity}, "
        f"profit={unrealized_profit:.2f}, threshold={threshold:.2f}, "
        f"qty_to_add={qty_to_add}"
    )
    return True, qty_to_add


