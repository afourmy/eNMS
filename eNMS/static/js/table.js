/*
global
page: false
tableProperties: false
*/

import {
  configureNamespace,
  createTooltip,
  createTooltips,
  notify,
  serializeForm,
  userIsActive,
} from "./base.js";
import { loadServiceTypes } from "./automation.js";
import { filterView } from "./visualization.js";

export let tables = {};
export const models = {};
let waitForSearch = false;

export function initTable(type, instance, runtime, id) {
  let columns = models[type].columns;
  let ColumnsIndex = {};
  columns.forEach((column, i) => {
    ColumnsIndex[column.data] = i;
  });
  if (tableProperties[type]) {
    for (let [property, values] of Object.entries(tableProperties[type])) {
      if (property in ColumnsIndex) {
        Object.assign(columns[ColumnsIndex[property]], values);
      } else {
        columns.splice(-1, 0, values);
      }
    }
  }
  let visibleColumns = localStorage.getItem(`table/${type}`);
  if (visibleColumns) visibleColumns = visibleColumns.split(",");
  columns.forEach((column) => {
    if (visibleColumns) column.visible = visibleColumns.includes(column.data);
    column.name = column.data;
  });

  // eslint-disable-next-line new-cap
  tables[type] = $(id ? `#${id}` : "#table").DataTable({
    serverSide: true,
    orderCellsTop: true,
    autoWidth: false,
    scrollX: true,
    drawCallback: function() {
      $(".paginate_button > a").on("focus", function() {
        $(this).blur();
      });
      createTooltips();
    },
    sDom: "tilp",
    columns: columns,
    columnDefs: [{ className: "dt-center", targets: "_all" }],
    initComplete: function() {
      this.api()
        .columns()
        .every(function(index) {
          const data = columns[index];
          let element;
          const elementId = `${type}_filtering-${data.data}`;
          if (data.search == "text") {
            element = `
            <div class="input-group" style="width:100%">
              <input
                id="${elementId}"
                name="${data.data}"
                type="text"
                placeholder="&#xF002;"
                class="form-control"
                style="font-family:Arial, FontAwesome;
                height: 30px; margin-top: 5px"
              >
              <span class="input-group-btn" style="width: 10px;">
                <button
                  id="${elementId}-search"
                  class="btn btn-default pull-right"
                  type="button"
                  style="height: 30px; margin-top: 5px">
                    <span
                      class="glyphicon glyphicon-center glyphicon-menu-down"
                      aria-hidden="true"
                      style="font-size: 10px">
                    </span>
                </button>
              </span>
            </div>`;
          } else if (data.search == "bool") {
            element = `
              <select
                id="${elementId}"
                name="${data.data}"
                class="form-control"
                style="width: 100%; height: 30px; margin-top: 5px"
              >
                <option value="">Any</option>
                <option value="bool-true">True</option>
                <option value="bool-false">False</option>
              </select>`;
          }
          $(element)
            .appendTo($(this.header()))
            .on("keyup", function() {
              if (waitForSearch) return;
              waitForSearch = true;
              setTimeout(function() {
                tables[type].page(0).ajax.reload(null, false);
                waitForSearch = false;
              }, 800);
            })
            .on("click", function(e) {
              e.stopPropagation();
            });
        });
      $(`#controls-${type}`).html(models[type].controls);
      models[type].postProcessing(this.api(), columns, type);
    },
    ajax: {
      url: `/table_filtering/${models[type].modelFiltering || type}`,
      type: "POST",
      contentType: "application/json",
      data: (d) => {
        const form = $(`#${type}_filtering`).length
          ? `#${type}_filtering-form`
          : `#search-${type}-form`;
        d.form = serializeForm(form);
        d.instance = instance;
        d.columns = columns;
        d.type = type;
        if (runtime) {
          d.runtime = $(`#runtimes-${instance.id}`).val() || runtime;
        }
        if (models[type].filteringData) models[type].filteringData(d);
        return JSON.stringify(d);
      },
      dataSrc: function(result) {
        return result.data.map((instance) => new models[type](instance));
      },
    },
  });
  if (["changelog", "run", "result"].includes(type)) {
    tables[type].order([0, "desc"]).draw();
  }
  if (["run", "service", "task", "workflow"].includes(type)) {
    refreshTablePeriodically(type, 3000, true);
  }
}

function filterTable(formType) {
  if (page.includes("table")) {
    tables[formType].page(0).ajax.reload(null, false);
  } else {
    filterView(formType);
  }
  notify("Filter applied.", "success", 5);
}

export const refreshTable = function(tableType, displayNotification) {
  tables[tableType].ajax.reload(null, false);
  if (displayNotification) notify("Table refreshed.", "success", 5);
};

function refreshTablePeriodically(tableType, interval, first) {
  if (userIsActive && !first) refreshTable(tableType, false);
  setTimeout(() => refreshTablePeriodically(tableType, interval), interval);
}

class Base {
  constructor(properties, derivedProperties) {
    Object.assign(this, properties);
    let instanceProperties = {
      id: this.id,
      name: this.name,
      type: this.type,
    };
    if (derivedProperties) {
      derivedProperties.forEach((property) => {
        instanceProperties[property] = this[property];
      });
    }
    this.instance = JSON.stringify(instanceProperties).replace(/"/g, "'");
  }

  static columnDisplay() {
    return `
      <button
        style="background:transparent; border:none; 
        color:transparent; width: 200px;"
        type="button"
      >
        <select multiple
          id="column-display"
          title="Columns"
          class="form-control"
          data-actions-box="true"
          data-selected-text-format="static"
        ></select>
      </button>`;
  }

  static createNewButton(type) {
    return `
      <button
        class="btn btn-primary"
        onclick="eNMS.base.showTypePanel('${type}')"
        data-tooltip="New"
        type="button"
      >
        <span class="glyphicon glyphicon-plus"></span>
      </button>`;
  }

  static searchTableButton() {
    return `
      <button
        id="advanced-search"
        class="btn btn-info"
        data-tooltip="Advanced Search"
        type="button"
      >
        <span class="glyphicon glyphicon-search"></span>
      </button>`;
  }

  static refreshTableButton(type) {
    return `
      <button
        class="btn btn-info"
        onclick="eNMS.table.refreshTable('${type}', true)"
        data-tooltip="Refresh"
        type="button"
      >
        <span class="glyphicon glyphicon-refresh"></span>
      </button>`;
  }

  get deleteInstanceButton() {
    return `
      <li>
        <button type="button" class="btn btn-sm btn-danger"
        onclick="eNMS.base.showDeletionPanel(${this.instance})" data-tooltip="Delete"
          ><span class="glyphicon glyphicon-trash"></span
        ></button>
      </li>`;
  }

  static get lastModifiedColumn() {
    return {
      data: "last_modified",
      title: "Last modified",
      search: "text",
      render: function(_, __, instance) {
        return instance.last_modified.slice(0, -7);
      },
      width: "150px",
    };
  }

  static createfilteringTooltips(type, columns) {
    columns.forEach((column) => {
      if (column.search != "text") return;
      const elementId = `${type}_filtering-${column.data}`;
      createTooltip({
        persistent: true,
        name: elementId,
        target: `#${elementId}-search`,
        container: `#tooltip-frame`,
        position: {
          my: "center-top",
          at: "center-bottom",
        },
        content: `
        <div class="modal-body">
          <select
            id="${column.data}_filter"
            name="${column.data}_filter"
            class="form-control search-select"
            style="width: 100%; height: 30px; margin-top: 15px"
          >
            <option value="inclusion">Inclusion</option>
            <option value="equality">Equality</option>
            <option value="regex">Regular Expression</option>
          </select>
        </div>`,
      });
    });
  }

  static postProcessing(table, columns, type) {
    createTooltip({
      autoshow: true,
      persistent: true,
      name: `${type}_filtering`,
      target: "#advanced-search",
      container: `#controls-${type}`,
      position: {
        my: "center-top",
        at: "center-bottom",
        offsetY: 18,
      },
      url: `../form/${type}_filtering`,
      title: "Relationship-based Filtering",
    });
    Base.createfilteringTooltips(type, columns);
    createTooltips();
    const visibleColumns = localStorage.getItem(`table/${type}`);
    columns.forEach((column) => {
      const visible = visibleColumns
        ? visibleColumns.split(",").includes(column.name)
        : "visible" in column
        ? column.visible
        : true;
      $("#column-display").append(
        new Option(column.title || column.data, column.data, visible, visible)
      );
    });
    $("#column-display").selectpicker("refresh");
    $("#column-display").on("change", function() {
      columns.forEach((col) => {
        table.column(`${col.name}:name`).visible(
          $(this)
            .val()
            .includes(col.data)
        );
      });
      table.ajax.reload(null, false);
      Base.createfilteringTooltips(type, columns);
      localStorage.setItem(`table/${type}`, $(this).val());
    });
    table.columns.adjust();
  }
}

models.device = class Device extends Base {
  static get columns() {
    return [
      { data: "name", title: "Name", search: "text" },
      { data: "description", title: "Description", search: "text" },
      { data: "subtype", title: "Subtype", search: "text" },
      { data: "model", title: "Model", search: "text" },
      { data: "location", title: "Location", search: "text" },
      { data: "vendor", title: "Vendor", search: "text" },
      { data: "operating_system", title: "Operating System", search: "text" },
      { data: "os_version", title: "OS Version", search: "text" },
      { data: "ip_address", title: "IP Address", search: "text" },
      { data: "port", title: "Port", search: "text", visible: false },
      { data: "buttons", width: "230px" },
    ];
  }

  static get controls() {
    return [
      super.columnDisplay(),
      super.createNewButton("device"),
      ` <button type="button" class="btn btn-primary"
      onclick="eNMS.inventory.showImportTopologyPanel()"
      data-tooltip="Export"><span class="glyphicon glyphicon-download">
      </span></button>
      <button type="button" class="btn btn-primary"
        onclick="eNMS.base.openPanel({name: 'excel_export'})"
        data-tooltip="Export"
      >
        <span class="glyphicon glyphicon-upload"></span>
      </button>`,
      super.searchTableButton(),
      super.refreshTableButton("device"),
    ];
  }

  get buttons() {
    return `
      <ul class="pagination pagination-lg" style="margin: 0px; width: 230px">
        <li>
          <button type="button" class="btn btn-sm btn-dark"
          onclick="eNMS.inventory.showConnectionPanel(${this.instance})"
          data-tooltip="Connection"
            ><span class="glyphicon glyphicon-console"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-info"
          onclick="eNMS.inventory.showDeviceData(${this.instance})"
          data-tooltip="Network Data"
            ><span class="glyphicon glyphicon-cog"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-info"
          onclick="eNMS.inventory.showDeviceResultsPanel(${this.instance})"
          data-tooltip="Results"
            ><span class="glyphicon glyphicon-list-alt"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-primary"
          onclick="eNMS.base.showTypePanel('device', '${this.id}')" data-tooltip="Edit"
            ><span class="glyphicon glyphicon-edit"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-primary"
          onclick="eNMS.base.showTypePanel('device', '${this.id}', 'duplicate')"
          data-tooltip="Duplicate"
            ><span class="glyphicon glyphicon-duplicate"></span
          ></button>
        </li>
        ${this.deleteInstanceButton}
      </ul>`;
  }
};

models.configuration = class Configuration extends models.device {
  static get modelFiltering() {
    return "device";
  }

  static get columns() {
    let columns = super.columns;
    columns.pop();
    columns.forEach((column) => (column.visible = column.data === "name"));
    columns.push(
      ...[
        {
          data: "configuration",
          title: "Configuration",
          search: "text",
          width: "80%",
        },
        {
          data: "operational_data",
          title: "Operational Data",
          search: "text",
          width: "80%",
          visible: false,
        },
        {
          data: "buttons",
          width: "90px",
        },
      ]
    );
    return columns;
  }

  static postProcessing(...args) {
    super.postProcessing(...args);
    $("#slider").bootstrapSlider({
      value: 0,
      ticks: [...Array(6).keys()],
      formatter: (value) => `Lines of context: ${value}`,
    });
    $("#slider").on("change", function() {
      refreshTable("configuration");
    });
  }

  static filteringData(data) {
    const dataType = $("#data-type").prop("checked")
      ? "operational_data"
      : "configuration";
    const filter = $("#search-type").prop("checked") ? "regex" : "inclusion";
    data.form[`${dataType}_filter`] = filter;
  }

  static get controls() {
    return [
      super.columnDisplay(),
      `<input
        name="context-lines"
        id="slider"
        class="slider"
        style="width: 200px"
      >`,
    ];
  }

  get buttons() {
    return `
      <ul class="pagination pagination-lg" style="margin: 0px">
        <li>
          <button type="button" class="btn btn-sm btn-info"
          onclick="eNMS.inventory.showDeviceData(${this.instance})"
          data-tooltip="Network Data"
            ><span class="glyphicon glyphicon-cog"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-primary"
          onclick="eNMS.base.showTypePanel('device', '${this.id}')" data-tooltip="Edit"
            ><span class="glyphicon glyphicon-edit"></span
          ></button>
        </li>
      </ul>`;
  }
};

models.link = class Link extends Base {
  static get columns() {
    return [
      { data: "name", title: "Name", search: "text" },
      { data: "description", title: "Description", search: "text" },
      { data: "subtype", title: "Subtype", search: "text" },
      { data: "model", title: "Model", search: "text" },
      { data: "location", title: "Location", search: "text" },
      { data: "vendor", title: "Vendor", search: "text" },
      { data: "source_name", title: "Source", search: "text" },
      { data: "destination_name", title: "Destination", search: "text" },
      { data: "buttons", width: "130px" },
    ];
  }

  static get controls() {
    return [
      super.columnDisplay(),
      super.createNewButton("link"),
      super.searchTableButton(),
      super.refreshTableButton("link"),
    ];
  }

  get buttons() {
    return `
      <ul class="pagination pagination-lg" style="margin: 0px; width: 120px">
        <li>
          <button type="button" class="btn btn-sm btn-primary"
          onclick="eNMS.base.showTypePanel('link', '${this.id}')" data-tooltip="Edit"
            ><span class="glyphicon glyphicon-edit"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-primary"
          onclick="eNMS.base.showTypePanel('link', '${this.id}', 'duplicate')"
          data-tooltip="Duplicate"
            ><span class="glyphicon glyphicon-duplicate"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-danger"
          onclick="eNMS.base.showDeletionPanel(${this.instance})" data-tooltip="Delete"
            ><span class="glyphicon glyphicon-trash"></span
          ></button>
        </li>
      </ul>`;
  }
};

models.pool = class Pool extends Base {
  static get columns() {
    return [
      { data: "name", title: "Name", search: "text" },
      super.lastModifiedColumn,
      { data: "description", title: "Description", search: "text" },
      {
        data: "never_update",
        title: "Never update",
        search: "bool",
        width: "100px",
      },
      { data: "objectNumber", title: "Object Count", width: "150px" },
      { data: "buttons", width: "250px" },
    ];
  }

  get objectNumber() {
    return `${this.device_number} devices - ${this.link_number} links`;
  }

  static get controls() {
    return [
      super.columnDisplay(),
      super.createNewButton("pool"),
      ` <button
        class="btn btn-primary"
        onclick="eNMS.inventory.updatePools()"
        data-tooltip="Update all pools"
        type="button"
      >
        <span class="glyphicon glyphicon-flash"></span>
      </button>`,
      super.searchTableButton(),
      super.refreshTableButton("pool"),
    ];
  }

  get buttons() {
    return `
      <ul class="pagination pagination-lg" style="margin: 0px; width: 230px">
        <li>
          <button type="button" class="btn btn-sm btn-info"
          onclick="eNMS.visualization.showPoolView('${this.id}')"
          data-tooltip="Internal View">
          <span class="glyphicon glyphicon-eye-open"></span></button>
        </li>
        <li>
          <button
            type="button"
            class="btn btn-sm btn-primary"
            onclick="eNMS.inventory.showPoolObjectsPanel('${this.id}')"
            data-tooltip="Pool Objects"
          ><span class="glyphicon glyphicon-wrench"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-primary"
          onclick="eNMS.inventory.updatePools('${this.id}')"
          data-tooltip="Update"><span class="glyphicon glyphicon-refresh">
          </span></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-primary"
          onclick="eNMS.base.showTypePanel('pool', '${this.id}')" data-tooltip="Edit"
            ><span class="glyphicon glyphicon-edit"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-primary"
          onclick="eNMS.base.showTypePanel('pool', '${this.id}', 'duplicate')"
          data-tooltip="Duplicate"
            ><span class="glyphicon glyphicon-duplicate"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-danger"
          onclick="eNMS.base.showDeletionPanel(${this.instance})" data-tooltip="Delete"
            ><span class="glyphicon glyphicon-trash"></span
          ></button>
        </li>
      </ul>
    `;
  }
};

models.service = class Service extends Base {
  static get columns() {
    return [
      {
        data: "name",
        title: "Name",
        search: "text",
        className: "dt-body-left",
        render: function(_, __, instance) {
          return instance.type === "workflow"
            ? `<b><a href="#" onclick="eNMS.workflow.switchToWorkflow(
              '${instance.id}')">${instance.scoped_name}</a></b>`
            : $("#parent-filtering").val() == "true"
            ? instance.scoped_name
            : instance.name;
        },
      },
      super.lastModifiedColumn,
      { data: "type", title: "Type", search: "text" },
      { data: "vendor", title: "Vendor", search: "text" },
      { data: "operating_system", title: "Operating System", search: "text" },
      { data: "creator", title: "Creator", search: "text" },
      { data: "status", title: "Status", search: "text", width: "60px" },
      { data: "buttons", width: "260px" },
    ];
  }

  static get controls() {
    return [
      super.columnDisplay(),
      `
      <input type="hidden" id="workflow-filtering" name="workflow-filtering">
      <button
        style="background:transparent; border:none; 
        color:transparent; width: 300px;"
        type="button"
      >
        <select
          id="parent-filtering"
          name="parent-filtering"
          class="form-control"
        >
          <option value="true">Display services hierarchically</option>
          <option value="false">Display all services</option>
        </select>
      </button>
      </input>
      ${super.searchTableButton()}
      <button
        class="btn btn-info"
        onclick="eNMS.table.refreshTable('service', true)"
        data-tooltip="Refresh"
        type="button"
      >
        <span class="glyphicon glyphicon-refresh"></span>
      </button>
      <a
      id="left-arrow"
      class="btn btn-info disabled"
      onclick="action['Backward']()"
      type="button"
    >
      <span class="glyphicon glyphicon-chevron-left"></span>
    </a>
    <a
      id="right-arrow"
      class="btn btn-info disabled"
      onclick="action['Forward']()"
      type="button"
    >
      <span class="glyphicon glyphicon-chevron-right"></span>
    </a>
    <button
    class="btn btn-primary"
    onclick="eNMS.automation.openServicePanel()"
    data-tooltip="New"
    type="button"
  >
    <span class="glyphicon glyphicon-plus"></span>
  </button>
  <button
    style="background:transparent; border:none; 
    color:transparent; width: 200px;"
    type="button"
  >
    <select id="service-type" class="form-control"></select>
  </button>
    `,
    ];
  }

  get buttons() {
    return `
      <ul class="pagination pagination-lg" style="margin: 0px; width: 270px">
        <li>
          <button type="button" class="btn btn-sm btn-info"
          onclick="eNMS.automation.showRuntimePanel('results', ${this.instance})"
          data-tooltip="Results"><span class="glyphicon glyphicon-list-alt">
          </span></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-info"
          onclick="eNMS.automation.showRuntimePanel('logs', ${this.instance})"
          data-tooltip="Logs"><span class="glyphicon glyphicon-list"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-success"
          onclick="eNMS.automation.normalRun('${this.id}')" data-tooltip="Run"
            ><span class="glyphicon glyphicon-play"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-success"
          onclick="eNMS.base.showTypePanel('{self.type}', '${this.id}', 'run')"
          data-tooltip="Parameterized Run"
            ><span class="glyphicon glyphicon-play-circle"></span
          ></button>
        </li>
        <li>
          <button
            type="button"
            class="btn btn-sm btn-primary"
            onclick="eNMS.base.showTypePanel('${this.type}', '${this.id}')"
            data-tooltip="Edit"
          ><span class="glyphicon glyphicon-edit"></span></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-primary"
          onclick="eNMS.automation.exportService('${this.id}')" data-tooltip="Export"
            ><span class="glyphicon glyphicon-download"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-danger"
          onclick="eNMS.base.showDeletionPanel(${this.instance})" data-tooltip="Delete"
            ><span class="glyphicon glyphicon-trash"></span
          ></button>
        </li>
      </ul>
    `;
  }

  static postProcessing(...args) {
    super.postProcessing(...args);
    loadServiceTypes();
    $("#parent-filtering")
      .selectpicker()
      .on("change", function() {
        tables["service"].page(0).ajax.reload(null, false);
      });
  }
};

models.run = class Run extends Base {
  constructor(properties) {
    super(properties);
    this.service = JSON.stringify(this.service_properties).replace(/"/g, "'");
  }

  static get columns() {
    return [
      { data: "runtime", title: "Runtime", search: "text", width: "200px" },
      { data: "duration", title: "Duration", search: "text", width: "100px" },
      { data: "service_name", title: "Service", search: "text" },
      { data: "status", title: "Status", search: "text", width: "100px" },
      { data: "progress", title: "Progress", width: "150px" },
      { data: "buttons", width: "90px" },
    ];
  }

  static get controls() {
    return [
      super.columnDisplay(),
      super.searchTableButton(),
      super.refreshTableButton("run"),
      ` <button
        class="btn btn-info"
        onclick="eNMS.automation.displayCalendar('run')"
        data-tooltip="Calendar"
        type="button"
      >
        <span class="glyphicon glyphicon-calendar"></span>
      </button>`,
    ];
  }

  get buttons() {
    return [
      `<ul class="pagination pagination-lg" style="margin: 0px; width: 100px">
        <li>
          <button type="button" class="btn btn-sm btn-info"
          onclick="eNMS.automation.showRuntimePanel('logs', ${this.service},
          '${this.runtime}')" data-tooltip="Logs">
          <span class="glyphicon glyphicon-list"></span></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-info"
          onclick="eNMS.automation.showRuntimePanel('results', ${this.service},
          '${this.runtime}')" data-tooltip="Results">
          <span class="glyphicon glyphicon-list-alt"></span></button>
        </li>
      </ul>`,
    ];
  }
};

models.result = class Result extends Base {
  constructor(properties) {
    delete properties.result;
    super(properties, ["service_name", "device_name"]);
  }

  static get columns() {
    return [
      { data: "runtime", title: "Runtime", search: "text" },
      { data: "duration", title: "Duration", search: "text" },
      { data: "device_name", title: "Device", search: "text" },
      {
        data: "success",
        title: "Success",
        render: function(_, __, instance) {
          const btn = instance.success ? "success" : "danger";
          const label = instance.success ? "Success" : "Failure";
          return `
            <button
              type="button"
              class="btn btn-${btn} btn-sm"
              style="width:100%">${label}
            </button>`;
        },
        search: "text",
        width: "80px",
      },
      { data: "buttons" },
      {
        data: "version_1",
        title: "V1",
        render: function(_, __, instance) {
          return `<input type="radio" name="v1" value="${instance.id}">`;
        },
      },
      {
        data: "version_2",
        title: "V2",
        render: function(_, __, instance) {
          return `<input type="radio" name="v2" value="${instance.id}">`;
        },
      },
    ];
  }

  static get controls() {
    return [
      `<button
        class="btn btn-info"
        onclick="eNMS.automation.compare('result')"
        data-tooltip="Compare"
        type="button"
      >
        <span class="glyphicon glyphicon-adjust"></span>
      </button>`,
    ];
  }

  get buttons() {
    return [
      `
    <ul class="pagination pagination-lg" style="margin: 0px; width: 90px">
      <li>
          <button type="button" class="btn btn-sm btn-info"
          onclick="eNMS.automation.showResult('${this.id}')"
          data-tooltip="Results"><span class="glyphicon glyphicon-list-alt">
          </span></button>
      </li>
      <li>
          <button
            type="button"
            id="btn-result-${this.id}"
            class="btn btn-sm btn-info"
            onclick="eNMS.automation.copyClipboard(
              'btn-result-${this.id}', ${this.instance}
            )"
            data-tooltip="Copy to clipboard"
          ><span class="glyphicon glyphicon-copy"></span></button>
      </li>
    </ul>`,
    ];
  }
};

models.task = class Task extends Base {
  static get columns() {
    return [
      { data: "name", title: "Name", search: "text" },
      { data: "service_name", title: "Service", search: "text" },
      { data: "status", title: "Status", search: "text", width: "100px" },
      {
        data: "scheduling_mode",
        title: "Scheduling",
        search: "text",
        width: "100px",
      },
      {
        data: "periodicity",
        title: "Periodicity",
        search: "text",
        render: function(_, __, instance) {
          if (instance.scheduling_mode == "standard") {
            return `${instance.frequency} ${instance.frequency_unit}`;
          } else {
            return instance.crontab_expression;
          }
        },
        width: "100px",
      },
      {
        data: "next_run_time",
        title: "Next run time",
        search: "text",
        width: "150px",
      },
      {
        data: "time_before_next_run",
        title: "Time left",
        search: "text",
        width: "150px",
      },
      { data: "buttons", width: "200px" },
    ];
  }

  static get controls() {
    return [
      super.columnDisplay(),
      super.createNewButton("task"),
      super.searchTableButton(),
      super.refreshTableButton("task"),
      ` <button
        class="btn btn-info"
        onclick="eNMS.automation.displayCalendar('task')"
        data-tooltip="Calendar"
        type="button"
      >
        <span class="glyphicon glyphicon-calendar"></span>
      </button>
      <button type="button" class="btn btn-success"
      onclick="eNMS.automation.schedulerAction('resume')" data-tooltip="Play"
        ><span class="glyphicon glyphicon-play"></span
      ></button>
      <button type="button" class="btn btn-danger"
      onclick="eNMS.automation.schedulerAction('pause')" data-tooltip="Pause"
        ><span class="glyphicon glyphicon-pause"></span
      ></button>`,
    ];
  }

  get buttons() {
    const state = this.is_active ? ["disabled", "active"] : ["active", "disabled"];
    return [
      `<ul class="pagination pagination-lg" style="margin: 0px;">
        <li>
          <button type="button" class="btn btn-sm btn-primary"
          onclick="eNMS.base.showTypePanel('task', '${this.id}')" data-tooltip="Edit"
            ><span class="glyphicon glyphicon-edit"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-primary"
          onclick="eNMS.base.showTypePanel('task', '${this.id}', 'duplicate')"
          data-tooltip="Duplicate">
          <span class="glyphicon glyphicon-duplicate"></span></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-success ${state[0]}" ${state[0]}
          onclick="eNMS.automation.resumeTask('${this.id}')" data-tooltip="Play"
            ><span class="glyphicon glyphicon-play"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-danger ${state[1]}" ${state[1]}
          onclick="eNMS.automation.pauseTask('${this.id}')" data-tooltip="Pause"
            ><span class="glyphicon glyphicon-pause"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-danger"
          onclick="eNMS.base.showDeletionPanel(${this.instance})" data-tooltip="Delete"
            ><span class="glyphicon glyphicon-trash"></span
          ></button>
        </li>
      </ul>`,
    ];
  }
};

models.user = class User extends Base {
  static get columns() {
    return [
      { data: "name", title: "Username", search: "text" },
      { data: "email", title: "Email Address", search: "text" },
      { data: "group", title: "Permission Group", search: "text" },
      { data: "buttons", width: "130px" },
    ];
  }

  static get controls() {
    return [
      super.columnDisplay(),
      super.createNewButton("user"),
      super.refreshTableButton("user"),
    ];
  }

  get buttons() {
    return [
      `
      <ul class="pagination pagination-lg" style="margin: 0px;">
        <li>
          <button type="button" class="btn btn-sm btn-primary"
          onclick="eNMS.base.showTypePanel('user', '${this.id}')" data-tooltip="Edit"
            ><span class="glyphicon glyphicon-edit"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-primary"
          onclick="eNMS.base.showTypePanel('user', '${this.id}', 'duplicate')"
          data-tooltip="Duplicate"
            ><span class="glyphicon glyphicon-duplicate"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-danger"
          onclick="eNMS.base.showDeletionPanel(${this.instance})" data-tooltip="Delete"
            ><span class="glyphicon glyphicon-trash"></span
          ></button>
        </li>
      </ul>`,
    ];
  }
};

models.server = class Server extends Base {
  static get columns() {
    return [
      { data: "name", title: "Username", search: "text" },
      { data: "description", title: "Description", search: "text" },
      { data: "ip_address", title: "IP address", search: "text" },
      { data: "weight", title: "Weight", search: "text" },
      { data: "status", title: "Status", search: "text" },
      { data: "buttons", width: "120px" },
    ];
  }

  static get controls() {
    return [
      super.columnDisplay(),
      super.createNewButton("server"),
      super.refreshTableButton("server"),
    ];
  }

  get buttons() {
    return [
      `
      <ul class="pagination pagination-lg" style="margin: 0px;">
        <li>
          <button type="button" class="btn btn-sm btn-primary"
          onclick="eNMS.base.showTypePanel('server', '${this.id}')" data-tooltip="Edit"
            ><span class="glyphicon glyphicon-edit"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-primary"
          onclick="eNMS.base.showTypePanel('server', '${this.id}', 'duplicate')"
          data-tooltip="Duplicate"
            ><span class="glyphicon glyphicon-duplicate"></span
          ></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-danger"
          onclick="eNMS.base.showDeletionPanel(${this.instance})" data-tooltip="Delete"
            ><span class="glyphicon glyphicon-trash"></span
          ></button>
        </li>
      </ul>`,
    ];
  }
};

models.changelog = class Changelog extends Base {
  static get columns() {
    return [
      { data: "time", title: "Time", search: "text", width: "200px" },
      { data: "user", title: "User", search: "text", width: "100px" },
      { data: "severity", title: "Severity", search: "text", width: "80px" },
      {
        data: "content",
        title: "Content",
        search: "text",
        className: "dt-body-left",
      },
    ];
  }

  static get controls() {
    return [
      super.columnDisplay(),
      super.createNewButton("changelog"),
      super.refreshTableButton("changelog"),
    ];
  }
};

models.session = class Session extends Base {
  static get columns() {
    return [
      { data: "timestamp", title: "Timestamp", search: "text", width: "200px" },
      { data: "device_name", title: "Device", search: "text", width: "150px" },
      { data: "user", title: "User", search: "text", width: "100px" },
      { data: "name", title: "Session UUID", search: "text", width: "300px" },
      { data: "buttons", width: "40px" },
    ];
  }

  static get controls() {
    return [super.columnDisplay(), super.refreshTableButton("session")];
  }

  get buttons() {
    return [
      `
      <ul class="pagination pagination-lg" style="margin: 0px;">
        <li>
          <button type="button" class="btn btn-sm btn-info"
          onclick="eNMS.inventory.showSessionLog(${this.id})" data-tooltip="Session Log"
            ><span class="glyphicon glyphicon-list"></span
          ></button>
        </li>
      </ul>`,
    ];
  }
};

models.event = class Event extends Base {
  static get columns() {
    return [
      { data: "name", title: "Name", search: "text" },
      { data: "service_name", title: "Service", search: "text" },
      { data: "log_source", title: "Log", search: "text" },
      { data: "log_content", title: "Content", search: "text" },
      { data: "buttons", width: "120px" },
    ];
  }

  static get controls() {
    return [
      super.columnDisplay(),
      super.createNewButton("event"),
      super.refreshTableButton("event"),
    ];
  }

  get buttons() {
    return [
      `
      <ul class="pagination pagination-lg" style="margin: 0px; width: 150px">
        <li>
          <button type="button" class="btn btn-sm btn-primary"
          onclick="eNMS.base.showTypePanel('event', '{self.id}')"
          data-tooltip="Edit"><span class="glyphicon glyphicon-edit">
          </span></button>
        </li>
        <li>
          <button type="button" class="btn btn-sm btn-primary"
          onclick="eNMS.base.showTypePanel('event', '{self.id}', 'duplicate')"
          data-tooltip="Duplicate">
          <span class="glyphicon glyphicon-duplicate"></span></button>
        </li>
        ${this.deleteInstanceButton}
      </ul>
    `,
    ];
  }
};

configureNamespace("table", [filterTable, refreshTable, refreshTablePeriodically]);
