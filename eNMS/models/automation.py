from builtins import __dict__ as builtins
from copy import deepcopy
from datetime import datetime
from functools import partial
from importlib import __import__ as importlib_import
from io import BytesIO, StringIO
from json import dump, load, loads
from json.decoder import JSONDecodeError
from multiprocessing.pool import ThreadPool
from napalm import get_network_driver
from ncclient import manager
from netmiko import ConnectHandler
from os import getenv
from paramiko import RSAKey, SFTPClient
from re import compile, search
from requests import post
from scp import SCPClient
from sqlalchemy import Boolean, ForeignKey, Index, Integer, or_
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import aliased, relationship
from threading import Thread
from time import sleep
from traceback import format_exc
from warnings import warn
from xmltodict import parse
from xml.parsers.expat import ExpatError

try:
    from scrapli import Scrapli
except ImportError as exc:
    warn(f"Couldn't import scrapli module ({exc})")

try:
    from slackclient import SlackClient
except ImportError as exc:
    warn(f"Couldn't import slackclient module ({exc})")

from eNMS import app
from eNMS.database import db
from eNMS.models.base import AbstractBase
from eNMS.models import models
from eNMS.models.inventory import Device  # noqa: F401
from eNMS.models.scheduling import Task  # noqa: F401
from eNMS.models.administration import User  # noqa: F401


class Service(AbstractBase):

    __tablename__ = class_type = "service"
    pool_model = True
    type = db.Column(db.SmallString)
    __mapper_args__ = {"polymorphic_identity": "service", "polymorphic_on": type}
    id = db.Column(Integer, primary_key=True)
    name = db.Column(db.SmallString, unique=True)
    creator = db.Column(db.SmallString)
    access_groups = db.Column(db.LargeString)
    default_access = db.Column(db.SmallString)
    shared = db.Column(Boolean, default=False)
    scoped_name = db.Column(db.SmallString, index=True)
    last_modified = db.Column(db.TinyString, info={"log_change": False})
    description = db.Column(db.LargeString)
    number_of_retries = db.Column(Integer, default=0)
    time_between_retries = db.Column(Integer, default=10)
    max_number_of_retries = db.Column(Integer, default=100)
    credential_type = db.Column(db.SmallString, default="any")
    positions = db.Column(db.Dict, info={"log_change": False})
    disable_result_creation = db.Column(Boolean, default=False)
    tasks = relationship("Task", back_populates="service", cascade="all,delete")
    events = relationship("Event", back_populates="service", cascade="all,delete")
    vendor = db.Column(db.SmallString)
    operating_system = db.Column(db.SmallString)
    waiting_time = db.Column(Integer, default=0)
    workflows = relationship(
        "Workflow", secondary=db.service_workflow_table, back_populates="services"
    )
    device_query = db.Column(db.LargeString)
    device_query_property = db.Column(db.SmallString, default="ip_address")
    target_devices = relationship(
        "Device",
        secondary=db.service_target_device_table,
        back_populates="target_services",
    )
    target_pools = relationship(
        "Pool", secondary=db.service_target_pool_table, back_populates="target_services"
    )
    pools = relationship(
        "Pool", secondary=db.pool_service_table, back_populates="services"
    )
    update_target_pools = db.Column(Boolean, default=False)
    update_pools_after_running = db.Column(Boolean, default=False)
    send_notification = db.Column(Boolean, default=False)
    send_notification_method = db.Column(db.TinyString, default="mail")
    notification_header = db.Column(db.LargeString)
    display_only_failed_nodes = db.Column(Boolean, default=True)
    include_device_results = db.Column(Boolean, default=True)
    include_link_in_summary = db.Column(Boolean, default=True)
    mail_recipient = db.Column(db.SmallString)
    reply_to = db.Column(db.SmallString)
    initial_payload = db.Column(db.Dict)
    skip = db.Column(db.Dict)
    skip_query = db.Column(db.LargeString)
    skip_value = db.Column(db.SmallString, default="True")
    iteration_values = db.Column(db.LargeString)
    iteration_variable_name = db.Column(db.SmallString, default="iteration_value")
    iteration_devices = db.Column(db.LargeString)
    iteration_devices_property = db.Column(db.TinyString, default="ip_address")
    preprocessing = db.Column(db.LargeString)
    postprocessing = db.Column(db.LargeString)
    postprocessing_mode = db.Column(db.TinyString, default="always")
    log_level = db.Column(Integer, default=1)
    runs = relationship(
        "Run",
        foreign_keys="[Run.service_id]",
        back_populates="service",
        cascade="all, delete-orphan",
    )
    logs = relationship(
        "ServiceLog",
        foreign_keys="[ServiceLog.service_id]",
        back_populates="service",
        cascade="all, delete-orphan",
    )
    maximum_runs = db.Column(Integer, default=1)
    multiprocessing = db.Column(Boolean, default=False)
    max_processes = db.Column(Integer, default=5)
    status = db.Column(db.TinyString, default="Idle")
    validation_condition = db.Column(db.TinyString, default="none")
    conversion_method = db.Column(db.TinyString, default="none")
    validation_method = db.Column(db.TinyString, default="text")
    content_match = db.Column(db.LargeString)
    content_match_regex = db.Column(Boolean, default=False)
    dict_match = db.Column(db.Dict)
    negative_logic = db.Column(Boolean, default=False)
    delete_spaces_before_matching = db.Column(Boolean, default=False)
    run_method = db.Column(db.TinyString, default="per_device")

    def __init__(self, **kwargs):
        kwargs.pop("status", None)
        super().__init__(**kwargs)
        if "name" not in kwargs:
            self.set_name()

    def update(self, **kwargs):
        if "scoped_name" in kwargs and kwargs.get("scoped_name") != self.scoped_name:
            self.set_name(kwargs["scoped_name"])
        if self.positions and "positions" in kwargs:
            kwargs["positions"] = {**self.positions, **kwargs["positions"]}
        super().update(**kwargs)

    @classmethod
    def filtering_constraints(cls, **kwargs):
        workflow_id, constraints = kwargs["form"].get("workflow-filtering"), []
        if workflow_id:
            constraints.extend(
                [
                    models["service"].workflows.any(
                        models["workflow"].id == int(workflow_id)
                    ),
                    ~or_(
                        models["service"].scoped_name == name
                        for name in ("Start", "End")
                    ),
                ]
            )
        elif kwargs["form"].get("parent-filtering", "true") == "true":
            constraints.append(~models["service"].workflows.any())
        return constraints

    def duplicate(self, workflow=None):
        for i in range(10):
            number = f" ({i})" if i else ""
            scoped_name = f"{self.scoped_name}{number}"
            name = f"[{workflow.name}] {scoped_name}" if workflow else scoped_name
            if not db.fetch("service", allow_none=True, name=name):
                service = super().duplicate(
                    name=name, scoped_name=scoped_name, shared=False, update_pools=True
                )
                break
        if workflow:
            workflow.services.append(service)
        return service

    @property
    def filename(self):
        return app.strip_all(self.name)

    @classmethod
    def rbac_filter(cls, query, mode, user):
        query = query.filter(cls.default_access != "admin")
        pool_alias = aliased(models["pool"])
        return query.filter(cls.default_access == "public").union(
            query.join(cls.pools)
            .join(models["access"], models["pool"].access)
            .join(pool_alias, models["access"].user_pools)
            .join(models["user"], pool_alias.users)
            .filter(models["access"].access_type.contains(mode))
            .filter(models["user"].name == user.name),
            query.filter(cls.creator == user.name),
        )

    def set_name(self, name=None):
        if self.shared:
            workflow = "[Shared] "
        elif not self.workflows:
            workflow = ""
        else:
            workflow = f"[{self.workflows[0].name}] "
        self.name = f"{workflow}{name or self.scoped_name}"

    def neighbors(self, workflow, direction, subtype):
        for edge in getattr(self, f"{direction}s"):
            if edge.subtype == subtype and edge.workflow == workflow:
                yield getattr(edge, direction), edge


class ConnectionService(Service):

    __tablename__ = "connection_service"
    id = db.Column(Integer, ForeignKey("service.id"), primary_key=True)
    parent_type = "service"
    credentials = db.Column(db.SmallString, default="device")
    custom_username = db.Column(db.SmallString)
    custom_password = db.Column(db.SmallString)
    start_new_connection = db.Column(Boolean, default=False)
    close_connection = db.Column(Boolean, default=False)
    __mapper_args__ = {"polymorphic_identity": "connection_service"}


class Result(AbstractBase):

    __tablename__ = type = "result"
    private = True
    log_change = False
    id = db.Column(Integer, primary_key=True)
    success = db.Column(Boolean, default=False)
    runtime = db.Column(db.TinyString)
    duration = db.Column(db.TinyString)
    result = db.Column(db.Dict)
    run_id = db.Column(Integer, ForeignKey("run.id", ondelete="cascade"))
    run = relationship("Run", back_populates="results", foreign_keys="Result.run_id")
    parent_runtime = db.Column(db.TinyString)
    parent_device_id = db.Column(Integer, ForeignKey("device.id"))
    parent_device = relationship("Device", uselist=False, foreign_keys=parent_device_id)
    parent_device_name = association_proxy("parent_device", "name")
    device_id = db.Column(Integer, ForeignKey("device.id"))
    device = relationship("Device", uselist=False, foreign_keys=device_id)
    device_name = association_proxy("device", "name")
    service_id = db.Column(Integer, ForeignKey("service.id"))
    service = relationship("Service", foreign_keys="Result.service_id")
    service_name = association_proxy(
        "service", "scoped_name", info={"name": "service_name"}
    )
    workflow_id = db.Column(Integer, ForeignKey("workflow.id", ondelete="cascade"))
    workflow = relationship("Workflow", foreign_keys="Result.workflow_id")
    workflow_name = association_proxy(
        "workflow", "scoped_name", info={"name": "workflow_name"}
    )

    def __getitem__(self, key):
        return self.result[key]

    def __init__(self, **kwargs):
        self.success = kwargs["result"]["success"]
        self.runtime = kwargs["result"]["runtime"]
        self.duration = kwargs["result"]["duration"]
        super().__init__(**kwargs)
        self.parent_runtime = self.run.parent_runtime

    def __repr__(self):
        return f"SERVICE '{self.service}' - DEVICE '{self.device} ({self.runtime})"

    @classmethod
    def filtering_constraints(cls, **kwargs):
        constraints = []
        if kwargs.get("rest_api_request", False):
            return []
        if kwargs.get("runtime"):
            constraints.append(models["result"].parent_runtime == kwargs["runtime"])
        return constraints


class ServiceLog(AbstractBase):

    __tablename__ = type = "service_log"
    private = True
    log_change = False
    id = db.Column(Integer, primary_key=True)
    content = db.Column(db.LargeString)
    runtime = db.Column(db.TinyString)
    service_id = db.Column(Integer, ForeignKey("service.id"))
    service = relationship("Service", foreign_keys="ServiceLog.service_id")

    def __repr__(self):
        return f"SERVICE '{self.service}' ({self.runtime})"


class Run(AbstractBase):

    __tablename__ = type = "run"
    __table_args__ = (
        Index("ix_run_parent_runtime_0", "parent_runtime", "runtime"),
        Index(
            "ix_run_start_service_id_0", "start_service_id", "parent_runtime", "runtime"
        ),
    )
    private = True
    id = db.Column(Integer, primary_key=True)
    restart_run_id = db.Column(Integer, ForeignKey("run.id"))
    restart_run = relationship("Run", uselist=False, foreign_keys=restart_run_id)
    start_services = db.Column(db.List)
    creator = db.Column(db.SmallString, default="")
    properties = db.Column(db.Dict)
    success = db.Column(Boolean, default=False)
    status = db.Column(db.TinyString, default="Running")
    runtime = db.Column(db.TinyString, index=True)
    duration = db.Column(db.TinyString)
    trigger = db.Column(db.TinyString, default="UI")
    parent_id = db.Column(Integer, ForeignKey("run.id", ondelete="cascade"))
    parent = relationship(
        "Run", remote_side=[id], foreign_keys="Run.parent_id", back_populates="children"
    )
    children = relationship("Run", foreign_keys="Run.parent_id")
    parent_runtime = db.Column(db.TinyString)
    path = db.Column(db.TinyString)
    parent_device_id = db.Column(Integer, ForeignKey("device.id"))
    parent_device = relationship("Device", foreign_keys="Run.parent_device_id")
    target_devices = relationship(
        "Device", secondary=db.run_device_table, back_populates="runs"
    )
    target_pools = relationship(
        "Pool", secondary=db.run_pool_table, back_populates="runs"
    )
    service_id = db.Column(Integer, ForeignKey("service.id"))
    service = relationship(
        "Service", back_populates="runs", foreign_keys="Run.service_id"
    )
    service_name = association_proxy(
        "service", "scoped_name", info={"name": "service_name"}
    )
    placeholder_id = db.Column(Integer, ForeignKey("service.id", ondelete="SET NULL"))
    placeholder = relationship("Service", foreign_keys="Run.placeholder_id")
    start_service_id = db.Column(Integer, ForeignKey("service.id", ondelete="SET NULL"))
    start_service = relationship("Service", foreign_keys="Run.start_service_id")
    start_service_name = association_proxy(
        "start_service", "scoped_name", info={"name": "start_service_name"}
    )
    workflow_id = db.Column(Integer, ForeignKey("workflow.id", ondelete="cascade"))
    workflow = relationship("Workflow", foreign_keys="Run.workflow_id")
    workflow_name = association_proxy(
        "workflow", "scoped_name", info={"name": "workflow_name"}
    )
    task_id = db.Column(Integer, ForeignKey("task.id", ondelete="SET NULL"))
    task = relationship("Task", foreign_keys="Run.task_id")
    state = db.Column(db.Dict, info={"log_change": False})
    results = relationship("Result", back_populates="run", cascade="all, delete-orphan")
    model_properties = ["progress", "service_properties"]

    def __init__(self, **kwargs):
        self.runtime = kwargs.get("runtime") or app.get_time()
        super().__init__(**kwargs)
        if not self.creator:
            self.creator = getattr(self.parent, "creator", "")
        if not kwargs.get("parent_runtime"):
            self.parent_runtime = self.runtime
            self.path = str(self.service.id)
        elif self.parent_device:
            self.path = self.parent.path
        else:
            self.path = f"{self.parent.path}>{self.service.id}"
        if not self.start_services:
            self.start_services = [db.fetch("service", scoped_name="Start").id]

    @classmethod
    def prefilter(cls, query):
        return query.filter(cls.parent_runtime == cls.runtime)

    @classmethod
    def rbac_filter(cls, query, mode, user):
        query = query.join(cls.service).filter(
            models["service"].default_access != "admin"
        )
        public_services = query.join(cls.service).filter(
            models["service"].default_access == "public"
        )
        pool_alias = aliased(models["pool"])
        return public_services.union(
            query.join(cls.service)
            .join(models["pool"], models["service"].pools)
            .join(models["access"], models["pool"].access)
            .join(pool_alias, models["access"].user_pools)
            .join(models["user"], pool_alias.users)
            .filter(models["access"].access_type.contains(mode))
            .filter(models["user"].name == user.name),
            query.filter(cls.creator == user.name),
        )

    @property
    def name(self):
        return repr(self)

    @property
    def original(self):
        return self if not self.parent else self.parent.original

    @property
    def log_change(self):
        return self.runtime == self.parent_runtime

    def __repr__(self):
        return f"{self.runtime}: SERVICE '{self.service}'"

    def __getattr__(self, key):
        if key in self.__dict__:
            return self.__dict__[key]
        elif key in self.__dict__.get("properties", {}):
            return self.__dict__["properties"][key]
        elif set(self.__dict__) & {"service_id", "service"}:
            return getattr(self.service, key)
        else:
            raise AttributeError

    def result(self, device=None, main=False):
        for result in self.results:
            if result.device_name == device:
                return result
        if main and len(self.results) == 1:
            return self.results[0]

    @property
    def service_properties(self):
        return {k: getattr(self.service, k) for k in ("id", "type", "name")}

    def get_state(self):
        if self.original.state:
            return self.original.state
        elif app.redis_queue:
            keys = app.redis("keys", f"{self.parent_runtime}/state/*")
            if not keys:
                return {}
            data, state = list(zip(keys, app.redis("mget", *keys))), {}
            for log, value in data:
                inner_store, (*path, last_key) = state, log.split("/")[2:]
                for key in path:
                    inner_store = inner_store.setdefault(key, {})
                if value in ("False", "True"):
                    value = value == "True"
                inner_store[last_key] = value
            return state
        else:
            return app.run_db[self.parent_runtime]

    @property
    def stop(self):
        if app.redis_queue:
            return bool(app.redis("get", f"stop/{self.parent_runtime}"))
        else:
            return app.run_stop[self.parent_runtime]

    @property
    def progress(self):
        progress = self.get_state().get(self.path, {}).get("progress")
        try:
            progress = progress["device"]
            failure = int(progress.get("failure", 0))
            success = int(progress.get("success", 0))
            return f"{success + failure}/{progress['total']} ({failure} failed)"
        except (KeyError, TypeError):
            return "N/A"

    def compute_devices_from_query(_self, query, property, **locals):  # noqa: N805
        values = _self.eval(query, **locals)[0]
        devices, not_found = set(), []
        if isinstance(values, str):
            values = [values]
        for value in values:
            if isinstance(value, models["device"]):
                device = value
            else:
                device = db.fetch("device", allow_none=True, **{property: value})
            if device:
                devices.add(device)
            else:
                not_found.append(value)
        if not_found:
            raise Exception(f"Device query invalid targets: {', '.join(not_found)}")
        return devices

    def compute_devices(self, payload):
        service = self.placeholder or self.service
        devices = set(self.target_devices)
        for pool in self.target_pools:
            devices |= set(pool.devices)
        if not devices:
            if service.device_query:
                devices |= self.compute_devices_from_query(
                    service.device_query,
                    service.device_query_property,
                    payload=payload,
                )
            devices |= set(service.target_devices)
            for pool in service.target_pools:
                if self.update_target_pools:
                    pool.compute_pool()
                devices |= set(pool.devices)
        return list(devices)

    def init_state(self):
        if not app.redis_queue:
            if app.run_db[self.parent_runtime].get(self.path):
                return
            app.run_db[self.parent_runtime][self.path] = {}
        if self.placeholder:
            for property in ("id", "scoped_name", "type"):
                value = getattr(self.placeholder, property)
                self.write_state(f"placeholder/{property}", value)
        self.write_state("success", True)

    def write_state(self, path, value, method=None):
        if app.redis_queue:
            if isinstance(value, bool):
                value = str(value)
            app.redis(
                {None: "set", "append": "lpush", "increment": "incr"}[method],
                f"{self.parent_runtime}/state/{self.path}/{path}",
                value,
            )
        else:
            *keys, last = f"{self.parent_runtime}/{self.path}/{path}".split("/")
            store = app.run_db
            for key in keys:
                store = store.setdefault(key, {})
            if not method:
                store[last] = value
            elif method == "increment":
                store.setdefault(last, 0)
                store[last] += value
            else:
                store.setdefault(last, []).append(value)

    def run(self, payload):
        self.init_state()
        self.write_state("status", "Running")
        start = datetime.now().replace(microsecond=0)
        try:
            app.service_db[self.service.id]["runs"] += 1
            results = {"runtime": self.runtime, **self.device_run(payload)}
        except Exception:
            result = "\n".join(format_exc().splitlines())
            self.log("error", result)
            results = {"success": False, "runtime": self.runtime, "result": result}
        finally:
            db.session.commit()
            state = self.get_state()
            self.status = state["status"] = "Aborted" if self.stop else "Completed"
            self.success = results["success"]
            if self.update_pools_after_running:
                for pool in db.fetch_all("pool"):
                    pool.compute_pool()
            if self.send_notification:
                try:
                    results = self.notify(results, payload)
                except Exception:
                    error = "\n".join(format_exc().splitlines())
                    self.log("error", f"Notification error: {error}")
                    results["notification"] = {"success": False, "error": error}
            app.service_db[self.service.id]["runs"] -= 1
            if not app.service_db[self.id]["runs"]:
                self.service.status = "Idle"
            now = datetime.now().replace(microsecond=0)
            results["duration"] = self.duration = str(now - start)
            if self.runtime == self.parent_runtime:
                self.state = state
                self.close_remaining_connections()
            if self.task and not (self.task.frequency or self.task.crontab_expression):
                self.task.is_active = False
            results["properties"] = {
                "run": {
                    k: v
                    for k, v in self.properties.items()
                    if k not in db.private_properties_set
                },
                "service": self.service.get_properties(exclude=["positions"]),
            }
            results["trigger"] = self.trigger
            if (
                self.runtime == self.parent_runtime
                or len(self.target_devices) > 1
                or self.run_method == "once"
            ):
                results = self.create_result(
                    results, run_result=self.runtime == self.parent_runtime
                )
            if app.redis_queue and self.runtime == self.parent_runtime:
                app.redis("delete", *(app.redis("keys", f"{self.runtime}/*") or []))
        return results

    def make_results_json_compliant(self, results):
        def rec(value):
            if isinstance(value, dict):
                return {k: rec(value[k]) for k in list(value)}
            elif isinstance(value, list):
                return list(map(rec, value))
            elif not isinstance(value, (int, str, bool, float, None.__class__)):
                self.log("info", f"Converting {value} to string in results")
                return str(value)
            else:
                return value

        return rec(results)

    @staticmethod
    def get_device_result(args):
        device_id, runtime, payload, results = args
        device = db.fetch("device", id=device_id)
        run = db.fetch("run", runtime=runtime)
        results.append(run.get_results(payload, device))

    def device_iteration(self, payload, device):
        derived_devices = self.compute_devices_from_query(
            self.service.iteration_devices,
            self.service.iteration_devices_property,
            **locals(),
        )
        derived_run = db.factory(
            "run",
            commit=True,
            **{
                "service": self.service.id,
                "target_devices": [
                    derived_device.id for derived_device in derived_devices
                ],
                "workflow": self.workflow.id,
                "parent_device": device.id,
                "restart_run": self.restart_run,
                "parent": self,
                "parent_runtime": self.parent_runtime,
            },
        )
        derived_run.properties = self.properties
        success = derived_run.run(payload)["success"]
        return success

    def device_run(self, payload):
        self.target_devices = self.compute_devices(payload)
        if self.runtime == self.parent_runtime:
            allowed_targets = db.query("device", rbac="target", username=self.creator)
            unauthorized_targets = set(self.target_devices) - set(allowed_targets)
            if unauthorized_targets:
                result = (
                    f"Error 403: User '{self.creator}' is not allowed to use these"
                    f" devices as targets: {', '.join(map(str, unauthorized_targets))}"
                )
                self.log("info", result, logger="security")
                return {"result": result, "success": False}
        summary = {"failure": [], "success": []}
        if self.iteration_devices and not self.parent_device:
            if not self.workflow:
                result = "Device iteration not allowed outside of a workflow"
                return {"success": False, "result": result, "runtime": self.runtime}
            for device in self.target_devices:
                key = "success" if self.device_iteration(payload, device) else "failure"
                self.write_state(f"progress/device/{key}", 1, "increment")
                summary[key].append(device.name)
            return {
                "success": not summary["failure"],
                "summary": summary,
                "runtime": self.runtime,
            }
        self.write_state("progress/device/total", len(self.target_devices), "increment")
        non_skipped_targets, skipped_targets, results = [], [], []
        skip_service = self.skip.get(self.workflow_name)
        if skip_service:
            self.write_state("status", "Skipped")
        for device in self.target_devices:
            skip_device = skip_service
            if not skip_service and self.skip_query:
                skip_device = self.eval(self.skip_query, **locals())[0]
            if skip_device:
                if device:
                    self.write_state("progress/device/skipped", 1, "increment")
                if self.skip_value == "discard":
                    continue
                device_results = {
                    "device_target": getattr(device, "name", None),
                    "runtime": app.get_time(),
                    "result": "skipped",
                    "duration": "0:00:00",
                    "success": self.skip_value == "success",
                }
                skipped_targets.append(device.name)
                self.create_result(device_results, device, commit=False)
                results.append(device_results)
            else:
                non_skipped_targets.append(device)
        self.target_devices = non_skipped_targets
        if self.run_method != "per_device":
            results = self.get_results(payload)
            if "summary" not in results:
                summary_key = "success" if results["success"] else "failure"
                device_names = [device.name for device in self.target_devices]
                summary[summary_key].extend(device_names)
                results["summary"] = summary
            for key in ("success", "failure"):
                device_number = len(results["summary"][key])
                self.write_state(f"progress/device/{key}", device_number)
            summary[self.skip_value].extend(skipped_targets)
            return results
        else:
            if self.parent_runtime == self.runtime and not self.target_devices:
                error = (
                    "The service 'Run method' is set to 'Per device' mode, "
                    "but no targets have been selected (in Step 3 > Targets)"
                )
                self.log("error", error)
                return {"success": False, "runtime": self.runtime, "result": error}
            if self.multiprocessing and len(non_skipped_targets) > 1:
                processes = min(len(non_skipped_targets), self.max_processes)
                process_args = [
                    (device.id, self.runtime, payload, results)
                    for device in non_skipped_targets
                ]
                self.log("info", f"Starting a pool of {processes} threads")
                with ThreadPool(processes=processes) as pool:
                    pool.map(self.get_device_result, process_args)
            else:
                results.extend(
                    [
                        self.get_results(payload, device, commit=False)
                        for device in non_skipped_targets
                    ]
                )
            for result in results:
                key = "success" if result["success"] else "failure"
                summary[key].append(result["device_target"])
            return {
                "summary": summary,
                "success": all(result["success"] for result in results if result),
                "runtime": self.runtime,
            }

    def create_result(self, results, device=None, commit=True, run_result=False):
        self.success = results["success"]
        results = self.make_results_json_compliant(results)
        result_kw = {
            "run": self,
            "service": self.service_id,
            "parent_runtime": self.parent_runtime,
        }
        if self.workflow_id:
            result_kw["workflow"] = self.workflow_id
        if self.parent_device_id:
            result_kw["parent_device"] = self.parent_device_id
        if device:
            result_kw["device"] = device.id
        if self.parent_runtime == self.runtime and not device:
            services = list(app.run_logs.get(self.runtime, []))
            for service_id in services:
                logs = app.log_queue(self.runtime, service_id, mode="get")
                db.factory(
                    "service_log",
                    runtime=self.runtime,
                    service=service_id,
                    content="\n".join(logs or []),
                )
            if self.trigger == "REST":
                results["devices"] = {}
                for result in self.results:
                    results["devices"][result.device.name] = result.result
        create_failed_results = self.disable_result_creation and not self.success
        if not self.disable_result_creation or create_failed_results or run_result:
            db.factory("result", result=results, commit=commit, **result_kw)
        return results

    def run_service_job(self, payload, device):
        args = (device,) if device else ()
        retries, total_retries = self.number_of_retries + 1, 0
        while retries and total_retries < self.max_number_of_retries:
            if self.stop:
                self.log("error", f"ABORTING {device.name} (STOP)")
                return {"success": False, "result": "Stopped"}
            retries -= 1
            total_retries += 1
            try:
                if self.number_of_retries - retries:
                    retry = self.number_of_retries - retries
                    self.log("error", f"RETRY n°{retry}", device)
                if self.service.preprocessing:
                    try:
                        self.eval(
                            self.service.preprocessing, function="exec", **locals()
                        )
                    except SystemExit:
                        pass
                try:
                    results = self.service.job(self, payload, *args)
                except Exception as exc:
                    self.log("error", str(exc), device)
                    result = "\n".join(format_exc().splitlines())
                    results = {"success": False, "result": result}
                results = self.convert_result(results)
                if "success" not in results:
                    results["success"] = True
                if self.service.postprocessing and (
                    self.postprocessing_mode == "always"
                    or self.postprocessing_mode == "failure"
                    and not results["success"]
                    or self.postprocessing_mode == "success"
                    and results["success"]
                ):
                    try:
                        _, exec_variables = self.eval(
                            self.service.postprocessing, function="exec", **locals()
                        )
                        if isinstance(exec_variables.get("retries"), int):
                            retries = exec_variables["retries"]
                    except SystemExit:
                        pass
                run_validation = (
                    self.validation_condition == "always"
                    or self.validation_condition == "failure"
                    and not results["success"]
                    or self.validation_condition == "success"
                    and results["success"]
                )
                if run_validation:
                    self.validate_result(results, payload, device)
                    if self.negative_logic:
                        results["success"] = not results["success"]
                if results["success"]:
                    return results
                elif retries:
                    sleep(self.time_between_retries)
            except Exception as exc:
                self.log("error", str(exc), device)
                result = "\n".join(format_exc().splitlines())
                results = {"success": False, "result": result}
        return results

    def get_results(self, payload, device=None, commit=True):
        self.log("info", "STARTING", device)
        start = datetime.now().replace(microsecond=0)
        results = {"device_target": getattr(device, "name", None)}
        try:
            if self.restart_run and self.service.type == "workflow":
                old_result = self.restart_run.result(
                    device=device.name if device else None
                )
                if old_result and "payload" in old_result.result:
                    payload.update(old_result["payload"])
            if self.service.iteration_values:
                targets_results = {}
                targets = list(self.eval(self.service.iteration_values, **locals())[0])
                if not isinstance(targets, dict):
                    targets = dict(zip(map(str, targets), targets))
                for target_name, target_value in targets.items():
                    self.payload_helper(
                        payload,
                        self.iteration_variable_name,
                        target_value,
                        device=getattr(device, "name", None),
                    )
                    targets_results[target_name] = self.run_service_job(payload, device)
                results.update(
                    {
                        "result": targets_results,
                        "success": all(r["success"] for r in targets_results.values()),
                    }
                )
            else:
                results.update(self.run_service_job(payload, device))
        except Exception:
            formatted_error = "\n".join(format_exc().splitlines())
            results.update({"success": False, "result": formatted_error})
            self.log("error", formatted_error, device)
        results["duration"] = str(datetime.now().replace(microsecond=0) - start)
        if device:
            if (
                getattr(self, "close_connection", False)
                or self.runtime == self.parent_runtime
            ):
                self.close_device_connection(device.name)
            status = "success" if results["success"] else "failure"
            self.write_state(f"progress/device/{status}", 1, "increment")
            self.create_result(
                {"runtime": app.get_time(), **results}, device, commit=commit
            )
        self.log("info", "FINISHED", device)
        if self.waiting_time:
            self.log("info", f"SLEEP {self.waiting_time} seconds...", device)
            sleep(self.waiting_time)
        if not results["success"]:
            self.write_state("success", False)
        return results

    def log(
        self,
        severity,
        log,
        device=None,
        change_log=False,
        logger=None,
        service_log=True,
    ):
        try:
            log_level = int(self.original.log_level)
        except Exception:
            log_level = 1
        if not log_level or severity not in app.log_levels[log_level - 1 :]:
            return
        if device:
            device_name = device if isinstance(device, str) else device.name
            log = f"DEVICE {device_name} - {log}"
        log = f"USER {self.creator} - SERVICE {self.service.scoped_name} - {log}"
        settings = app.log(
            severity, log, user=self.creator, change_log=change_log, logger=logger
        )
        if service_log or logger and settings.get("service_log"):
            run_log = f"{app.get_time()} - {severity} - {log}"
            app.log_queue(self.parent_runtime, self.service.id, run_log)
            if self.runtime != self.parent_runtime:
                app.log_queue(self.parent_runtime, self.original.service.id, run_log)

    def build_notification(self, results, payload):
        notification = {
            "Service": f"{self.service.name} ({self.service.type})",
            "Runtime": self.runtime,
            "Status": "PASS" if results["success"] else "FAILED",
        }
        if "result" in results:
            notification["Results"] = results["result"]
        if self.notification_header:
            notification["Header"] = self.sub(self.notification_header, locals())
        if self.include_link_in_summary:
            address = app.settings["app"]["address"]
            notification["Link"] = f"{address}/view_service_results/{self.id}"
        if "summary" in results:
            if results["summary"]["failure"]:
                notification["FAILED"] = results["summary"]["failure"]
            if results["summary"]["success"] and not self.display_only_failed_nodes:
                notification["PASSED"] = results["summary"]["success"]
        return notification

    def notify(self, results, payload):
        self.log("info", f"Sending {self.send_notification_method} notification...")
        notification = self.build_notification(results, payload)
        file_content = deepcopy(notification)
        if self.include_device_results:
            file_content["Device Results"] = {}
            for device in self.target_devices:
                device_result = db.fetch(
                    "result",
                    service_id=self.service_id,
                    parent_runtime=self.parent_runtime,
                    device_id=device.id,
                    allow_none=True,
                )
                if device_result:
                    file_content["Device Results"][device.name] = device_result.result
        if self.send_notification_method == "mail":
            filename = self.runtime.replace(".", "").replace(":", "")
            status = "PASS" if results["success"] else "FAILED"
            result = app.send_email(
                f"{status}: {self.service.name}",
                app.str_dict(notification),
                recipients=self.mail_recipient,
                reply_to=self.reply_to,
                filename=f"results-{filename}.txt",
                file_content=app.str_dict(file_content),
            )
        elif self.send_notification_method == "slack":
            result = SlackClient(getenv("SLACK_TOKEN")).api_call(
                "chat.postMessage",
                channel=app.settings["slack"]["channel"],
                text=notification,
            )
        else:
            result = post(
                app.settings["mattermost"]["url"],
                verify=app.settings["mattermost"]["verify_certificate"],
                json={
                    "channel": app.settings["mattermost"]["channel"],
                    "text": notification,
                },
            ).text
        results["notification"] = {"success": True, "result": result}
        return results

    def get_credentials(self, device):
        result, credential_type = {}, self.original.credential_type
        credentials = device.get_credentials(credential_type, self.creator)
        self.log("info", f"Using '{credentials.name}' credentials for '{device.name}'")
        if self.credentials == "device":
            result["username"] = credentials.username
            if credentials.subtype == "password":
                result["password"] = app.get_password(credentials.password)
            else:
                private_key = app.get_password(credentials.private_key)
                result["pkey"] = RSAKey.from_private_key(StringIO(private_key))
        elif self.credentials == "user":
            user = db.fetch("user", name=self.creator)
            result["username"] = user.name
            result["password"] = app.get_password(user.password)
        else:
            result["username"] = self.sub(self.custom_username, locals())
            password = app.get_password(self.custom_password)
            substituted_password = self.sub(password, locals())
            if password != substituted_password:
                if substituted_password.startswith("b'"):
                    substituted_password = substituted_password[2:-1]
                password = app.get_password(substituted_password)
            result["password"] = password
        result["secret"] = app.get_password(credentials.enable_password)
        return result

    def convert_result(self, result):
        if self.conversion_method == "none" or "result" not in result:
            return result
        try:
            if self.conversion_method == "text":
                result["result"] = str(result["result"])
            elif self.conversion_method == "json":
                result["result"] = loads(result["result"])
            elif self.conversion_method == "xml":
                result["result"] = parse(result["result"], force_list=True)
        except (ExpatError, JSONDecodeError) as exc:
            result = {
                "success": False,
                "text_response": result,
                "error": f"Conversion to {self.conversion_method} failed",
                "exception": str(exc),
            }
        return result

    def validate_result(self, results, payload, device):
        if self.validation_method == "text":
            match = self.sub(self.content_match, locals())
            str_result = str(results["result"])
            if self.delete_spaces_before_matching:
                match, str_result = map(self.space_deleter, (match, str_result))
            success = (
                self.content_match_regex
                and bool(search(match, str_result))
                or match in str_result
                and not self.content_match_regex
            )
        else:
            match = self.sub(self.dict_match, locals())
            success = self.match_dictionary(results["result"], match)
        results.update({"match": match, "success": success})

    def match_dictionary(self, result, match, first=True):
        if self.validation_method == "dict_equal":
            return result == self.dict_match
        else:
            copy = deepcopy(match) if first else match
            if isinstance(result, dict):
                for k, v in result.items():
                    if isinstance(copy.get(k), list) and isinstance(v, list):
                        for item in v:
                            try:
                                copy[k].remove(item)
                            except ValueError:
                                pass
                        pop_key = not copy[k]
                    else:
                        pop_key = copy.get(k) == v
                    copy.pop(k) if pop_key else self.match_dictionary(v, copy, False)
            elif isinstance(result, list):
                for item in result:
                    self.match_dictionary(item, copy, False)
            return not copy

    def transfer_file(self, ssh_client, files):
        if self.protocol == "sftp":
            with SFTPClient.from_transport(
                ssh_client.get_transport(),
                window_size=self.window_size,
                max_packet_size=self.max_transfer_size,
            ) as sftp:
                sftp.get_channel().settimeout(self.timeout)
                for source, destination in files:
                    getattr(sftp, self.direction)(source, destination)
        else:
            with SCPClient(
                ssh_client.get_transport(), socket_timeout=self.timeout
            ) as scp:
                for source, destination in files:
                    getattr(scp, self.direction)(source, destination)

    def payload_helper(
        self,
        payload,
        name,
        value=None,
        device=None,
        section=None,
        operation="__setitem__",
        allow_none=False,
        default=None,
    ):
        payload = payload.setdefault("variables", {})
        if device:
            payload = payload.setdefault("devices", {})
            payload = payload.setdefault(device, {})
        if section:
            payload = payload.setdefault(section, {})
        if value is None:
            value = default
        value = getattr(payload, operation)(name, value)
        if operation == "get" and not allow_none and value is None:
            raise Exception(f"Payload Editor: {name} not found in {payload}.")
        else:
            return value

    def get_var(self, *args, **kwargs):
        return self.payload_helper(*args, operation="get", **kwargs)

    def get_result(self, service_name, device=None, workflow=None):
        def filter_run(query, property):
            query = query.filter(
                models["run"].service.has(
                    getattr(models["service"], property) == service_name
                )
            )
            return query.all()

        def recursive_search(run: "Run"):
            if not run:
                return None
            query = db.session.query(models["run"]).filter(
                models["run"].parent_runtime == run.parent_runtime
            )
            if workflow or self.workflow:
                name = workflow or self.workflow.name
                query.filter(
                    models["run"].workflow.has(models["workflow"].name == name)
                )
            runs = filter_run(query, "scoped_name") or filter_run(query, "name")
            results = list(filter(None, [run.result(device) for run in runs]))
            if not results:
                return recursive_search(run.restart_run)
            else:
                return results.pop().result

        return recursive_search(self)

    @staticmethod
    def _import(module, *args, **kwargs):
        if module in app.settings["security"]["forbidden_python_libraries"]:
            raise ImportError(f"Module '{module}' is restricted.")
        return importlib_import(module, *args, **kwargs)

    def fetch(self, model, func="fetch", **kwargs):
        if model not in ("device", "link", "pool", "service"):
            raise db.rbac_error(f"Cannot fetch {model}s from workflow builder.")
        return getattr(db, func)(model, rbac="edit", username=self.creator, **kwargs)

    def global_variables(_self, **locals):  # noqa: N805
        payload, device = locals.get("payload", {}), locals.get("device")
        variables = locals
        variables.update(payload.get("variables", {}))
        if device and "devices" in payload.get("variables", {}):
            variables.update(payload["variables"]["devices"].get(device.name, {}))
        variables.update(
            {
                "__builtins__": {**builtins, "__import__": _self._import},
                "fetch": _self.fetch,
                "fetch_all": partial(_self.fetch, func="fetch_all"),
                "send_email": app.send_email,
                "settings": app.settings,
                "devices": _self.target_devices,
                "encrypt": app.encrypt_password,
                "get_var": partial(_self.get_var, payload),
                "get_result": _self.get_result,
                "log": _self.log,
                "workflow": _self.workflow,
                "set_var": partial(_self.payload_helper, payload),
                "parent_device": _self.parent_device or device,
                "placeholder": _self.original.placeholder,
                "dict_to_string": app.str_dict,
            }
        )
        return variables

    def eval(_self, query, function="eval", **locals):  # noqa: N805
        exec_variables = _self.global_variables(**locals)
        results = builtins[function](query, exec_variables) if query else ""
        return results, exec_variables

    def sub(self, input, variables):

        r = compile("{{(.*?)}}")

        def replace(match):
            return str(self.eval(match.group()[2:-2], **variables)[0])

        def rec(input):
            if isinstance(input, str):
                return r.sub(replace, input)
            elif isinstance(input, list):
                return [rec(x) for x in input]
            elif isinstance(input, dict):
                return {rec(k): rec(v) for k, v in input.items()}
            else:
                return input

        return rec(input)

    def space_deleter(self, input):
        return "".join(input.split())

    def update_netmiko_connection(self, connection):
        for property in ("fast_cli", "timeout", "global_delay_factor"):
            service_value = getattr(self.service, property)
            if service_value:
                setattr(connection, property, service_value)
        try:
            if not hasattr(connection, "check_enable_mode"):
                self.log("error", "Netmiko 'check_enable_mode' method is missing")
                return connection
            mode = connection.check_enable_mode()
            if mode and not self.enable_mode:
                connection.exit_enable_mode()
            elif self.enable_mode and not mode:
                connection.enable()
        except Exception as exc:
            self.log("error", f"Failed to honor the enable mode {exc}")
        try:
            if not hasattr(connection, "check_config_mode"):
                self.log("error", "Netmiko 'check_config_mode' method is missing")
                return connection
            mode = connection.check_config_mode()
            if mode and not self.config_mode:
                connection.exit_config_mode()
            elif self.config_mode and not mode:
                connection.config_mode()
        except Exception as exc:
            self.log("error", f"Failed to honor the config mode {exc}")
        return connection

    def netmiko_connection(self, device):
        connection = self.get_or_close_connection("netmiko", device.name)
        if connection:
            self.log("info", "Using cached Netmiko connection", device)
            return self.update_netmiko_connection(connection)
        self.log(
            "info",
            "OPENING Netmiko connection",
            device,
            change_log=False,
            logger="security",
        )
        driver = device.netmiko_driver if self.use_device_driver else self.driver
        netmiko_connection = ConnectHandler(
            device_type=driver,
            ip=device.ip_address,
            port=device.port,
            fast_cli=self.fast_cli,
            timeout=self.timeout,
            global_delay_factor=self.global_delay_factor,
            session_log=BytesIO(),
            global_cmd_verify=False,
            **self.get_credentials(device),
        )
        if self.enable_mode:
            netmiko_connection.enable()
        if self.config_mode:
            netmiko_connection.config_mode()
        app.connections_cache["netmiko"][self.parent_runtime][
            device.name
        ] = netmiko_connection
        return netmiko_connection

    def scrapli_connection(self, device):
        connection = self.get_or_close_connection("scrapli", device.name)
        if connection:
            self.log("info", "Using cached Scrapli connection", device)
            return connection
        self.log(
            "info",
            "OPENING Scrapli connection",
            device,
            change_log=False,
            logger="security",
        )
        credentials = self.get_credentials(device)
        connection = Scrapli(
            transport=self.transport,
            platform=device.scrapli_driver if self.use_device_driver else self.driver,
            host=device.ip_address,
            auth_username=credentials["username"],
            auth_password=credentials["password"],
            auth_private_key=False,
            auth_strict_key=False,
        )
        connection.open()
        app.connections_cache["scrapli"][self.parent_runtime][device.name] = connection
        return connection

    def napalm_connection(self, device):
        connection = self.get_or_close_connection("napalm", device.name)
        if connection:
            self.log("info", "Using cached NAPALM connection", device)
            return connection
        self.log(
            "info",
            "OPENING Napalm connection",
            device,
            change_log=False,
            logger="security",
        )
        credentials = self.get_credentials(device)
        optional_args = self.service.optional_args
        if not optional_args:
            optional_args = {}
        if "secret" not in optional_args:
            optional_args["secret"] = credentials.pop("secret")
        driver = get_network_driver(
            device.napalm_driver if self.use_device_driver else self.driver
        )
        napalm_connection = driver(
            hostname=device.ip_address,
            timeout=self.timeout,
            optional_args=optional_args,
            **credentials,
        )
        napalm_connection.open()
        app.connections_cache["napalm"][self.parent_runtime][
            device.name
        ] = napalm_connection
        return napalm_connection

    def ncclient_connection(self, device):
        connection = self.get_or_close_connection("ncclient", device.name)
        if connection:
            self.log("info", "Using cached ncclient connection", device)
            return connection
        self.log(
            "info",
            "OPENING ncclient connection",
            device,
            change_log=False,
            logger="security",
        )
        credentials = self.get_credentials(device)
        if device.netconf_driver is not None:
            driver_name = device.netconf_driver
        else:
            driver_name = "default"
        device_params = {"name": driver_name}
        ncclient_connection = manager.connect(
            host=device.ip_address,
            port=830,
            hostkey_verify=False,
            look_for_keys=False,
            device_params=device_params,
            username=credentials["username"],
            password=credentials["password"],
        )
        app.connections_cache["ncclient"][self.parent_runtime][
            device.name
        ] = ncclient_connection
        return ncclient_connection

    def get_or_close_connection(self, library, device):
        connection = self.get_connection(library, device)
        if not connection:
            return
        if self.start_new_connection:
            return self.disconnect(library, device, connection)
        if library == "napalm":
            if connection.is_alive():
                return connection
            else:
                self.disconnect(library, device, connection)
        elif library == "ncclient":
            if connection.connected:
                return connection
            else:
                self.disconnect(library, device, connection)
        else:
            try:
                if library == "netmiko":
                    connection.find_prompt()
                else:
                    connection.get_prompt()
                return connection
            except Exception:
                self.disconnect(library, device, connection)

    def get_connection(self, library, device):
        cache = app.connections_cache[library].get(self.parent_runtime, {})
        return cache.get(device)

    def close_device_connection(self, device):
        for library in ("netmiko", "napalm", "scrapli", "ncclient"):
            connection = self.get_connection(library, device)
            if connection:
                self.disconnect(library, device, connection)

    def close_remaining_connections(self):
        threads = []
        for library in ("netmiko", "napalm", "scrapli", "ncclient"):
            devices = list(app.connections_cache[library][self.runtime])
            for device in devices:
                connection = app.connections_cache[library][self.runtime][device]
                thread = Thread(
                    target=self.disconnect, args=(library, device, connection)
                )
                thread.start()
                threads.append(thread)
        for thread in threads:
            thread.join()

    def disconnect(self, library, device, connection):
        try:
            if library == "netmiko":
                connection.disconnect()
            elif library == "ncclient":
                connection.close_session()
            else:
                connection.close()
            app.connections_cache[library][self.parent_runtime].pop(device)
            self.log("info", f"Closed {library} connection", device)
        except Exception as exc:
            self.log(
                "error", f"Error while closing {library} connection ({exc})", device
            )

    def enter_remote_device(self, connection, device):
        if not getattr(self, "jump_on_connect", False):
            return
        connection.find_prompt()
        prompt = connection.base_prompt
        commands = list(
            filter(
                None,
                [
                    self.sub(self.jump_command, locals()),
                    self.sub(self.expect_username_prompt, locals()),
                    self.sub(self.jump_username, locals()),
                    self.sub(self.expect_password_prompt, locals()),
                    self.sub(app.get_password(self.jump_password), locals()),
                    self.sub(self.expect_prompt, locals()),
                ],
            )
        )
        for (send, expect) in zip(commands[::2], commands[1::2]):
            if not send or not expect:
                continue
            self.log(
                "info",
                f"Sent '{send if send != commands[4] else 'jump on connect password'}'"
                f", waiting for '{expect}'",
            )
            connection.send_command(
                send,
                expect_string=expect,
                auto_find_prompt=False,
                strip_prompt=False,
                strip_command=True,
                max_loops=150,
            )
        return prompt

    def exit_remote_device(self, connection, prompt, device):
        if not getattr(self, "jump_on_connect", False):
            return
        exit_command = self.sub(self.exit_command, locals())
        self.log("info", f"Exit jump server with '{exit_command}'", device)
        connection.send_command(
            exit_command,
            expect_string=prompt or None,
            auto_find_prompt=True,
            strip_prompt=False,
            strip_command=True,
        )

    def update_configuration_properties(self, path, property, device):
        try:
            with open(path / "timestamps.json", "r") as file:
                data = load(file)
        except FileNotFoundError:
            data = {}
        data[property] = {
            timestamp: getattr(device, f"last_{property}_{timestamp}")
            for timestamp in app.configuration_timestamps
        }
        with open(path / "timestamps.json", "w") as file:
            dump(data, file, indent=4)
