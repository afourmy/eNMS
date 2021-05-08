// eslint-disable-next-line
function job(id) {
  // timout of 50ms required to wait for form data to load
  setTimeout(() => {
    // allocate the dropdown
    const operationDropdownId = "netconf_service-nc_type";
    const operationDropdown = getJQueryObject(operationDropdownId, id);

    // maintain state
    // this is the data passed in through the view
    let inputData = JSON.parse($("#input_data").val());
    const fields = inputData["fields"];
    const netconfType = inputData["netconf_type"];

    // get the current dropdown value and update UI
    let operation = operationDropdown.val();
    updateElements(fields, netconfType, operation);

    // CHANGE HANDLER //
    // have to be defined before they can be used later in the code
    operationDropdown.change(() => {
      // get the data from the selected element and update
      operation = getSelectedValue(operationDropdownId, id);
      updateElements(fields, netconfType, operation);
    });
  }, 50);

  // HELPERS
  function updateElements(fieldList, netconfTypes, selectedType) {
    // make all fields invisible
    for (let key in fieldList) {
      if ({}.hasOwnProperty.call(fieldList, key)) {
      hideElement(fieldList[key]);
      }
    }

    // enable fields per selection
    let fieldsToShow = netconfTypes[selectedType];
    for (let key in fieldsToShow) {
      if ({}.hasOwnProperty.call(fieldsToShow, key)) {
      showElement(fieldsToShow[key]);
      }
    }
  }

  function hideElement(name) {
    // disables visibility for a field
    $(`label[for=${name}]`).hide();
    if (id) {
      $(`#netconf_service-${name}-${id}`).parent().hide();
    } else {
      $(`#netconf_service-${name}`).parent().hide();
    }
  }

  function showElement(name) {
    // enables visibility for a field
    $(`label[for=${name}]`).show();
    if (id) {
      $(`#netconf_service-${name}-${id}`).parent().show();
    } else {
      $(`#netconf_service-${name}`).parent().show();
    }
  }

  function getSelectedValue(dropdownId, id) {
    // returns the currently selected value for a dropdown
    let value = null;
    if (id) {
      value = $(`#${dropdownId}-${id} option:selected`).val();
    } else {
      value = $(`#${dropdownId} option:selected`).val();
    }
    return value;
  }

  function getJQueryObject(objectId, id) {
    // returns the JQuery object of an object
    // if id is passed in we have an existing service
    let e = null;
    if (id) {
      e = $(`#${objectId}-${id}`);
    } else {
      e = $(`#${objectId}`);
    }
    return e;
  }
}
