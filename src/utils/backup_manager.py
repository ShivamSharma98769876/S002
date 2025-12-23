"""
Backup Manager
Creates position snapshots for recovery
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from src.utils.logger import get_logger
from src.database.repository import PositionRepository
from src.database.models import Position

logger = get_logger("utils")


class BackupManager:
    """Manages position snapshots and backups"""
    
    def __init__(self, position_repo: PositionRepository, backup_dir: Path = None):
        self.position_repo = position_repo
        if backup_dir is None:
            backup_dir = Path("data/backups")
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
    
    def create_position_snapshot(self) -> Dict[str, Any]:
        """Create snapshot of current positions"""
        try:
            positions = self.position_repo.get_active_positions()
            
            snapshot = {
                "timestamp": datetime.utcnow().isoformat(),
                "positions": []
            }
            
            for pos in positions:
                snapshot["positions"].append({
                    "id": pos.id,
                    "instrument_token": pos.instrument_token,
                    "trading_symbol": pos.trading_symbol,
                    "exchange": pos.exchange,
                    "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
                    "entry_price": pos.entry_price,
                    "current_price": pos.current_price,
                    "quantity": pos.quantity,
                    "lot_size": pos.lot_size,
                    "unrealized_pnl": pos.unrealized_pnl
                })
            
            return snapshot
        except Exception as e:
            logger.error(f"Error creating position snapshot: {e}")
            return {}
    
    def save_snapshot(self, snapshot: Dict[str, Any]) -> Path:
        """Save snapshot to file"""
        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"position_snapshot_{timestamp}.json"
            filepath = self.backup_dir / filename
            
            with open(filepath, 'w') as f:
                json.dump(snapshot, f, indent=2)
            
            logger.debug(f"Position snapshot saved: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Error saving snapshot: {e}")
            return None
    
    def load_latest_snapshot(self) -> Optional[Dict[str, Any]]:
        """Load the latest position snapshot"""
        try:
            snapshots = sorted(self.backup_dir.glob("position_snapshot_*.json"))
            if not snapshots:
                return None
            
            latest = snapshots[-1]
            with open(latest, 'r') as f:
                snapshot = json.load(f)
            
            logger.info(f"Loaded latest snapshot: {latest.name}")
            return snapshot
        except Exception as e:
            logger.error(f"Error loading snapshot: {e}")
            return None
    
    def cleanup_old_snapshots(self, keep_last_n: int = 100):
        """Clean up old snapshots, keeping only the last N"""
        try:
            snapshots = sorted(self.backup_dir.glob("position_snapshot_*.json"))
            if len(snapshots) > keep_last_n:
                to_delete = snapshots[:-keep_last_n]
                for snapshot_file in to_delete:
                    snapshot_file.unlink()
                logger.info(f"Cleaned up {len(to_delete)} old snapshots")
        except Exception as e:
            logger.error(f"Error cleaning up snapshots: {e}")

