from flask import Blueprint, render_template

from routes.decorators import login_required

dashboard = Blueprint('dashboard', __name__)

@dashboard.route('', strict_slashes=False)
@login_required
def dashboard_index():
    return render_template('dashboard/dashboard.html')

@dashboard.route('/change_password', methods=['GET'])
@login_required
def dashboard_change_password():
    return render_template('dashboard/change_password.html')

@dashboard.route('/systems', methods=['GET'])
@login_required
def dashboard_edit_systems():
    return render_template('dashboard/edit_systems.html')

@dashboard.route('/triggers', methods=['GET'])
@login_required
def dashboard_edit_triggers():
    return render_template('dashboard/edit_triggers.html')
