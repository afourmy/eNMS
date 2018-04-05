from base.database import db
from .forms import DiagramPropertiesForm
from collections import Counter
from flask import Blueprint, jsonify, render_template, redirect, request, url_for
from .properties import pretty_names

import flask_login

blueprint = Blueprint(
    'base_blueprint',
    __name__,
    url_prefix='',
    template_folder='templates'
)

from objects.models import Node, Link
from objects.properties import node_public_properties, link_public_properties
from users.models import User
from users.routes import login_manager

## root of the site


@blueprint.route('/')
def site_root():
    return redirect(url_for('users_blueprint.login'))

## dashboard


@blueprint.route('/dashboard')
@flask_login.login_required
def dashboard():
    # total number of nodes / links / users
    counters = {
        'nodes': len(Node.query.all()),
        'links': len(Link.query.all()),
        'users': len(User.query.all())
    }
    return render_template(
        'dashboard/dashboard.html',
        names=pretty_names,
        node_properties=node_public_properties,
        link_properties=link_public_properties,
        counters=counters
    )


@blueprint.route('/<property>_<type>', methods=['POST'])
@flask_login.login_required
def get_counters(property, type):
    print(type, property)
    objects = Node.query.all() if type == 'node' else Link.query.all()
    return jsonify(Counter(map(lambda o: str(getattr(o, property)), objects)))


@blueprint.route('/dashboard_control', methods=['GET', 'POST'])
@flask_login.login_required
def dashboard_control():
    diagram_properties_form = DiagramPropertiesForm(request.form)
    if request.method == 'POST':
        user = db.session.query(User)\
            .filter_by(name=flask_login.current_user.name)\
            .first()
        user.dashboard_node_properties = str(diagram_properties_form.data['node_properties'])
        user.dashboard_link_properties = str(diagram_properties_form.data['link_properties'])
        db.session.commit()
    return render_template(
        'dashboard/dashboard_control.html',
        diagram_properties_form=diagram_properties_form,
    )


@blueprint.route('/project')
@flask_login.login_required
def project():
    return render_template('about/project.html')

## Errors


@login_manager.unauthorized_handler
def unauthorized_handler():
    return render_template('errors/page_403.html'), 403


@blueprint.errorhandler(403)
def authorization_required(error):
    return render_template('errors/page_403.html'), 403


@blueprint.errorhandler(404)
def not_found_error(error):
    return render_template('errors/page_404.html'), 404


@blueprint.errorhandler(500)
def internal_error(error):
    return render_template('errors/page_500.html'), 500
