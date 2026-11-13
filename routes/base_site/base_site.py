from flask import Blueprint, request, jsonify, flash, redirect, url_for, render_template, current_app, session, abort

base_site = Blueprint('base_site', __name__)


def safe_next(target):
    """Only allow redirects back to a page on this site (blocks //evil.com and similar)."""
    if target and target.startswith("/") and not target.startswith(("//", "/\\")):
        return target
    return None


@base_site.route('/')
def base_site_index():
    # No public homepage: go straight to the dashboard, or to the login page
    if session.get('authenticated'):
        return redirect(url_for('dashboard.dashboard_index'))
    return redirect(url_for('base_site.base_site_login'))

@base_site.route('/favicon.ico')
def base_site_favicon():
    # Browsers ask for /favicon.ico on their own; point them at the real icon
    return redirect(url_for('static', filename='img/fav_icon/favicon.ico'), code=301)

@base_site.route('/login')
def base_site_login():
    if session.get('authenticated'):
        return redirect(safe_next(request.args.get('next')) or url_for('dashboard.dashboard_index'))
    return render_template('base_site/login.html')
