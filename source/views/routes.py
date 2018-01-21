from base.database import db
from base.properties import pretty_names
from collections import OrderedDict
from flask import Blueprint, current_app, jsonify, render_template, redirect, request, session, url_for
from flask_login import current_user, login_required
from .forms import *
from json import dumps
from objects.models import *
from objects.properties import *
from os.path import join
from tasks.models import *
from simplekml import Color, Kml, Style
from subprocess import Popen

blueprint = Blueprint(
    'views_blueprint', 
    __name__, 
    url_prefix = '/views', 
    template_folder = 'templates',
    static_folder = 'static'
    )

styles = {}

for subtype in node_subtypes:
    point_style = Style()
    point_style.labelstyle.color = Color.blue
    path_icon = join(
        blueprint.root_path,
        'static',
        'images',
        'default',
        '{}.gif'.format(subtype)
        )
    point_style.iconstyle.icon.href = path_icon
    styles[subtype] = point_style
    
for subtype, cls in link_class.items():
    line_style = Style()
    # we convert the RGB color to a KML color, 
    # i.e #RRGGBB to #AABBGGRR
    kml_color = "#ff" + cls.color[-2:] + cls.color[3:5] + cls.color[1:3]
    line_style.linestyle.color = kml_color
    styles[subtype] = line_style

def get_targets(nodes):
    targets = []
    for id in nodes:
        obj = get_obj(db, Node, id=int(id))
        print(obj, obj.name, obj.ip_address, obj.secret_password)
        targets.append((
            obj.name,
            obj.ip_address, 
            obj.operating_system.lower(),
            obj.secret_password
            ))
    return targets

@blueprint.route('/<view_type>_view', methods = ['GET', 'POST'])
@login_required
def view(view_type):
    napalm_configuration_form = NapalmConfigurationForm(request.form)
    napalm_getters_form = NapalmGettersForm(request.form)
    netmiko_form = NetmikoForm(request.form)
    view_options_form = ViewOptionsForm(request.form)
    google_earth_form = GoogleEarthForm(request.form)
    labels = {'node': 'name', 'link': 'name'}
    # update the list of available nodes / script by querying the database
    netmiko_form.script.choices = Script.choices()
    napalm_configuration_form.script.choices = Script.choices()
    if 'netmiko_script' in request.form:
        targets = get_targets(session['selection'])
        task = NetmikoTask(current_user, targets, **netmiko_form.data)
        db.session.add(task)
        db.session.commit()
        return redirect(url_for('tasks_blueprint.task_management'))
    elif 'napalm_configuration' in request.form:
        targets = get_targets(session['selection'])
        task = NapalmConfigTask(current_user, targets, **napalm_configuration_form.data)
        db.session.add(task)
        db.session.commit()
        return redirect(url_for('tasks_blueprint.task_management'))
    elif 'napalm_getters' in request.form:
        targets = get_targets(session['selection'])
        napalm_task = NapalmGettersTask(
            current_user,
            targets,
            **napalm_getters_form.data
            )
        db.session.add(napalm_task)
        db.session.commit()
        return redirect(url_for('tasks_blueprint.task_management'))
    elif 'view_options' in request.form:
        # retrieve labels
        labels = {
            'node': request.form['node_label'],
            'link': request.form['link_label']
            }
    elif 'google_earth' in request.form:
        kml_file = Kml()
        
        for node in filter(lambda obj: obj.visible, Node.query.all()):
            point = kml_file.newpoint(name=node.name)
            point.coords = [(node.longitude, node.latitude)]
            point.style = styles[node.subtype]
            point.style.labelstyle.scale = request.form['label_size']
            
        for link in filter(lambda obj: obj.visible, Link.query.all()):
            line = kml_file.newlinestring(name=link.name) 
            line.coords = [
                (link.source.longitude, link.source.latitude),
                (link.destination.longitude, link.destination.latitude)
                ]
            line.style = styles[link.type]
            line.style.linestyle.width = request.form['line_width']
        
        filepath = join(current_app.kmz_path, request.form['name'] + '.kmz')
        kml_file.save(filepath)
    return render_template(
        '{}_view.html'.format(view_type),
        napalm_configuration_form = napalm_configuration_form,
        napalm_getters_form = napalm_getters_form,
        netmiko_form = netmiko_form,
        view_options_form = view_options_form,
        google_earth_form = google_earth_form,
        labels = labels,
        names = pretty_names,
        subtypes = node_subtypes,
        clusterize = len(Node.query.all()) > 2000,
        node_table = {
            obj: OrderedDict([
                (property, getattr(obj, property)) 
                for property in type_to_public_properties[obj.type]
            ])
            for obj in filter(lambda obj: obj.visible, Node.query.all())
        },
        link_table = {
            obj: OrderedDict([
                (property, getattr(obj, property)) 
                for property in type_to_public_properties[obj.type]
            ])
            for obj in filter(lambda obj: obj.visible, Link.query.all())
        })

@blueprint.route('/putty_connection', methods = ['POST'])
@login_required
def putty_connection():
    node = db.session.query(Node)\
        .filter_by(id=request.form['id'])\
        .first()
    path_putty = join(current_app.path_apps, 'putty.exe')
    ssh_connection = '{} -ssh {}@{} -pw {}'.format(
        path_putty,
        current_user.username,
        node.ip_address,
        current_user.password
        )
    connect = Popen(ssh_connection.split())
    return dumps({'success': True}), 200, {'ContentType': 'application/json'} 

@blueprint.route('/selection', methods = ['POST'])
@login_required
def selection():
    session['selection'] = request.form.getlist('selection[]')
    return dumps({'success': True}), 200, {'ContentType': 'application/json'}
