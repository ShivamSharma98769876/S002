# Testing Guide

## Overview
This document provides guidance on running and maintaining tests for the Risk Management System.

## Test Structure

### Test Files
- `tests/test_config.py` - Configuration management tests
- `tests/test_loss_protection.py` - Daily loss protection tests
- `tests/test_trailing_sl.py` - Trailing stop loss tests
- `tests/test_profit_protection.py` - Profit protection tests
- `tests/test_quantity_manager.py` - Quantity management tests
- `tests/test_edge_cases.py` - Edge case handling tests
- `tests/test_integration.py` - Integration tests
- `tests/test_api_client.py` - API client tests
- `tests/test_security.py` - Security component tests
- `tests/test_performance.py` - Performance tests
- `tests/test_market_hours.py` - Market hours tests

## Running Tests

### Run All Tests
```bash
python -m pytest
```

### Run with Coverage
```bash
pytest --cov=src --cov-report=html
```

### Run Specific Test File
```bash
pytest tests/test_loss_protection.py
```

### Run Specific Test
```bash
pytest tests/test_loss_protection.py::TestDailyLossProtection::test_calculate_daily_loss_no_positions
```

### Run by Marker
```bash
# Unit tests only
pytest -m unit

# Integration tests only
pytest -m integration

# Performance tests only
pytest -m performance
```

## Test Categories

### Unit Tests
Test individual components in isolation:
- Loss protection calculations
- Trailing SL logic
- Profit protection
- Quantity management
- Configuration validation

### Integration Tests
Test component interactions:
- Loss limit auto-exit flow
- Trailing SL activation flow
- Protected profit separation
- Multi-position scenarios

### Performance Tests
Test system performance:
- Calculation speed
- Auto-exit latency
- High position count handling

### Security Tests
Test security features:
- Access control
- Parameter locking
- Session management
- Audit logging

## Coverage Goals

- **Current Target**: 50% (minimum)
- **Long-term Goal**: 80%+
- **Critical Components**: 90%+

## Writing New Tests

### Test Naming Convention
- Test files: `test_<module_name>.py`
- Test classes: `Test<ClassName>`
- Test methods: `test_<description>`

### Example Test Structure
```python
import unittest
from unittest.mock import Mock

class TestComponent(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures"""
        self.mock_dependency = Mock()
    
    def test_feature_behavior(self):
        """Test description"""
        # Arrange
        # Act
        # Assert
        self.assertEqual(expected, actual)
```

## Continuous Integration

Tests should be run:
- Before every commit
- In CI/CD pipeline
- Before deployment
- After code changes

## Test Maintenance

- Update tests when code changes
- Add tests for new features
- Fix broken tests immediately
- Review coverage reports regularly
- Keep tests fast and independent

## Troubleshooting

### Tests Failing
1. Check error messages
2. Verify mocks are set up correctly
3. Check test data
4. Review recent code changes

### Low Coverage
1. Identify untested code paths
2. Add tests for edge cases
3. Test error handling
4. Test integration points

### Slow Tests
1. Use mocks instead of real dependencies
2. Avoid I/O operations
3. Run tests in parallel
4. Profile slow tests

