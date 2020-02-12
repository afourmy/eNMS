/*
global
NProgress: false
page: false
settings: false
user: false
*/

import { call, createTooltips, detectUserInactivity } from "./base.js";
import { initDashboard } from "./inventory.js";
import { initTable, tables } from "./table.js";
import { initView } from "./visualization.js";
import { initWorkflowBuilder } from "./workflow.js";

const currentUrl = window.location.href.split("#")[0].split("?")[0];

function doc(page) {
  let endpoint = {
    administration: "base/installation.html",
    dashboard: "base/features.html",
    "table/device": "inventory/network_creation.html",
    "table/event": "automation/scheduling.html",
    "table/link": "inventory/network_creation.html",
    "table/changelog": "advanced/administration.html",
    "table/pool": "inventory/pools.html",
    "table/run": "automation/services.html",
    "table/service": "automation/services.html",
    "table/task": "automation/scheduling.html",
    "table/user": "advanced/administration.html",
    view: "inventory/network_visualization.html",
    workflow_builder: "automation/workflows.html",
  }[page];
  $("#doc-link").attr("href", `${settings.app.documentation_url}${endpoint}`);
}

function initSidebar() {
  $("#sidebar-menu")
    .find("a")
    .on("click", function(ev) {
      let $li = $(this).parent();
      if ($li.is(".active")) {
        $li.removeClass("active active-sm");
        $("ul:first", $li).slideUp();
      } else {
        if (!$li.parent().is(".child_menu")) {
          $("#sidebar-menu")
            .find("li")
            .removeClass("active active-sm");
          $("#sidebar-menu")
            .find("li ul")
            .slideUp();
        } else {
          if ($("body").is(".nav-sm")) {
            $("#sidebar-menu")
              .find("li")
              .removeClass("active active-sm");
            $("#sidebar-menu")
              .find("li ul")
              .slideUp();
          }
        }
        $li.addClass("active");
        $("ul:first", $li).slideDown();
      }
    });

  let switchMenu = function() {
    if ($("body").hasClass("nav-sm")) {
      $(".left_column").css("width", "70px");
      $(".right_column").css({ width: "calc(100% - 70px)", left: "70px" });
      $("#eNMS").css({ "font-size": "17px" });
      $("#eNMS-version").css({ "font-size": "15px" });
      $("#sidebar-menu")
        .find("li.active ul")
        .hide();
      $("#sidebar-menu")
        .find("li.active")
        .addClass("active-sm");
      $("#sidebar-menu")
        .find("li.active")
        .removeClass("active");
    } else {
      $(".left_column").css("width", "230px");
      $(".right_column").css({ width: "calc(100% - 230px)", left: "230px" });
      $("#eNMS").css({ "font-size": "30px" });
      $("#eNMS-version").css({ "font-size": "20px" });
      $("#sidebar-menu")
        .find("li.active-sm ul")
        .show();
      $("#sidebar-menu")
        .find("li.active-sm")
        .addClass("active");
      $("#sidebar-menu")
        .find("li.active-sm")
        .removeClass("active-sm");
      const url = "a[href='" + currentUrl + "']";
      $("#sidebar-menu")
        .find(url)
        .parent("li")
        .addClass("current-page");
      $("#sidebar-menu")
        .find("a")
        .filter(function() {
          return this.href == currentUrl;
        })
        .parent("li")
        .addClass("current-page")
        .parents("ul")
        .slideDown()
        .parent()
        .addClass("active");
    }
    $(".dataTable").each(function() {
      $(this)
        .dataTable()
        .fnDraw();
    });
  };

  switchMenu();
  $("#menu_toggle").on("click", function() {
    call({ url: `/switch_menu/${user.id}` });
    $("body").toggleClass("nav-md nav-sm");
    switchMenu();
  });
}

$(document).ready(function() {
  NProgress.start();
  $(window).resize(() => {
    Object.keys(tables).forEach((table) => tables[table].columns.adjust());
  });
  const alerts = localStorage.getItem("alerts");
  if (!alerts) {
    localStorage.setItem("alerts", "[]");
  } else {
    const alertNumber = JSON.parse(alerts).length;
    $("#alert-number").text(alertNumber > 99 ? "99+" : alertNumber || "");
  }
  initSidebar();
  if (page.includes("table")) {
    initTable(page.split("/")[1]);
  } else if (page == "workflow_builder") {
    initWorkflowBuilder();
  } else if (page.includes("view")) {
    initView();
  } else if (page == "dashboard") {
    initDashboard();
  }
  doc(page);
  detectUserInactivity();
  createTooltips();
});

$(window).load(function() {
  NProgress.done();
});
