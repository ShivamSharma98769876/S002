"""
Test Runner - Run all tests
"""

import unittest
import sys
from io import StringIO

def run_all_tests():
    """Run all test suites"""
    # Discover and load all tests
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test modules
    test_modules = [
        'tests.test_config',
        'tests.test_trailing_sl',
        'tests.test_profit_protection',
        'tests.test_loss_protection',
        'tests.test_quantity_manager',
        'tests.test_edge_cases',
        'tests.test_integration',
        'tests.test_api_client',
        'tests.test_security',
        'tests.test_performance'
    ]
    
    for module_name in test_modules:
        try:
            suite.addTests(loader.loadTestsFromName(module_name))
        except ImportError as e:
            print(f"Warning: Could not import {module_name}: {e}")
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success rate: {((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100):.1f}%")
    
    if result.failures:
        print("\nFAILURES:")
        for test, traceback in result.failures:
            print(f"  - {test}: {traceback.split(chr(10))[-2]}")
    
    if result.errors:
        print("\nERRORS:")
        for test, traceback in result.errors:
            print(f"  - {test}: {traceback.split(chr(10))[-2]}")
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)

