"""
Unit Tests for Kite API Client
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from src.api.kite_client import KiteClient
from src.config.config_manager import ConfigManager
from src.utils.exceptions import AuthenticationError, OrderExecutionError


class TestKiteClient(unittest.TestCase):
    """Test cases for Kite API Client"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_config = Mock(spec=ConfigManager)
        self.mock_config.get_user_config.return_value = Mock(
            api_key="test_api_key",
            api_secret="test_api_secret",
            access_token="test_access_token"
        )
        
        self.kite_client = KiteClient(self.mock_config)
    
    @patch('src.api.kite_client.KiteConnect')
    def test_authentication_success(self, mock_kite_connect):
        """Test successful authentication"""
        mock_kite = Mock()
        mock_kite_connect.return_value = mock_kite
        mock_kite.generate_session.return_value = {"access_token": "new_token"}
        
        result = self.kite_client.authenticate("test_request_token")
        
        self.assertTrue(result)
        self.assertEqual(self.kite_client.access_token, "new_token")
        mock_kite.generate_session.assert_called_once()
    
    @patch('src.api.kite_client.KiteConnect')
    def test_authentication_failure(self, mock_kite_connect):
        """Test authentication failure"""
        mock_kite = Mock()
        mock_kite_connect.return_value = mock_kite
        mock_kite.generate_session.side_effect = Exception("Invalid token")
        
        result = self.kite_client.authenticate("invalid_token")
        
        self.assertFalse(result)
    
    def test_is_authenticated(self):
        """Test authentication status check"""
        self.kite_client.access_token = "test_token"
        self.assertTrue(self.kite_client.is_authenticated())
        
        self.kite_client.access_token = None
        self.assertFalse(self.kite_client.is_authenticated())
    
    @patch('src.api.kite_client.KiteConnect')
    def test_get_positions(self, mock_kite_connect):
        """Test getting positions from API"""
        mock_kite = Mock()
        mock_kite_connect.return_value = mock_kite
        self.kite_client.kite = mock_kite
        self.kite_client.access_token = "test_token"
        
        mock_positions = [
            {"tradingsymbol": "NIFTY25JAN24000CE", "quantity": 10, "pnl": 100.0}
        ]
        mock_kite.positions.return_value = {"net": mock_positions}
        
        positions = self.kite_client.get_positions()
        
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["tradingsymbol"], "NIFTY25JAN24000CE")
    
    @patch('src.api.kite_client.KiteConnect')
    def test_place_market_order(self, mock_kite_connect):
        """Test placing market order"""
        mock_kite = Mock()
        mock_kite_connect.return_value = mock_kite
        self.kite_client.kite = mock_kite
        self.kite_client.access_token = "test_token"
        
        mock_kite.place_order.return_value = "order123"
        
        order_id = self.kite_client.place_market_order(
            tradingsymbol="NIFTY25JAN24000CE",
            exchange="NFO",
            transaction_type="BUY",
            quantity=10,
            product="MIS"
        )
        
        self.assertEqual(order_id, "order123")
        mock_kite.place_order.assert_called_once()
    
    @patch('src.api.kite_client.KiteConnect')
    def test_place_order_not_authenticated(self, mock_kite_connect):
        """Test placing order without authentication"""
        self.kite_client.access_token = None
        
        with self.assertRaises(AuthenticationError):
            self.kite_client.place_market_order(
                tradingsymbol="NIFTY25JAN24000CE",
                exchange="NFO",
                transaction_type="BUY",
                quantity=10
            )
    
    @patch('src.api.kite_client.KiteConnect')
    def test_square_off_all_positions(self, mock_kite_connect):
        """Test squaring off all positions"""
        mock_kite = Mock()
        mock_kite_connect.return_value = mock_kite
        self.kite_client.kite = mock_kite
        self.kite_client.access_token = "test_token"
        
        mock_positions = [
            {"tradingsymbol": "NIFTY25JAN24000CE", "quantity": 10, "exchange": "NFO"},
            {"tradingsymbol": "NIFTY25JAN24001CE", "quantity": 5, "exchange": "NFO"}
        ]
        mock_kite.positions.return_value = {"net": mock_positions}
        mock_kite.place_order.side_effect = ["order1", "order2"]
        
        order_ids = self.kite_client.square_off_all_positions()
        
        self.assertEqual(len(order_ids), 2)
        self.assertEqual(mock_kite.place_order.call_count, 2)


if __name__ == '__main__':
    unittest.main()

