from copy import deepcopy
from flask import request
from flask_login import current_user
from flask_wtf import FlaskForm
from importlib.util import module_from_spec, spec_from_file_location
from wtforms.fields.core import UnboundField
from wtforms.form import FormMeta
from wtforms.validators import InputRequired
from wtforms.widgets import TextArea

from eNMS.database import db
from eNMS.fields import (
    BooleanField,
    HiddenField,
    DictField,
    FloatField,
    InstanceField,
    IntegerField,
    JsonField,
    MultipleInstanceField,
    PasswordField,
    SelectField,
    SelectMultipleField,
    SelectMultipleStringField,
    StringField,
)
from eNMS.variables import vs


class MetaForm(FormMeta):
    def __new__(cls, name, bases, attrs):
        if name == "BaseForm":
            return type.__new__(cls, name, bases, attrs)
        form_type = attrs["form_type"].kwargs["default"]
        form = type.__new__(cls, name, bases, attrs)
        if form.__dict__.get("get_request_allowed", True):
            vs.rbac["get_requests"][f"/{form_type}_form"] = "access"
        if hasattr(form, "form_init"):
            form.form_init()
        if not hasattr(form, "custom_properties"):
            form.custom_properties = {}
        form.custom_properties = {
            **form.custom_properties,
            **vs.properties["custom"].get(form_type, {}),
        }
        for property, values in form.custom_properties.items():
            if not values.get("form", True):
                continue
            if property in vs.private_properties_set:
                field = PasswordField
            else:
                field = {
                    "bool": BooleanField,
                    "dict": DictField,
                    "integer": IntegerField,
                    "json": JsonField,
                    "str": StringField,
                    "select": SelectField,
                    "multiselect": SelectMultipleField,
                }[values.get("type", "str")]
            form_kw = {"default": values["default"]} if "default" in values else {}
            if field in (SelectField, SelectMultipleField):
                form_kw["choices"] = values["choices"]
            field = field(values["pretty_name"], **form_kw)
            setattr(form, property, field)
            attrs[property] = field
        vs.form_class[form_type] = form
        properties = {}
        for field_name, field in attrs.items():
            if not isinstance(field, UnboundField):
                continue
            field_type = field.kwargs.pop("type", None)
            if not field_type:
                field_type = field.field_class.type
            properties[field_name] = {
                "type": field_type,
                "model": field.kwargs.pop("model", None),
            }
            if field.args and isinstance(field.args[0], str):
                vs.property_names[field_name] = field.args[0]
            if (
                issubclass(field.field_class, PasswordField)
                and field_name not in vs.private_properties_set
            ):
                vs.private_properties_set.add(field_name)
        vs.form_properties[form_type].update(properties)
        for base in form.__bases__:
            if not hasattr(base, "form_type"):
                continue
            base_form_type = base.form_type.kwargs["default"]
            form.custom_properties.update(base.custom_properties)
            if base_form_type == "service":
                form.service_fields = [
                    property
                    for property in properties
                    if property not in form.custom_properties
                ]
            if getattr(base, "abstract_service", False):
                form.service_fields.extend(vs.form_properties[base_form_type])
            vs.form_properties[form_type].update(vs.form_properties[base_form_type])
        return form

    def __setattr__(self, field, value):
        if hasattr(value, "field_class") and "multiselect" in value.field_class.type:
            form_type = self.form_type.kwargs["default"]
            vs.form_properties[form_type][field] = {"type": value.field_class.type}
        return super().__setattr__(field, value)


class BaseForm(FlaskForm, metaclass=MetaForm):
    def form_postprocessing(self, form_data):
        data = {"user": current_user, **form_data.to_dict()}
        if request.files:
            data["file"] = request.files["file"]
        for property, field in vs.form_properties[form_data.get("form_type")].items():
            if field["type"] in ("object-list", "multiselect", "multiselect-string"):
                value = form_data.getlist(property)
                if field["type"] == "multiselect-string":
                    value = str(value)
                data[property] = value
            elif field["type"] == "object":
                data[property] = form_data.get(property)
            elif field["type"] == "field-list":
                data[property] = []
                for entry in getattr(self, property):
                    properties = entry.data
                    properties.pop("csrf_token")
                    data[property].append(properties)
            elif field["type"] == "bool":
                data[property] = property in form_data
            elif field["type"] in db.field_conversion and property in data:
                data[property] = db.field_conversion[field["type"]](form_data[property])
        return data


class FormFactory:
    def _initialize(self):
        self.generate_filtering_forms()
        self.generate_instance_insertion_forms()
        self.generate_service_forms()

    def generate_filtering_forms(self):
        for model in ("device", "link", "pool", "run", "service", "task", "user"):
            properties, relations = vs.properties["filtering"].get(model, []), {}
            for related_model, relation in vs.relationships[model].items():
                if related_model in ("edges", "results"):
                    continue
                relations[related_model] = MultipleInstanceField(related_model)
                vs.relationships[f"{model}_filtering"][related_model] = relation
                filtering_key = f"{model}_relation_filtering"
                vs.relationships[filtering_key][related_model] = relation
            relation_form = {
                "template": "filtering",
                "properties": sorted(relations),
                "object_type": model,
                "form_type": HiddenField(default=f"{model}_relation_filtering"),
                **{
                    **relations,
                    **{
                        f"{relation}_filter": SelectField(
                            choices=(
                                ("union", "Union"),
                                ("intersection", "Intersection"),
                                ("empty", "Empty"),
                            )
                        )
                        for relation in relations
                    },
                },
            }
            type(f"{model}RelationshipFilteringForm", (BaseForm,), relation_form)
            form, form_type = deepcopy(relation_form), f"{model}_filtering"
            for property in properties:
                vs.form_properties[form_type][f"{property}_filter"] = {"type": "list"}
            form.update(
                {
                    "form_type": HiddenField(default=form_type),
                    "properties": sorted(properties) + sorted(relations),
                    **{property: StringField() for property in properties},
                    **{
                        f"{property}_filter": SelectField(
                            choices=(
                                ("inclusion", "Inclusion"),
                                ("equality", "Equality"),
                                ("regex", "Regular Expression"),
                                ("empty", "Empty"),
                            )
                        )
                        for property in properties
                    },
                }
            )
            type(f"{model}FilteringForm", (BaseForm,), form)

    def generate_instance_insertion_forms(self):
        for model in ("device", "link", "user", "service"):
            vs.relationships[f"add_{model}s"]["instances"] = {
                "type": "object-list",
                "model": model,
            }
            type(
                f"{model}RelationshipFilteringForm",
                (BaseForm,),
                {
                    "form_type": HiddenField(default=f"add_{model}s"),
                    "action": "eNMS.base.addInstancesToRelation",
                    "model": HiddenField(default=model),
                    "relation_id": HiddenField(),
                    "relation_type": HiddenField(),
                    "property": HiddenField(),
                    "instances": MultipleInstanceField(f"{model}s", model=model),
                    "names": StringField(widget=TextArea(), render_kw={"rows": 8}),
                },
            )

    def generate_service_forms(self):
        for file in (vs.path / "eNMS" / "forms").glob("**/*.py"):
            spec = spec_from_file_location(str(file).split("/")[-1][:-3], str(file))
            spec.loader.exec_module(module_from_spec(spec))


class AddObjectsForm(BaseForm):
    form_type = HiddenField(default="add_objects_to_view")
    action = "eNMS.visualization.addObjectsToView"
    devices = MultipleInstanceField("Devices", model="device")
    links = MultipleInstanceField("Links", model="link")


class AddServiceForm(BaseForm):
    form_type = HiddenField(default="add_services_to_workflow")
    template = "add_services_to_workflow"
    mode = SelectField(
        "Mode",
        choices=(
            ("deep", "Deep Copy (creates a duplicate from the service)"),
            ("shallow", "Shallow Copy (creates a reference to the service)"),
        ),
    )
    search = StringField()


class AdminForm(BaseForm):
    template = "administration"
    form_type = HiddenField(default="administration")


class ChangelogForm(BaseForm):
    action = "eNMS.base.processData"
    form_type = HiddenField(default="changelog")
    id = HiddenField()
    severity = SelectField(
        "Severity",
        choices=(
            ("debug", "Debug"),
            ("info", "Info"),
            ("warning", "Warning"),
            ("error", "Error"),
            ("critical", "Critical"),
        ),
    )
    content = StringField(widget=TextArea(), render_kw={"rows": 10})


class CredentialForm(BaseForm):
    action = "eNMS.base.processData"
    form_type = HiddenField(default="credential")
    id = HiddenField()
    name = StringField("Name", [InputRequired()])
    description = StringField(widget=TextArea(), render_kw={"rows": 6})
    role = SelectField(
        "Role",
        choices=(
            ("read-write", "Read Write"),
            ("read-only", "Read Only"),
        ),
    )
    subtype = SelectField(
        "Subtype",
        choices=(("password", "Username / Password"), ("key", "SSH Key")),
    )
    device_pools = MultipleInstanceField("Devices", model="pool")
    user_pools = MultipleInstanceField("Users", model="pool")
    priority = IntegerField("Priority", default=1)
    username = StringField("Username")
    password = PasswordField("Password")
    private_key = StringField(widget=TextArea(), render_kw={"rows": 1})
    enable_password = PasswordField("'Enable' Password")


class DatabaseDeletionForm(BaseForm):
    action = "eNMS.administration.databaseDeletion"
    form_type = HiddenField(default="database_deletion")
    deletion_choices = vs.dualize(db.import_export_models)
    deletion_types = SelectMultipleField(
        "Instances to delete", choices=deletion_choices
    )


class DatabaseMigrationsForm(BaseForm):
    template = "database_migration"
    form_type = HiddenField(default="database_migration")
    empty_database_before_import = BooleanField("Empty Database before Import")
    skip_pool_update = BooleanField(
        "Skip the Pool update after Import", default="checked"
    )
    export_private_properties = BooleanField(
        "Include private properties", default="checked"
    )
    export_choices = vs.dualize(db.import_export_models)
    import_export_types = SelectMultipleField(
        "Instances to migrate", choices=export_choices
    )


class DebugForm(BaseForm):
    template = "debug"
    form_type = HiddenField(default="debug")
    snippets = SelectField(validate_choice=False)
    code = StringField(
        "Python Code",
        type="code",
        python=True,
        widget=TextArea(),
        render_kw={"rows": 15},
    )
    output = StringField("Output", widget=TextArea(), render_kw={"rows": 16})


class DeviceConnectionForm(BaseForm):
    template = "device_connection"
    form_type = HiddenField(default="device_connection")
    address_choices = [("ip_address", "IP address"), ("name", "Name")] + [
        (property, values["pretty_name"])
        for property, values in vs.properties["custom"]["device"].items()
        if values.get("is_address", False)
    ]
    address = SelectField(choices=address_choices)
    username = StringField("Username")
    password = PasswordField("Password")


class DeviceDataForm(BaseForm):
    template = "device_data"
    form_type = HiddenField(default="device_data")
    data_type = SelectField("Display", choices=vs.configuration_properties)


class ExcelExportForm(BaseForm):
    action = "eNMS.inventory.exportTopology"
    form_type = HiddenField(default="excel_export")
    export_filename = StringField("Filename")


class ExcelImportForm(BaseForm):
    template = "topology_import"
    form_type = HiddenField(default="excel_import")
    replace = BooleanField("Replace Existing Topology")


class FileForm(BaseForm):
    template = "file"
    form_type = HiddenField(default="file")
    file_content = StringField(widget=TextArea(), render_kw={"rows": 8})


class ImportService(BaseForm):
    action = "eNMS.administration.importService"
    form_type = HiddenField(default="import_service")
    service = SelectField("Service", choices=())


class LogicalViewForm(BaseForm):
    action = "eNMS.base.processData"
    form_type = HiddenField(default="view")
    id = HiddenField()
    name = StringField("Name", [InputRequired()])


class LoginForm(BaseForm):
    form_type = HiddenField(default="login")
    get_request_allowed = False
    authentication_method = SelectField(
        "Authentication Method",
        choices=[
            (method, properties["display_name"])
            for method, properties in vs.settings["authentication"]["methods"].items()
            if properties["enabled"]
        ],
    )
    username = StringField("Name", [InputRequired()])
    password = PasswordField("Password", [InputRequired()])


class ObjectForm(BaseForm):
    action = "eNMS.base.processData"
    form_type = HiddenField(default="object")
    get_request_allowed = False
    id = HiddenField()
    name = StringField("Name", [InputRequired()])
    access_groups = StringField("Groups")
    description = StringField("Description")
    subtype = StringField("Subtype")
    location = StringField("Location")
    vendor = StringField("Vendor")
    model = StringField("Model")


class PoolForm(BaseForm):
    template = "pool"
    form_type = HiddenField(default="pool")
    id = HiddenField()
    name = StringField("Name", [InputRequired()])
    admin_only = BooleanField("Pool visible to admin users only")
    access_groups = StringField("Groups")
    description = StringField("Description")
    manually_defined = BooleanField("Manually defined (won't be automatically updated)")

    @classmethod
    def form_init(cls):
        cls.models = ("device", "link", "service", "user")
        for model in cls.models:
            setattr(cls, f"{model}_properties", vs.properties["filtering"][model])
            for property in vs.properties["filtering"][model]:
                setattr(cls, f"{model}_{property}", StringField(property))
                setattr(cls, f"{model}_{property}_invert", BooleanField(property))
                vs.form_properties["pool"][f"{model}_{property}_match"] = {
                    "type": "list"
                }
                vs.form_properties["pool"][f"{model}_{property}_invert"] = {
                    "type": "bool"
                }
                setattr(
                    cls,
                    f"{model}_{property}_match",
                    SelectField(
                        choices=(
                            ("inclusion", "Inclusion"),
                            ("equality", "Equality"),
                            ("regex", "Regular Expression"),
                            ("empty", "Empty"),
                        )
                    ),
                )


class RbacForm(BaseForm):
    action = "eNMS.base.processData"
    form_type = HiddenField(default="rbac")
    get_request_allowed = False
    id = HiddenField()
    name = StringField("Name", [InputRequired()])
    description = StringField(widget=TextArea(), render_kw={"rows": 6})
    email = StringField("Email")


class RestartWorkflowForm(BaseForm):
    action = "eNMS.workflow.restartWorkflow"
    form_type = HiddenField(default="restart_workflow")
    start_services = HiddenField()
    restart_runtime = SelectField("Restart Runtime", validate_choice=False)


class ResultLogDeletionForm(BaseForm):
    action = "eNMS.administration.resultLogDeletion"
    form_type = HiddenField(default="result_log_deletion")
    deletion_types = SelectMultipleField(
        "Instances do delete",
        choices=[("run", "result"), ("changelog", "changelog")],
    )
    date_time = StringField(type="date", label="Delete Records before")


class RunServiceForm(BaseForm):
    action = "eNMS.automation.runServicesOnTargets"
    button_label = "Run Service"
    button_class = "primary"
    form_type = HiddenField(default="run_service")
    targets = HiddenField()
    type = HiddenField()
    service = InstanceField("Services", model="service")


class ServerForm(BaseForm):
    action = "eNMS.base.processData"
    form_type = HiddenField(default="server")
    id = HiddenField()
    name = StringField("Name", [InputRequired()])
    description = StringField(widget=TextArea(), render_kw={"rows": 6})
    ip_address = StringField("IP address")
    weight = IntegerField("Weigth", default=1)


class ServiceForm(BaseForm):
    template = "service"
    form_type = HiddenField(default="service")
    get_request_allowed = False
    id = HiddenField()
    name = StringField("Name")
    type = StringField("Service Type")
    access_groups = StringField("Groups")
    shared = BooleanField("Shared")
    scoped_name = StringField("Scoped Name", [InputRequired()])
    description = StringField("Description")
    device_query = StringField(
        "Device Query", python=True, widget=TextArea(), render_kw={"rows": 2}
    )
    device_query_property = SelectField(
        "Query Property Type", choices=(("name", "Name"), ("ip_address", "IP address"))
    )
    target_devices = MultipleInstanceField("Devices")
    disable_result_creation = BooleanField("Save only failed results")
    target_pools = MultipleInstanceField("Pools")
    update_target_pools = BooleanField("Update target pools before running")
    update_pools_after_running = BooleanField("Update pools after running")
    workflows = MultipleInstanceField("Workflows")
    waiting_time = IntegerField(
        "Time to Wait before next service is started (in seconds)", default=0
    )
    priority = IntegerField("Priority", default=1)
    send_notification = BooleanField("Send a notification")
    send_notification_method = SelectField(
        "Notification Method",
        choices=(("mail", "Mail"), ("slack", "Slack"), ("mattermost", "Mattermost")),
    )
    notification_header = StringField(
        widget=TextArea(), render_kw={"rows": 5}, substitution=True
    )
    include_device_results = BooleanField("Include Device Results")
    include_link_in_summary = BooleanField("Include Result Link in Summary")
    display_only_failed_nodes = BooleanField("Display only Failed Devices")
    mail_recipient = StringField("Mail Recipients (separated by comma)")
    reply_to = StringField("Reply-to Email Address")
    number_of_retries = IntegerField("Number of retries", default=0)
    time_between_retries = IntegerField("Time between retries (in seconds)", default=10)
    max_number_of_retries = IntegerField("Maximum number of retries", default=100)
    credential_type = SelectField(
        "Type of Credentials",
        choices=(
            ("any", "Any"),
            ("read-write", "Read Write"),
            ("read-only", "Read Only"),
        ),
    )
    maximum_runs = IntegerField("Maximum number of runs", default=1)
    skip_query = StringField(
        "Skip Query (Python)", python=True, widget=TextArea(), render_kw={"rows": 2}
    )
    skip_value = SelectField(
        "Skip Value",
        choices=(
            ("success", "Success"),
            ("failure", "Failure"),
            ("discard", "Discard"),
        ),
    )
    vendor = StringField("Vendor")
    operating_system = StringField("Operating System")
    iteration_values = StringField("Iteration Values", python=True)
    initial_payload = DictField()
    iteration_variable_name = StringField(
        "Iteration Variable Name", default="iteration_value"
    )
    iteration_devices = StringField("Iteration Devices", python=True)
    iteration_devices_property = SelectField(
        "Iteration Devices Property",
        choices=(("name", "Name"), ("ip_address", "IP address")),
    )
    preprocessing = StringField(type="code", python=True, widget=TextArea())
    postprocessing = StringField(type="code", python=True, widget=TextArea())
    postprocessing_mode = SelectField(
        choices=(
            ("always", "Always run"),
            ("success", "Run on success only"),
            ("failure", "Run on failure only"),
        )
    )
    default_access = SelectField(
        choices=(
            ("creator", "Creator only"),
            ("public", "Public (all users)"),
            ("admin", "Admin Users only"),
        )
    )
    log_level = SelectField(
        "Logging",
        choices=((0, "Disable logging"), *enumerate(vs.log_levels, 1)),
        default=1,
    )
    multiprocessing = BooleanField("Multiprocessing")
    max_processes = IntegerField("Maximum number of processes", default=15)
    validation_condition = SelectField(
        choices=(
            ("none", "No validation"),
            ("success", "Run on success only"),
            ("failure", "Run on failure only"),
            ("always", "Always run"),
        )
    )
    conversion_method = SelectField(
        choices=(
            ("none", "No conversion"),
            ("text", "Text"),
            ("json", "Json dictionary"),
            ("xml", "XML dictionary"),
        )
    )
    validation_method = SelectField(
        "Validation Method",
        choices=(
            ("text", "Validation by text match"),
            ("dict_included", "Validation by dictionary inclusion"),
            ("dict_equal", "Validation by dictionary equality"),
        ),
    )
    content_match = StringField(
        "Content Match", widget=TextArea(), render_kw={"rows": 8}, substitution=True
    )
    content_match_regex = BooleanField('"Content Match" is a regular expression')
    dict_match = DictField("Dictionary to Match Against", substitution=True)
    negative_logic = BooleanField("Negative logic")
    delete_spaces_before_matching = BooleanField("Delete Spaces before Matching")
    run_method = SelectField(
        "Run Method",
        choices=(
            ("per_device", "Run the service once per device"),
            ("once", "Run the service once"),
        ),
    )

    def validate(self):
        valid_form = super().validate()
        no_recipient_error = (
            self.send_notification.data
            and self.send_notification_method.data == "mail"
            and not self.mail_recipient.data
        )
        if no_recipient_error:
            self.mail_recipient.errors.append(
                "Please add at least one recipient for the mail notification."
            )
        forbidden_name_error = self.scoped_name.data in ("Start", "End", "Placeholder")
        if forbidden_name_error:
            self.name.errors.append("This name is not allowed.")
        conversion_validation_mismatch = self.validation_condition.data != "none" and (
            self.conversion_method.data == "text"
            and "dict" in self.validation_method.data
            or self.conversion_method.data in ("xml", "json")
            and "dict" not in self.validation_method.data
        )
        if conversion_validation_mismatch:
            self.conversion_method.errors.append(
                f"The conversion method is set to {self.conversion_method.data}"
                f" and the validation method to {self.validation_method.data} :"
                " these do not match."
            )
        empty_validation = self.validation_condition.data != "none" and (
            self.validation_method.data == "text"
            and not self.content_match.data
            or self.validation_method.data == "dict_included"
            and self.dict_match.data == "{}"
        )
        if empty_validation:
            self.content_match.errors.append(
                f"The validation method is set to '{self.validation_method.data}'"
                f" and the matching value is empty: these do no match."
            )
        too_many_threads_error = (
            self.max_processes.data > vs.settings["automation"]["max_process"]
        )
        if too_many_threads_error:
            self.max_processes.errors.append(
                "The number of threads used for multiprocessing must be "
                f"less than {vs.settings['automation']['max_process']}."
            )
        shared_service_error = not self.shared.data and len(self.workflows.data) > 1
        if shared_service_error:
            self.shared.errors.append(
                "The 'shared' property is unticked, but the service belongs"
                " to more than one workflow: this is incompatible."
            )
        return (
            valid_form
            and not conversion_validation_mismatch
            and not empty_validation
            and not forbidden_name_error
            and not no_recipient_error
            and not shared_service_error
            and not too_many_threads_error
        )


class SettingsForm(BaseForm):
    form_type = HiddenField(default="settings_panel")
    action = "eNMS.administration.saveSettings"
    settings = JsonField("Settings")
    write_changes = BooleanField("Write changes back to 'settings.json' file")


class TaskForm(BaseForm):
    action = "eNMS.base.processData"
    form_type = HiddenField(default="task")
    id = HiddenField()
    name = StringField("Name", [InputRequired()])
    default_access = SelectField(
        choices=(
            ("creator", "Creator only"),
            ("public", "Public (all users)"),
            ("admin", "Admin Users only"),
        )
    )
    scheduling_mode = SelectField(
        "Scheduling Mode",
        choices=(("cron", "Crontab Scheduling"), ("standard", "Standard Scheduling")),
    )
    description = StringField("Description")
    start_date = StringField("Start Date", type="date")
    end_date = StringField("End Date", type="date")
    frequency = IntegerField("Frequency", default=0)
    frequency_unit = SelectField(
        "Frequency Unit",
        choices=(
            ("seconds", "Seconds"),
            ("minutes", "Minutes"),
            ("hours", "Hours"),
            ("days", "Days"),
        ),
    )
    crontab_expression = StringField("Crontab Expression")
    initial_payload = DictField("Payload")
    devices = MultipleInstanceField("Devices", model="device")
    pools = MultipleInstanceField("Pools", model="pool")
    service = InstanceField("Service", model="service")

    def validate(self):
        valid_form = super().validate()
        if self.name.data == "Bulk Edit":
            return valid_form
        no_date = self.scheduling_mode.data == "standard" and not self.start_date.data
        if no_date:
            self.start_date.errors.append("A start date must be set.")
        no_cron_expression = (
            self.scheduling_mode.data == "cron" and not self.crontab_expression.data
        )
        if no_cron_expression:
            self.crontab_expression.errors.append("A crontab expression must be set.")
        no_service = not self.service.data
        if no_service:
            self.service.errors.append("No service set.")
        return valid_form and not any([no_date, no_cron_expression, no_service])


class UploadFilesForm(BaseForm):
    template = "upload_files"
    folder = HiddenField()
    form_type = HiddenField(default="upload_files")


class ViewLabelForm(BaseForm):
    form_type = HiddenField(default="view_label")
    action = "eNMS.visualization.createLabel"
    text = StringField(widget=TextArea(), render_kw={"rows": 15})


class ViewPlanForm(BaseForm):
    form_type = HiddenField(default="view_plan")
    action = "eNMS.visualization.createPlan"
    name = StringField("Name", [InputRequired()])
    size = IntegerField("Size", default=2000)
    rows = IntegerField("Number of Rows", default=100)
    opacity = FloatField("Opacity", default=1.0)


class WorkflowLabelForm(BaseForm):
    form_type = HiddenField(default="workflow_label")
    action = "eNMS.workflow.createLabel"
    text = StringField(widget=TextArea(), render_kw={"rows": 15})
    alignment = SelectField(
        "Text Alignment",
        choices=(("left", "Left"), ("center", "Center"), ("right", "Right")),
    )


class WorkflowEdgeForm(BaseForm):
    action = "eNMS.base.processData"
    form_type = HiddenField(default="workflow_edge")
    id = HiddenField()
    label = StringField()
    color = StringField()


class AccessForm(RbacForm):
    template = "access"
    form_type = HiddenField(default="access")
    user_pools = MultipleInstanceField("pool")
    access_pools = MultipleInstanceField("pool")
    access_type = SelectMultipleStringField(
        "Access Type",
        choices=vs.dualize(
            ["Read", "Edit", "Run", "Schedule", "Connect", "Use as target"]
        ),
    )
    relations = ["pools", "services"]

    @classmethod
    def form_init(cls):
        keys = (
            "get_requests",
            "post_requests",
            "delete_requests",
            "upper_menu",
        )
        for key in keys:
            values = [(k, k) for k, v in vs.rbac[key].items() if v == "access"]
            field_name = " ".join(key.split("_")).capitalize()
            setattr(cls, key, SelectMultipleField(field_name, choices=values))
        menus, pages = [], []
        for category, values in vs.rbac["menu"].items():
            if values["rbac"] == "admin":
                continue
            if values["rbac"] == "access":
                menus.append(category)
            for page, page_values in values["pages"].items():
                if page_values["rbac"] == "admin":
                    continue
                if page_values["rbac"] == "access":
                    pages.append(page)
                subpages = page_values.get("subpages", {})
                for subpage, subpage_values in subpages.items():
                    if subpage_values["rbac"] == "admin":
                        continue
                    if subpage_values["rbac"] == "access":
                        pages.append(subpage)
        menu_choices = vs.dualize(menus)
        setattr(cls, "menu", SelectMultipleField("Menu", choices=menu_choices))
        page_choices = vs.dualize(pages)
        setattr(cls, "pages", SelectMultipleField("Pages", choices=page_choices))


class ConnectionForm(ServiceForm):
    form_type = HiddenField(default="connection")
    get_request_allowed = False
    abstract_service = True
    credentials = SelectField(
        "Credentials",
        choices=(
            ("device", "Device Credentials"),
            ("user", "User Credentials"),
            ("custom", "Custom Credentials"),
        ),
    )
    custom_username = StringField("Custom Username", substitution=True)
    custom_password = PasswordField("Custom Password", substitution=True)
    start_new_connection = BooleanField("Start New Connection")
    close_connection = BooleanField("Close Connection")
    groups = {
        "Connection Parameters": {
            "commands": [
                "credentials",
                "custom_username",
                "custom_password",
                "start_new_connection",
                "close_connection",
            ],
            "default": "expanded",
        }
    }


class DeviceForm(ObjectForm):
    form_type = HiddenField(default="device")
    icon = SelectField(
        "Icon",
        choices=(
            ("antenna", "Antenna"),
            ("firewall", "Firewall"),
            ("host", "Host"),
            ("optical_switch", "Optical switch"),
            ("regenerator", "Regenerator"),
            ("router", "Router"),
            ("server", "Server"),
            ("switch", "Switch"),
        ),
    )
    ip_address = StringField("IP address")
    port = IntegerField("Port", default=22)
    operating_system = StringField("Operating System")
    os_version = StringField("OS Version")
    longitude = StringField("Longitude", default=0.0)
    latitude = StringField("Latitude", default=0.0)
    napalm_driver = SelectField(
        "NAPALM Driver", choices=vs.napalm_drivers, default="ios"
    )
    netmiko_driver = SelectField(
        "Netmiko Driver", choices=vs.netmiko_drivers, default="cisco_ios"
    )
    scrapli_driver = SelectField(
        "Scrapli Driver",
        choices=vs.dualize(vs.scrapli_drivers),
        default="cisco_iosxe",
    )


class LinkForm(ObjectForm):
    action = "eNMS.base.processData"
    form_type = HiddenField(default="link")
    source = InstanceField("Source", model="device")
    destination = InstanceField("Destination", model="device")
    color = StringField("Color")


class NapalmForm(ConnectionForm):
    form_type = HiddenField(default="napalm")
    get_request_allowed = False
    abstract_service = True
    driver = SelectField(choices=vs.napalm_drivers)
    use_device_driver = BooleanField(
        default=True,
        help="napalm/use_device_driver",
    ))
    timeout = IntegerField(default=10)
    optional_args = DictField()
    groups = {
        "Napalm Parameters": {
            "commands": ["driver", "use_device_driver", "timeout", "optional_args"],
            "default": "expanded",
        },
        **ConnectionForm.groups,
    }


class NetmikoForm(ConnectionForm):
    form_type = HiddenField(default="netmiko")
    abstract_service = True
    driver = SelectField(choices=vs.netmiko_drivers)
    use_device_driver = BooleanField(
        default=True,
        help="netmiko/use_device_driver",
    )
    enable_mode = BooleanField(
        "Enable mode (run in enable mode or as root)", default=True
    )
    config_mode = BooleanField("Config mode", default=False)
    fast_cli = BooleanField()
    timeout = FloatField(default=10.0)
    delay_factor = FloatField(
        (
            "Delay Factor (Changing from default of 1"
            " will nullify Netmiko Timeout setting)"
        ),
        default=1.0,
    )
    global_delay_factor = FloatField(
        (
            "Global Delay Factor (Changing from default of 1"
            " will nullify Netmiko Timeout setting)"
        ),
        default=1.0,
    )
    jump_on_connect = BooleanField(
        "Jump to remote device on connect",
        default=False,
        help="netmiko/jump_on_connect",
    )
    jump_command = StringField(
        label="Command that jumps to device",
        default="ssh jump_server_IP",
        substitution=True,
        help="netmiko/jump_command",
    )
    jump_username = StringField(
        label="Device username", substitution=True, help="netmiko/jump_username"
    )
    jump_password = PasswordField(
        label="Device password", substitution=True, help="netmiko/jump_password"
    )
    exit_command = StringField(
        label="Command to exit device back to original device",
        default="exit",
        substitution=True,
        help="netmiko/exit_command",
    )
    expect_username_prompt = StringField(
        "Expected username prompt",
        default="username:",
        substitution=True,
        help="netmiko/expect_username_prompt",
    )
    expect_password_prompt = StringField(
        "Expected password prompt",
        default="password",
        substitution=True,
        help="netmiko/expect_password_prompt",
    )
    expect_prompt = StringField(
        "Expected prompt after login",
        default="admin.*$",
        substitution=True,
        help="netmiko/expect_prompt",
    )
    groups = {
        "Netmiko Parameters": {
            "commands": [
                "driver",
                "use_device_driver",
                "enable_mode",
                "config_mode",
                "fast_cli",
                "timeout",
                "delay_factor",
                "global_delay_factor",
            ],
            "default": "expanded",
        },
        **ConnectionForm.groups,
        "Jump on connect Parameters": {
            "commands": [
                "jump_on_connect",
                "jump_command",
                "expect_username_prompt",
                "jump_username",
                "expect_password_prompt",
                "jump_password",
                "expect_prompt",
                "exit_command",
            ],
            "default": "hidden",
        },
    }


class UserForm(RbacForm):
    form_type = HiddenField(default="user")
    groups = StringField("Groups")
    theme = SelectField(
        "Theme",
        choices=[
            (theme, values["name"]) for theme, values in vs.themes["themes"].items()
        ],
    )
    authentication = SelectField(
        "Authentication",
        choices=[
            (method, values["display_name"])
            for method, values in vs.settings["authentication"]["methods"].items()
        ],
    )
    password = PasswordField("Password")
    is_admin = BooleanField(default=False)


form_factory = FormFactory()
