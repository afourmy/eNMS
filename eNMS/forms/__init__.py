from collections import defaultdict
from flask import request
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms.fields.core import UnboundField
from wtforms.form import FormMeta

from eNMS import app
from eNMS.database import db
from eNMS.forms.fields import (
    BooleanField,
    DictField,
    InstanceField,
    IntegerField,
    JsonField,
    MultipleInstanceField,
    PasswordField,
    SelectField,
    SelectMultipleField,
    StringField,
)
from eNMS.models import property_types, relationships

form_classes = {}
form_properties = defaultdict(dict)


class MetaForm(FormMeta):
    def __new__(cls, name, bases, attrs):
        if name == "BaseForm":
            return type.__new__(cls, name, bases, attrs)
        form_type = attrs["form_type"].kwargs["default"]
        form = type.__new__(cls, name, bases, attrs)
        if form.__dict__.get("get_request_allowed", True):
            app.rbac["get_requests"][f"/{form_type}_form"] = "access"
        if hasattr(form, "form_init"):
            form.form_init()
        if not hasattr(form, "custom_properties"):
            form.custom_properties = {}
        form.custom_properties = {
            **form.custom_properties,
            **app.properties["custom"].get(form_type, {}),
        }
        for property, values in form.custom_properties.items():
            if not values.get("form", True):
                continue
            if property in db.private_properties_set:
                field = PasswordField
            else:
                field = {
                    "boolean": BooleanField,
                    "dict": DictField,
                    "integer": IntegerField,
                    "json": JsonField,
                    "string": StringField,
                    "select": SelectField,
                    "multiselect": SelectMultipleField,
                }[values.get("type", "string")]
            form_kw = {"default": values["default"]} if "default" in values else {}
            if field in (SelectField, SelectMultipleField):
                form_kw["choices"] = values["choices"]
            field = field(values["pretty_name"], **form_kw)
            setattr(form, property, field)
            attrs[property] = field
        form_classes[form_type] = form
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
                app.property_names[field_name] = field.args[0]
            if (
                issubclass(field.field_class, PasswordField)
                and field_name not in db.private_properties_set
            ):
                db.private_properties_set.add(field_name)
        form_properties[form_type].update(properties)
        for property, value in properties.items():
            if property not in property_types and value["type"] != "field-list":
                property_types[property] = value["type"]
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
                form.service_fields.extend(form_properties[base_form_type])
            form_properties[form_type].update(form_properties[base_form_type])
        return form

    def __setattr__(self, field, value):
        if hasattr(value, "field_class") and "multiselect" in value.field_class.type:
            form_type = self.form_type.kwargs["default"]
            form_properties[form_type][field] = {"type": value.field_class.type}
        return super().__setattr__(field, value)


class BaseForm(FlaskForm, metaclass=MetaForm):
    @classmethod
    def configure_relationships(cls, *models):
        form_type = cls.form_type.kwargs["default"]
        for related_model, relation in relationships[form_type].items():
            if related_model not in models:
                continue
            field = MultipleInstanceField if relation["list"] else InstanceField
            field_type = "object-list" if relation["list"] else "object"
            form_properties[form_type][related_model] = {"type": field_type}
            setattr(cls, related_model, field())

    def form_postprocessing(self, form_data):
        data = {**form_data.to_dict(), **{"user": current_user}}
        if request.files:
            data["file"] = request.files["file"]
        for property, field in form_properties[form_data.get("form_type")].items():
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


def choices(iterable):
    return [(choice, choice) for choice in iterable]
