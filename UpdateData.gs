// Global variable for the spreadsheet ID
const SPREADSHEET_ID = '1yfYG2b5vpl781sHvxJgaCdZeB_MTe_FRImjXnFXEUeE'; // *** IMPORTANT: REPLACE THIS ***

/**
 * Helper to create a JSON response.
 * @param {Object} data The data payload.
 * @param {number} statusCode HTTP status code (default 200).
 * @return {GoogleAppsScript.Content.TextOutput}
 */
function createJsonResponse(data, statusCode = 200) {
  const output = ContentService.createTextOutput(JSON.stringify(data));
  output.setMimeType(ContentService.MimeType.JSON);
  // Apps Script Web Apps don't directly set HTTP status codes other than 200 for successful execution.
  // We'll communicate success/error via the JSON body.
  return output;
}

/**
 * Handles GET requests to fetch data or a specific value.
 * Expected parameters:
 * - e.parameter.sheetName (e.g., 'API')
 * - e.parameter.action (e.g., 'getStartDate')
 */
function doGet(e) {
  try {
    const action = e.parameter.action;

    if (action === "getStartDate") {
      // Logic for getting the start date.
      // Replace this with the actual logic to get your desired date.
      const today = new Date();
      const formattedDate = (today.getMonth() + 1) + '-' + today.getDate() + '-' + today.getFullYear();
      return createJsonResponse({ status: 'success', startDate: formattedDate });
    }

    const sheetName = e.parameter.sheetName;
    if (!sheetName) {
      return createJsonResponse({ status: 'error', message: 'Missing sheetName parameter.' }, 400);
    }
    
    // Your existing logic for fetching sheet data by name...
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sheet = ss.getSheetByName(sheetName);

    if (!sheet) {
      return createJsonResponse({ status: 'error', message: `Sheet '${sheetName}' not found.` }, 404);
    }

    const range = sheet.getDataRange();
    const values = range.getDisplayValues();

    if (values.length === 0) {
      return createJsonResponse({ status: 'success', message: 'No data in sheet.', data: [] });
    }

    const headers = values[0];
    const dataRows = values.slice(1);

    const jsonData = dataRows.map(row => {
      const rowObject = {};
      headers.forEach((header, index) => {
        rowObject[header] = row[index];
      });
      return rowObject;
    });

    return createJsonResponse({ status: 'success', data: jsonData, sheetName: sheetName });

  } catch (error) {
    Logger.log('Error in doGet: ' + error.message);
    return createJsonResponse({ status: 'error', message: 'Failed to process GET request.', details: error.message }, 500);
  }
}

/**
 * Processes a single update request for a spreadsheet row.
 * This is a helper function used by doPost.
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet The target sheet object.
 * @param {Array<string>} headers The header row of the sheet.
 * @param {Array<Array<any>>} allValues All values from the sheet's data range.
 * @param {Object} updateRequest The individual update object (sheetName, identifier, idColumnIndex, updates).
 * @returns {Object} Result of the update for this specific request.
 */
function processSingleUpdateRequest(sheet, headers, allValues, updateRequest) {
  const sheetName = updateRequest.sheetName;
  const identifier = updateRequest.identifier;
  const idColumnIndex = updateRequest.idColumnIndex; // 1-based index
  const updates = updateRequest.updates; // Object like {'Column Name': 'New Value'}

  if (!sheetName || identifier === undefined || idColumnIndex === undefined || !updates) {
    return { status: 'error', message: 'Missing required parameters for an update request: sheetName, identifier, idColumnIndex, or updates.', identifier: identifier || 'N/A' };
  }

  let rowIndexToUpdate = -1;
  // Find the row based on the identifier in the specified column
  for (let i = 1; i < allValues.length; i++) { // Start from second row (index 1) to skip headers
    const cellValue = allValues[i][idColumnIndex - 1]; // Adjust to 0-based array index
    if (String(cellValue) === String(identifier)) { // Compare as strings for robustness
      rowIndexToUpdate = i + 1; // Convert 0-based array index to 1-based sheet row number
      break;
    }
  }

  if (rowIndexToUpdate === -1) {
    return { status: 'error', message: `Identifier '${identifier}' not found in column ${idColumnIndex} of sheet '${sheetName}'.`, identifier: identifier };
  }

  // Apply updates
  let updatedCellsCount = 0;
  // Create an array of ranges to update to use setValues for batch writing
  const rangesToUpdate = [];
  const valuesToSet = [];

  for (const colName in updates) {
    if (updates.hasOwnProperty(colName)) {
      const colIndex = headers.indexOf(colName);
      if (colIndex !== -1) {
        // Collect the range and value
        rangesToUpdate.push(sheet.getRange(rowIndexToUpdate, colIndex + 1));
        valuesToSet.push([updates[colName]]); // Needs to be a 2D array for setValues
        updatedCellsCount++;
      } else {
        Logger.log(`Warning: Column '${colName}' not found in sheet '${sheetName}' for identifier '${identifier}'.`);
      }
    }
  }

  if (updatedCellsCount > 0) {
    // This is the key optimization: use setValue for each range individually
    // If we wanted true batching per row, we'd gather all values for the row and set at once.
    // However, given the current structure of `updates` dict, individual cell updates are more direct.
    // For large numbers of individual cells, a single `setValues` call on a larger range would be better
    // but would require fetching the whole row, modifying it, and writing it back.
    // The current approach avoids extra reads per row, focusing on writes.
    // For the current setup, individual setValue calls are still better than multiple HTTP requests.

    // A more advanced batching for a *single row* would look like this:
    // const rowRange = sheet.getRange(rowIndexToUpdate, 1, 1, sheet.getLastColumn());
    // const rowValues = rowRange.getValues()[0];
    // for (const colName in updates) {
    //   const colIndex = headers.indexOf(colName);
    //   if (colIndex !== -1) {
    //     rowValues[colIndex] = updates[colName];
    //   }
    // }
    // rowRange.setValues([rowValues]);

    // Sticking to the more direct `setValue` for columns as in original,
    // as it aligns with the `updates` dict, but note it performs one API call per cell.
    // For true batching *within GAS*, you'd re-read the row, update the array, then set the whole row back.

    // To truly optimize within GAS for multiple individual cell updates from different rows,
    // you'd collect all ranges and all new values and then use `sheet.setValues()` on a single large range
    // or `sheet.getRangeList(a1NotationStrings).setValues(nestedArrayOfValues)`.
    // However, for simplicity and direct adaptation, let's keep the setValue per cell,
    // which is still efficient enough when you're reducing HTTP calls from the client.
    
    // Applying individual updates:
    for (const [i, range] of rangesToUpdate.entries()) {
      range.setValue(valuesToSet[i][0]);
    }
  }

  if (updatedCellsCount === 0) {
      return { status: 'warning', message: 'Identifier found, but no matching columns for update were found or updated.', identifier: identifier, sheetName: sheetName };
  }

  return { status: 'success', message: `Row for identifier '${identifier}' updated successfully.`, updatedCells: updatedCellsCount, identifier: identifier };
}

/**
 * Processes a batch of update requests for a single spreadsheet sheet efficiently.
 * This is a helper function used by doPost. It performs a single, optimized write operation.
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet The target sheet object.
 * @param {Array<string>} headers The header row of the sheet.
 * @param {Array<Array<any>>} allValues All values from the sheet's data range.
 * @param {Array<Object>} batchUpdateRequests The array of individual update objects.
 * @returns {Array<Object>} Results of the updates for this specific request.
 */
function processBatchUpdates(sheet, headers, allValues, batchUpdateRequests) {
  const results = [];
  const rangesToUpdate = [];
  const valuesToSet = [];
  
  // Use a map to quickly look up row numbers by identifier
  const idColumnIndex = batchUpdateRequests.length > 0 ? batchUpdateRequests[0].idColumnIndex : undefined;
  if (idColumnIndex === undefined) {
    return [{ status: 'error', message: 'Missing idColumnIndex in batch request.' }];
  }
  
  const identifierToRowIndex = {};
  for (let i = 1; i < allValues.length; i++) {
    const cellValue = String(allValues[i][idColumnIndex - 1]);
    identifierToRowIndex[cellValue] = i + 1; // Store 1-based row number
  }
  
  // First, find all the rows to update and gather the changes
  for (const updateRequest of batchUpdateRequests) {
    const { identifier, updates, sheetName } = updateRequest;
    
    // Check if the identifier is valid and exists in our map
    const rowIndexToUpdate = identifierToRowIndex[String(identifier)];
    
    if (!updates) {
       results.push({ status: 'error', message: 'Missing `updates` object.', identifier: identifier });
       continue;
    }

    if (!rowIndexToUpdate) {
      results.push({ status: 'error', message: `Identifier '${identifier}' not found in sheet '${sheetName}'.`, identifier: identifier });
      continue;
    }
    
    let updatedCellsCount = 0;
    for (const colName in updates) {
      const colIndex = headers.indexOf(colName);
      if (colIndex !== -1) {
        // Collect range string and new value
        const a1Notation = sheet.getRange(rowIndexToUpdate, colIndex + 1).getA1Notation();
        rangesToUpdate.push(a1Notation);
        valuesToSet.push([updates[colName]]);
        updatedCellsCount++;
      } else {
        Logger.log(`Warning: Column '${colName}' not found in sheet '${sheetName}' for identifier '${identifier}'.`);
      }
    }
    
    if (updatedCellsCount > 0) {
       results.push({ status: 'success', message: `Row for identifier '${identifier}' will be updated.`, updatedCells: updatedCellsCount, identifier: identifier });
    } else {
       results.push({ status: 'warning', message: `Identifier found, but no matching columns for update were found or updated.`, identifier: identifier });
    }
  }

  // Perform the single batch write operation if there's anything to write
  if (rangesToUpdate.length > 0) {
    // Older/newer Apps Script runtimes may not support RangeList.setValues reliably.
    // Use getRangeList(...).getRanges() and call setValue on each Range to ensure compatibility.
    const rangeList = sheet.getRangeList(rangesToUpdate);
    const ranges = rangeList.getRanges();
    for (let i = 0; i < ranges.length; i++) {
      try {
        ranges[i].setValue(valuesToSet[i][0]);
      } catch (err) {
        Logger.log('Error setting value for range ' + ranges[i].getA1Notation() + ': ' + err.message);
      }
    }
  }

  return results;
}

/**
 * Handles POST requests to update a specific row or multiple rows in a sheet.
 * Expected POST JSON payload:
 * * Single update (existing format):
 * {
 * "sheetName": "API",
 * "identifier": "your_tracking_id",
 * "idColumnIndex": 3, // Column index (1-based) where identifier is found
 * "updates": {
 * "Delivery Status": "Delivered",
 * "Amount Status": 1200
 * }
 * }
 * * Batch update (new format - an array of update objects):
 * [
 * {
 * "sheetName": "API",
 * "identifier": "order123",
 * "idColumnIndex": 3,
 * "updates": {
 * "Moderator's Name": "John Doe"
 * }
 * },
 * {
 * "sheetName": "API",
 * "identifier": "order456",
 * "idColumnIndex": 3,
 * "updates": {
 * "Moderator's Name": "Jane Smith"
 * }
 * }
 * ]
 */
/**
 * Handles POST requests to update a specific row or multiple rows in a sheet.
 */
function doPost(e) {
  try {
    const requestBody = JSON.parse(e.postData.contents);
    Logger.log('Received POST data: ' + JSON.stringify(requestBody));

    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    
    // Check if it's a batch update or a single update
    const isBatch = Array.isArray(requestBody);
    
    const sheetName = isBatch ? requestBody[0]?.sheetName : requestBody.sheetName;
    if (!sheetName) {
        return createJsonResponse({ status: 'error', message: 'Missing sheetName in request or empty batch.' }, 400);
    }

    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) {
      return createJsonResponse({ status: 'error', message: `Sheet '${sheetName}' not found.` }, 404);
    }
    
    const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
    const allValues = sheet.getDataRange().getValues();

    if (isBatch) {
      const results = processBatchUpdates(sheet, headers, allValues, requestBody);
      return createJsonResponse({ status: 'success', message: 'Batch update processed.', results: results });
    } else {
      // Single update logic (re-using the old helper for clarity)
      const result = processSingleUpdateRequest(sheet, headers, allValues, requestBody);
      return createJsonResponse(result);
    }

  } catch (error) {
    Logger.log('Error in doPost: ' + error.message);
    if (error.message.includes("Unexpected token") || error.message.includes("is not valid JSON")) {
      return createJsonResponse({ status: 'error', message: 'Invalid JSON payload. Please send valid JSON.', details: error.message }, 400);
    }
    return createJsonResponse({ status: 'error', message: 'Failed to process update.', details: error.message }, 500);
  }
}