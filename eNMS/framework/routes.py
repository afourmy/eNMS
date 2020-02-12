from flask import (
    abort,
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_user, logout_user
from functools import wraps
from logging import info
from werkzeug.wrappers import Response

from eNMS import app
from eNMS.database import Session
from eNMS.database.functions import fetch, handle_exception
from eNMS.forms import form_actions, form_classes, form_postprocessing, form_templates
from eNMS.forms.administration import LoginForm
from eNMS.setup import properties


blueprint = Blueprint("blueprint", __name__, template_folder="../templates")


@blueprint.route("/")
def site_root():
    return redirect(url_for("blueprint.route", page="login"))


@blueprint.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            user = app.authenticate_user(**request.form.to_dict())
            if user:
                login_user(user)
                return redirect(url_for("blueprint.route", page="dashboard"))
            else:
                abort(403)
        except Exception as e:
            info(f"Authentication failed ({str(e)})")
            abort(403)
    if not current_user.is_authenticated:
        login_form = LoginForm(request.form)
        authentication_methods = [("Local User",) * 2]
        if app.settings["ldap"]["active"]:
            authentication_methods.append(("LDAP Domain",) * 2)
        if app.settings["tacacs"]["active"]:
            authentication_methods.append(("TACACS",) * 2)
        login_form.authentication_method.choices = authentication_methods
        return render_template("login.html", login_form=login_form)
    return redirect(url_for("blueprint.route", page="dashboard"))


def monitor_requests(function):
    @wraps(function)
    def decorated_function(*args, **kwargs):
        path, method = request.path, request.method
        if not current_user.is_authenticated:
            client_address = request.environ.get(
                "HTTP_X_FORWARDED_FOR", request.environ["REMOTE_ADDR"]
            )
            app.log(
                "warning",
                (
                    f"Unauthorized {request.method} request from "
                    f"'{client_address}' calling the endpoint '{request.url}'"
                ),
            )
            return redirect(url_for("blueprint.route", page="login"))
        else:
            endpoint = path if method == "GET" else f"/{path.split('/')[1]}"
            if endpoint not in app.rbac["endpoints"][method]:
                if method == "GET":
                    return render_template("error.html", error=404), 404
                else:
                    return jsonify({"alert": "Invalid POST request."})
            forbidden_endpoints = app.rbac["groups"][current_user.group][method]
            if any(url == endpoint for url in forbidden_endpoints):
                if method == "GET":
                    return render_template("error.html", error=403), 403
                else:
                    return jsonify({"alert": "Error 403 Forbidden."})
            return function(*args, **kwargs)

    return decorated_function


@blueprint.route("/logout")
@monitor_requests
def logout():
    logout_user()
    return redirect(url_for("blueprint.route", page="login"))


@blueprint.route("/dashboard")
@monitor_requests
def dashboard():
    return render_template(
        f"dashboard.html",
        **{"endpoint": "dashboard", "properties": properties["dashboard"]},
    )


@blueprint.route("/table/<table_type>")
@monitor_requests
def table(table_type):
    return render_template(
        f"table.html", **{"endpoint": f"table/{table_type}", "type": table_type}
    )


@blueprint.route("/view/<view_type>")
@monitor_requests
def view(view_type):
    return render_template(
        f"visualization.html", **{"endpoint": "view", "view_type": view_type}
    )


@blueprint.route("/workflow_builder")
@monitor_requests
def workflow_builder():
    return render_template(f"workflow.html", endpoint="workflow_builder")


@blueprint.route("/form/<form_type>")
@monitor_requests
def form(form_type):
    return render_template(
        f"forms/{form_templates.get(form_type, 'base')}.html",
        **{
            "endpoint": f"form/{form_type}",
            "action": form_actions.get(form_type),
            "form": form_classes[form_type](request.form),
            "form_type": form_type,
        },
    )


@blueprint.route("/view_service_results/<int:id>")
@monitor_requests
def view_service_results(id):
    result = fetch("run", id=id).result().result
    return f"<pre>{app.str_dict(result)}</pre>"


@blueprint.route("/download_output/<id>")
@monitor_requests
def download_output(id):
    data = fetch("data", id=id)
    filename = f"{data.device_name}-\
                {data.command}-\
                {app.strip_all(data.runtime)}"
    return Response(
        (f"{line}\n" for line in data.output.splitlines()),
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment;filename={filename}.txt"},
    )


@blueprint.route("/download_file/<path:path>")
@monitor_requests
def download_file(path):
    return send_file(f"/{path}", as_attachment=True)


@blueprint.route("/<path:_>")
@monitor_requests
def get_requests_sink(_):
    abort(404)


@blueprint.route("/", methods=["POST"])
@blueprint.route("/<path:page>", methods=["POST"])
@monitor_requests
def route(page):
    endpoint, *args = page.split("/")
    form_type = request.form.get("form_type")
    if endpoint in app.json_endpoints:
        result = getattr(app, endpoint)(*args, **request.json)
    elif form_type:
        form = form_classes[form_type](request.form)
        if not form.validate_on_submit():
            return jsonify({"invalid_form": True, **{"errors": form.errors}})
        result = getattr(app, endpoint)(
            *args, **form_postprocessing(form, request.form)
        )
    else:
        result = getattr(app, endpoint)(*args)
    try:
        Session.commit()
        return jsonify(result)
    except Exception as exc:
        raise exc
        Session.rollback()
        if app.settings["app"]["config_mode"] == "debug":
            raise
        return jsonify({"alert": handle_exception(str(exc))})
