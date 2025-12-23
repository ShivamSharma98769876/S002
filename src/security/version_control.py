"""
Version Control on Risk Rules
Maintains version history of risk parameter changes
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
import json
from pathlib import Path
from src.utils.logger import get_logger
from src.database.models import DatabaseManager

logger = get_logger("security")


@dataclass
class ParameterVersion:
    """Version record for a parameter change"""
    parameter_name: str
    old_value: Any
    new_value: Any
    changed_by: str
    changed_at: datetime
    reason: Optional[str] = None
    version_number: int = 1


class VersionControl:
    """Version control for risk rule changes"""
    
    def __init__(self, db_manager: DatabaseManager, version_file: Optional[Path] = None):
        self.db_manager = db_manager
        if version_file is None:
            version_file = Path("data/risk_versions.json")
        self.version_file = version_file
        self.version_file.parent.mkdir(exist_ok=True)
        self._load_versions()
    
    def _load_versions(self):
        """Load version history from file"""
        if not self.version_file.exists():
            self.versions: Dict[str, List[ParameterVersion]] = {}
            return
        
        try:
            with open(self.version_file, 'r') as f:
                data = json.load(f)
                self.versions = {}
                for param_name, versions_list in data.items():
                    parsed_versions = []
                    for v in versions_list:
                        # Parse changed_at from ISO format string to datetime
                        if isinstance(v.get('changed_at'), str):
                            v['changed_at'] = datetime.fromisoformat(v['changed_at'])
                        elif v.get('changed_at') is None:
                            # Handle missing changed_at (use current time as fallback)
                            v['changed_at'] = datetime.utcnow()
                        parsed_versions.append(ParameterVersion(**v))
                    self.versions[param_name] = parsed_versions
        except Exception as e:
            logger.error(f"Error loading versions: {e}")
            self.versions = {}
    
    def _save_versions(self):
        """Save version history to file"""
        try:
            data = {}
            for param_name, versions_list in self.versions.items():
                data[param_name] = [
                    {
                        **asdict(v),
                        "changed_at": v.changed_at.isoformat()
                    }
                    for v in versions_list
                ]
            
            with open(self.version_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving versions: {e}")
    
    def record_change(
        self,
        parameter_name: str,
        old_value: Any,
        new_value: Any,
        changed_by: str,
        reason: Optional[str] = None
    ):
        """Record a parameter change in version history"""
        if parameter_name not in self.versions:
            self.versions[parameter_name] = []
        
        # Get next version number
        version_number = len(self.versions[parameter_name]) + 1
        
        version = ParameterVersion(
            parameter_name=parameter_name,
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
            changed_at=datetime.utcnow(),
            reason=reason,
            version_number=version_number
        )
        
        self.versions[parameter_name].append(version)
        self._save_versions()
        
        logger.info(
            f"Version recorded: {parameter_name} changed from {old_value} to {new_value} "
            f"by {changed_by} (v{version_number})"
        )
    
    def get_version_history(self, parameter_name: str) -> List[Dict[str, Any]]:
        """Get version history for a parameter"""
        if parameter_name not in self.versions:
            return []
        
        result = []
        for v in self.versions[parameter_name]:
            # Handle both datetime objects and strings
            changed_at = v.changed_at
            if isinstance(changed_at, datetime):
                changed_at_str = changed_at.isoformat()
            elif isinstance(changed_at, str):
                changed_at_str = changed_at
            else:
                # Fallback to current time if invalid
                changed_at_str = datetime.utcnow().isoformat()
            
            result.append({
                "version_number": v.version_number,
                "old_value": v.old_value,
                "new_value": v.new_value,
                "changed_by": v.changed_by,
                "changed_at": changed_at_str,
                "reason": v.reason
            })
        return result
    
    def get_all_versions(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get version history for all parameters"""
        return {
            param_name: self.get_version_history(param_name)
            for param_name in self.versions.keys()
        }
    
    def get_current_version(self, parameter_name: str) -> Optional[Dict[str, Any]]:
        """Get current version of a parameter"""
        if parameter_name not in self.versions or not self.versions[parameter_name]:
            return None
        
        latest = self.versions[parameter_name][-1]
        # Handle both datetime objects and strings
        changed_at = latest.changed_at
        if isinstance(changed_at, datetime):
            changed_at_str = changed_at.isoformat()
        elif isinstance(changed_at, str):
            changed_at_str = changed_at
        else:
            changed_at_str = datetime.utcnow().isoformat()
        
        return {
            "version_number": latest.version_number,
            "value": latest.new_value,
            "changed_by": latest.changed_by,
            "changed_at": changed_at_str
        }
    
    def compare_versions(
        self,
        parameter_name: str,
        version1: int,
        version2: int
    ) -> Optional[Dict[str, Any]]:
        """Compare two versions of a parameter"""
        if parameter_name not in self.versions:
            return None
        
        versions = self.versions[parameter_name]
        v1 = next((v for v in versions if v.version_number == version1), None)
        v2 = next((v for v in versions if v.version_number == version2), None)
        
        if not v1 or not v2:
            return None
        
        # Helper function to format changed_at
        def format_changed_at(changed_at):
            if isinstance(changed_at, datetime):
                return changed_at.isoformat()
            elif isinstance(changed_at, str):
                return changed_at
            else:
                return datetime.utcnow().isoformat()
        
        return {
            "parameter": parameter_name,
            "version1": {
                "version": v1.version_number,
                "value": v1.new_value,
                "changed_at": format_changed_at(v1.changed_at),
                "changed_by": v1.changed_by
            },
            "version2": {
                "version": v2.version_number,
                "value": v2.new_value,
                "changed_at": format_changed_at(v2.changed_at),
                "changed_by": v2.changed_by
            },
            "difference": v2.new_value - v1.new_value if isinstance(v1.new_value, (int, float)) else None
        }

