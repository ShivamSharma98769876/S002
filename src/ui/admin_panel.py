"""
Admin Configuration Interface
Admin-only interface for modifying locked parameters
"""

from flask import Blueprint, request, jsonify, render_template
from typing import Dict, Any
from src.utils.logger import get_logger
from src.security.access_control import AccessControl
from src.security.parameter_locker import ParameterLocker
from src.security.version_control import VersionControl
from src.config.config_manager import ConfigManager
from src.database.models import DatabaseManager

logger = get_logger("ui")

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def init_admin_panel(
    app,
    access_control: AccessControl,
    parameter_locker: ParameterLocker,
    version_control: VersionControl,
    kite_client=None
):
    """Initialize admin panel routes"""
    
    @admin_bp.route('/login', methods=['POST'])
    def admin_login():
        """Admin login endpoint"""
        data = request.get_json()
        password = data.get('password', '')
        
        token = access_control.authenticate_admin(password)
        if token:
            return jsonify({"success": True, "token": token})
        return jsonify({"success": False, "error": "Invalid password"}), 401
    
    @admin_bp.route('/logout', methods=['POST'])
    def admin_logout():
        """Admin logout endpoint"""
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        access_control.logout(token)
        return jsonify({"success": True})
    
    @admin_bp.route('/panel')
    def admin_panel_page():
        """Admin panel page"""
        return render_template('admin.html')
    
    @admin_bp.route('/parameters', methods=['GET'])
    def get_parameters():
        """Get all parameters with lock status"""
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not access_control.is_user(token):
            return jsonify({"error": "Unauthorized"}), 401
        
        is_admin = access_control.is_admin(token)
        all_params = parameter_locker.get_all_parameters_info()
        
        # Filter based on user role
        if not is_admin:
            # Users can only see unlocked parameters
            all_params = {k: v for k, v in all_params.items() if not v['is_locked']}
        
        return jsonify(all_params)
    
    @admin_bp.route('/parameters/<parameter_name>', methods=['PUT'])
    def update_parameter(parameter_name: str):
        """Update a parameter"""
        try:
            token = request.headers.get('Authorization', '').replace('Bearer ', '')
            data = request.get_json()
            
            if not data:
                return jsonify({"error": "No data provided"}), 400
            
            value = data.get('value')
            admin_password = data.get('admin_password')
            reason = data.get('reason', '')
            
            if not access_control.is_user(token):
                return jsonify({"error": "Unauthorized"}), 401
            
            # Get current value for version control
            param_info = parameter_locker.get_parameter_info(parameter_name)
            old_value = param_info.get('current_value')
            
            # Update parameter
            success = parameter_locker.update_parameter(
                parameter_name,
                value,
                token,
                admin_password
            )
            
            if success:
                # Record version (optional - don't fail if this fails)
                try:
                    session = access_control.verify_session(token)
                    changed_by = session.user_id if session else "unknown"
                    version_control.record_change(
                        parameter_name,
                        old_value,
                        value,
                        changed_by,
                        reason
                    )
                except Exception as version_error:
                    # Version control failure shouldn't prevent success response
                    logger.warning(f"Failed to record version for {parameter_name}: {version_error}")
                
                return jsonify({
                    "success": True, 
                    "message": f"Parameter {parameter_name} updated successfully",
                    "old_value": old_value,
                    "new_value": value
                })
            
            # If update failed, return error
            return jsonify({"error": "Failed to update parameter. Check logs for details."}), 403
        except Exception as e:
            logger.error(f"Error in update_parameter endpoint: {e}", exc_info=True)
            return jsonify({"error": f"Internal error: {str(e)}"}), 500
    
    @admin_bp.route('/versions/<parameter_name>', methods=['GET'])
    def get_versions(parameter_name: str):
        """Get version history for a parameter"""
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not access_control.is_admin(token):
            return jsonify({"error": "Admin access required"}), 403
        
        versions = version_control.get_version_history(parameter_name)
        return jsonify(versions)
    
    @admin_bp.route('/versions', methods=['GET'])
    def get_all_versions():
        """Get version history for all parameters"""
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not access_control.is_admin(token):
            return jsonify({"error": "Admin access required"}), 403
        
        versions = version_control.get_all_versions()
        return jsonify(versions)
    
    @admin_bp.route('/audit-logs', methods=['GET'])
    def get_audit_logs():
        """Get audit logs"""
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not access_control.is_admin(token):
            return jsonify({"error": "Admin access required"}), 403
        
        limit = request.args.get('limit', 100, type=int)
        logs = access_control.get_audit_logs(limit)
        return jsonify(logs)
    
    @admin_bp.route('/change-password', methods=['POST'])
    def change_password():
        """Change admin password"""
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        data = request.get_json()
        
        old_password = data.get('old_password')
        new_password = data.get('new_password')
        
        if not access_control.is_admin(token):
            return jsonify({"error": "Admin access required"}), 403
        
        success = access_control.change_admin_password(old_password, new_password, token)
        if success:
            return jsonify({"success": True, "message": "Password changed"})
        return jsonify({"error": "Failed to change password"}), 400
    
    # Register blueprint
    app.register_blueprint(admin_bp)

