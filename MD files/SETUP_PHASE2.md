# Phase 2 Implementation Complete: Trailing Stop Loss

## Overview
Phase 2 of the Risk Management System has been successfully implemented. This includes the complete Trailing Stop Loss system that activates when profit reaches ₹5,000 and trails every ₹10,000 increment.

## What's Been Implemented

### 1. Profit Calculation for Trailing SL (TASK-04-01)
✅ Calculate total daily profit including protected profit and current positions P&L
✅ Real-time profit tracking
✅ Handle profit-to-loss transitions
✅ Accurate profit calculation for multiple positions

### 2. Trailing SL Activation Logic (TASK-04-02)
✅ Check if profit >= ₹5,000
✅ Set initial trailing SL at ₹5,000
✅ Activate trailing SL flag
✅ Send notification on activation (logged)

### 3. Trailing SL Increment Logic (TASK-04-03)
✅ Detect profit increments of ₹10,000
✅ Update trailing SL: ₹5k → ₹10k → ₹20k → ₹30k...
✅ Only move SL up, never down
✅ Handle rapid profit changes correctly

### 4. Trailing SL Trigger & Exit (TASK-04-04)
✅ Monitor profit vs trailing SL continuously
✅ Trigger exit when profit <= trailing SL
✅ Place market orders for all positions
✅ Handle simultaneous exits correctly

### 5. Trailing SL Configuration (TASK-04-05)
✅ Configurable activation threshold (default ₹5,000)
✅ Configurable increment amount (default ₹10,000)
✅ Admin-only access for configuration
✅ Stored in admin_config.json

## New Components

### 1. `src/risk_management/trailing_stop_loss.py`
Main trailing stop loss system that:
- Calculates total daily profit (protected + unrealized)
- Activates when profit reaches ₹5,000
- Updates trailing SL every ₹10,000 increment
- Triggers exit when profit drops to trailing SL level

### 2. `src/risk_management/risk_monitor.py`
Coordinated risk monitoring system that:
- Runs continuous monitoring loop (every 1 second)
- Checks both loss protection and trailing SL
- Updates daily statistics
- Handles market hours checking

### 3. Updated `main.py`
- Integrated trailing SL system
- Started risk monitoring loop
- Coordinated all risk management components

### 4. Updated Database
- Added `trailing_sl_active` and `trailing_sl_level` to DailyStats
- Updated repository to handle trailing SL data

## How It Works

### Activation
1. System continuously monitors total daily profit
2. When profit reaches ₹5,000, trailing SL activates
3. Initial trailing SL is set at ₹5,000

### Increment Logic
- Profit ₹5,000 → Trailing SL = ₹5,000
- Profit ₹15,000 → Trailing SL = ₹10,000 (crossed ₹10k threshold)
- Profit ₹28,000 → Trailing SL = ₹20,000 (crossed ₹20k threshold)
- Profit ₹35,000 → Trailing SL = ₹30,000 (crossed ₹30k threshold)

### Trigger Logic
- If profit drops from ₹15,000 to ₹10,000 → Exit all positions
- If profit drops from ₹28,000 to ₹20,000 → Exit all positions
- Trailing SL only moves up, never down

## Configuration

Trailing SL parameters are configured in `config/admin_config.json`:
```json
{
  "trailing_sl_activation": 5000.0,
  "trailing_sl_increment": 10000.0
}
```

These parameters are **locked** and can only be modified by admin.

## Integration with Phase 1

The trailing SL system works seamlessly with:
- **Daily Loss Protection**: Both systems monitor simultaneously
- **Data Tracking**: All trailing SL events are logged to database
- **Position Monitoring**: Uses same position repository
- **Risk Monitor**: Coordinated monitoring loop

## Testing

Unit tests are available in `tests/test_trailing_sl.py`:
- Test activation at ₹5,000
- Test increment logic
- Test trigger when profit drops
- Test that SL only moves up

Run tests with:
```bash
pytest tests/test_trailing_sl.py -v
```

## Example Scenarios

### Scenario 1: Normal Profit Growth
1. User enters trade, profit reaches ₹5,000
2. Trailing SL activates at ₹5,000
3. Profit grows to ₹15,000 → Trailing SL moves to ₹10,000
4. Profit grows to ₹28,000 → Trailing SL moves to ₹20,000
5. Profit drops to ₹20,000 → All positions exited

### Scenario 2: Profit Drop Before Increment
1. Profit reaches ₹5,000 → Trailing SL at ₹5,000
2. Profit grows to ₹8,000 → Trailing SL stays at ₹5,000
3. Profit drops to ₹4,000 → All positions exited

### Scenario 3: Rapid Profit Growth
1. Profit jumps from ₹5,000 to ₹25,000
2. Trailing SL activates at ₹5,000
3. Trailing SL immediately updates to ₹20,000 (crossed ₹20k threshold)

## Status Monitoring

The system provides real-time status through `RiskMonitor.get_current_status()`:
```python
{
    "monitoring_active": True,
    "loss_protection": {...},
    "trailing_sl": {
        "total_profit": 15000.0,
        "trailing_sl_active": True,
        "trailing_sl_level": 10000.0,
        "activation_threshold": 5000.0,
        "increment_amount": 10000.0
    },
    "trading_blocked": False,
    "protected_profit": 0.0
}
```

## Next Steps

Phase 2 is complete! The system now has:
- ✅ Daily Loss Protection (Phase 1)
- ✅ Trailing Stop Loss (Phase 2)

Upcoming phases:
- Phase 3: Cycle-wise Profit Protection
- Phase 4: Dashboard UI & Notifications
- Phase 5: Security & Admin Controls
- Phase 6: Testing & Deployment

## Notes

- Trailing SL works independently of loss protection
- Both systems can trigger simultaneously if conditions are met
- Trailing SL protects profits, loss protection limits losses
- All actions are logged and audited

