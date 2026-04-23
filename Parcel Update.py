import asyncio
import re
import signal
import sys
import time
import logging
import json
import pandas as pd
import aiohttp
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# --- Configuration ---
# Replace this with your deployed Google Apps Script Web App URL (doGet/doPost endpoints)
import os as _os
WEBAPP_URL = _os.environ.get("WEBAPP_URL", "https://script.google.com/macros/s/AKfycbx34ODMPZFRG8DNOzaYVzQwfxE7w5f2PWYM3yNpxUAM1UFELkXAiyG_B2jWS53H1DUj9A/exec")  # can be overridden via env
USERNAME = _os.environ.get('STEADFAST_USERNAME', "")
PASSWORD = _os.environ.get('STEADFAST_PASSWORD', "")
MAX_CONCURRENT_TABS = 5  # Reduced for stability
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

# --- Helper functions for Excel Interaction ---
async def fetch_sheet(session, sheet_name):
    """Fetches sheet data from deployed Google Apps Script web app and returns a DataFrame."""
    params = {"sheetName": sheet_name}
    try:
        async with session.get(WEBAPP_URL, params=params, timeout=60) as resp:
            text = await resp.text()
            data = json.loads(text)
            if data.get('status') != 'success':
                logging.error(f"Failed to fetch sheet '{sheet_name}': {data.get('message')}")
                return None
            rows = data.get('data', [])
            if not rows:
                # return empty DataFrame with no rows
                return pd.DataFrame(columns=[])
            df = pd.DataFrame(rows)
            return df
    except Exception as e:
        logging.error(f"Error fetching sheet '{sheet_name}' from web app: {e}")
        return None


async def send_batch_updates(session, batch_updates):
    """Sends a batch of update requests to the Google Apps Script web app via POST.

    Expects batch_updates to be a list of objects in the format the Apps Script doPost expects.
    """
    if not batch_updates:
        return None
    try:
        headers = {'Content-Type': 'application/json'}
        async with session.post(WEBAPP_URL, data=json.dumps(batch_updates), headers=headers, timeout=120) as resp:
            text = await resp.text()
            try:
                return json.loads(text)
            except Exception:
                logging.error(f"Unexpected response from web app: {text}")
                return None
    except Exception as e:
        logging.error(f"Error sending batch updates to web app: {e}")
        return None

# --- Your existing web scraping functions (modified for async) ---
async def get_status_and_amount(page, identifier):
    try:
        search_box = await page.wait_for_selector("input#searchInput", timeout=30000)
        await search_box.fill(str(identifier))
        await search_box.press("Enter")

        await page.wait_for_selector("#searchResults div li a p", timeout=30000)
        first_result = await page.query_selector("#searchResults div li a p")
        await first_result.click()

        await page.wait_for_selector(".alert", timeout=30000)
        status_elements = await page.query_selector_all(".alert")
        status, amount = "Not Found", "Not Found"

        for element in status_elements:
            text = await element.inner_text()
            if "Cancelled" in text:
                status = "Cancelled"
                break
            elif "Partial Delivered" in text:
                status = "Partial Delivered"
                break
            elif "Delivered" in text:
                status = "Delivered"
                break
            elif "Pending" in text:
                status = "Pending"
                break

        cod_elements = await page.query_selector_all("h6:has-text('COD: ৳')")
        if cod_elements:
            cod_text = await cod_elements[0].inner_text()
            match = re.search(r'৳ (\d+)', cod_text)
            if match:
                amount = int(match.group(1))

        logging.info(f"Status for {identifier}: {status}, Amount: {amount}")
        return status, amount
    except Exception as e:
        logging.error(f"Error fetching status for {identifier}: {str(e)}")
        return "Error", "Error"

async def get_status_for_identifier_with_retry(context, identifier):
    for attempt in range(MAX_RETRIES):
        try:
            page = await context.new_page()
            await page.goto("https://www.packzy.com/dashboard", timeout=60000)
            return await get_status_and_amount(page, identifier)
        except PlaywrightTimeoutError as e:
            logging.warning(f"Timeout error for {identifier} on attempt {attempt + 1}/{MAX_RETRIES}: {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY)
            else:
                logging.error(f"Failed to fetch status for {identifier} after {MAX_RETRIES} attempts.")
                return "Error", "Error"
        except Exception as e:
            logging.error(f"An unexpected error occurred for {identifier}: {e}")
            return "Error", "Error"
        finally:
            if 'page' in locals() and not page.is_closed():
                await page.close()

# --- Modified function to update DataFrame statuses ---
async def process_and_update_sheet(context, sheet_name, id_col_name, delivery_col_name, amount_col_name):
    """
    Fetches data from local Excel sheet, scrapes website in parallel, and updates a DataFrame.
    """
    logging.info(f"Processing sheet: {sheet_name}")

    # Use the deployed web app to fetch sheet contents instead of local Excel
    async with aiohttp.ClientSession() as session:
        df = await fetch_sheet(session, sheet_name)
        if df is None:
            logging.error(f"Could not fetch sheet '{sheet_name}'. Skipping.")
            return
        logging.info(f"Successfully fetched '{sheet_name}' from web app. Rows: {len(df)}")

    logging.info(f"Fetched {len(df)} rows from sheet '{sheet_name}'.")

    price_col_name = "Price"
    price_change_received_col_name = "Price Change Received"

    df[delivery_col_name] = df[delivery_col_name].astype(str)

    rows_to_process = df[df[delivery_col_name].isin(["", "nan", "Pending", "Approval Pending", "None"])]
    
    logging.info(f"Found {len(rows_to_process)} rows to process based on Delivery Status criteria.")

    identifiers_to_process = rows_to_process[id_col_name].dropna().unique().tolist()
    
    # Prepare for batching updates to Google Sheets
    batch_update_requests = []
    BATCH_SIZE = 50
    processed_count = 0  # count of identifiers processed to flush periodically
    # Determine id column index (1-based) for Apps Script updates
    try:
        headers = df.columns.tolist()
        id_col_index = headers.index(id_col_name) + 1
    except Exception:
        logging.error(f"ID column '{id_col_name}' not found in sheet '{sheet_name}'.")
        return

    # Process identifiers in concurrent batches: fetch statuses for a small batch, then immediately
    # process corresponding rows and send updates in batches of BATCH_SIZE to avoid holding everything
    for i in range(0, len(identifiers_to_process), MAX_CONCURRENT_TABS):
        batch = identifiers_to_process[i:i+MAX_CONCURRENT_TABS]
        tasks = [get_status_for_identifier_with_retry(context, identifier) for identifier in batch]
        results = await asyncio.gather(*tasks)

        # For each identifier in this small batch, update its rows immediately
        for identifier, result in zip(batch, results):
            scraped_status, scraped_amount = result

            # find all rows in rows_to_process that have this identifier
            matching_indices = rows_to_process[rows_to_process[id_col_name] == identifier].index.tolist()
            if not matching_indices:
                continue

            if scraped_status == "Error":
                for idx in matching_indices:
                    logging.error(f"Row {idx + 2} (ID: {identifier}): Skipping updates due to scraping error.")
                continue

            for idx in matching_indices:
                row = df.loc[idx]
                current_delivery_status = str(row.get(delivery_col_name) or "").strip()
                current_amount_status = str(row.get(amount_col_name) or "").strip()
                current_price = str(row.get(price_col_name) or "").strip()
                current_price_change_received = str(row.get(price_change_received_col_name) or "").strip()

                scraped_amount_int = None
                if scraped_amount and scraped_amount != "Not Found":
                    try:
                        scraped_amount_int = int(scraped_amount)
                    except ValueError:
                        pass

                current_price_int = None
                if current_price and current_price not in ["nan", "None"]:
                    try:
                        current_price_int = int(float(current_price))
                    except (ValueError, TypeError):
                        pass

                updates_needed = {}

                if scraped_status == "Delivered":
                    if scraped_amount_int is not None and current_price_int is not None and scraped_amount_int == current_price_int:
                        if current_delivery_status != "Delivered":
                            updates_needed[delivery_col_name] = "Delivered"
                        if current_price_change_received:
                            updates_needed[price_change_received_col_name] = ""
                    else:
                        if current_delivery_status != "Price Changed":
                            updates_needed[delivery_col_name] = "Price Changed"
                        if scraped_amount_int is not None and str(scraped_amount_int) != current_price_change_received:
                            updates_needed[price_change_received_col_name] = scraped_amount_int
                    if amount_col_name in df.columns:
                        updates_needed[amount_col_name] = ""

                elif scraped_status == "Cancelled":
                    if current_delivery_status != "Cancelled":
                        updates_needed[delivery_col_name] = "Cancelled"
                    if amount_col_name in df.columns:
                        updates_needed[amount_col_name] = ""

                elif scraped_status in ["Pending", "Approval Pending"]:
                    if current_delivery_status not in ["Pending", "Approval Pending"]:
                        updates_needed[delivery_col_name] = scraped_status
                    if amount_col_name in df.columns:
                        updates_needed[amount_col_name] = ""

                elif scraped_status == "Partial Delivered":
                    if current_delivery_status != "Partial Delivered":
                        updates_needed[delivery_col_name] = "Partial Delivered"
                    if scraped_amount_int is not None and str(scraped_amount_int) != current_amount_status:
                        updates_needed[amount_col_name] = scraped_amount_int

                elif scraped_status == "Not Found":
                    if current_delivery_status != "Not Found":
                        updates_needed[delivery_col_name] = "Not Found"
                    if amount_col_name in df.columns:
                        updates_needed[amount_col_name] = ""

                else:
                    if current_delivery_status in ["", "Pending", "Approval Pending", "Not Found", "nan", "None"] and scraped_status != current_delivery_status:
                        updates_needed[delivery_col_name] = scraped_status
                    if current_amount_status in ["", "Not Found", "nan", "None"] and scraped_amount_int is not None and str(scraped_amount_int) != current_amount_status:
                        updates_needed[amount_col_name] = scraped_amount_int

                if updates_needed:
                    logging.info(f"Row {idx + 2} (ID: {identifier}): Applying updates to DataFrame: {updates_needed}")
                    for col, value in updates_needed.items():
                        df.loc[idx, col] = value

                    update_obj = {
                        "sheetName": sheet_name,
                        "identifier": identifier,
                        "idColumnIndex": id_col_index,
                        "updates": updates_needed
                    }
                    batch_update_requests.append(update_obj)

                    # If we have many updates, or we've processed enough identifiers, flush to web app
                    if len(batch_update_requests) >= BATCH_SIZE:
                        async with aiohttp.ClientSession() as session:
                            resp = await send_batch_updates(session, batch_update_requests)
                            logging.info(f"Sent batch of {len(batch_update_requests)} updates. Response: {resp}")
                        batch_update_requests = []
                else:
                    logging.info(f"Row {idx + 2} (ID: {identifier}): No updates needed for DataFrame.")
            # count this identifier as processed and flush every BATCH_SIZE identifiers
            processed_count += 1
            if processed_count % BATCH_SIZE == 0:
                if batch_update_requests:
                    async with aiohttp.ClientSession() as session:
                        resp = await send_batch_updates(session, batch_update_requests)
                        logging.info(f"Sent periodic batch after {processed_count} identifiers. Response: {resp}")
                    batch_update_requests = []

    # Send any remaining updates
    if batch_update_requests:
        async with aiohttp.ClientSession() as session:
            resp = await send_batch_updates(session, batch_update_requests)
            logging.info(f"Sent final batch of {len(batch_update_requests)} updates. Response: {resp}")

    # Note: we no longer write to local Excel. The Google Apps Script updates the spreadsheet.

# Signal handler for safe exit
def signal_handler(sig, frame):
    logging.info("Signal received, exiting gracefully.")
    sys.exit(0)

# Main function
async def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # No local Excel file is used anymore; sheet reads/writes go through the deployed Web App.

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            logging.info("Navigating to dashboard and logging in...")
            await page.goto("https://www.packzy.com/dashboard", timeout=60000)
            await page.fill("input[name='email']", USERNAME)
            await page.fill("input#pass", PASSWORD)
            await page.click("button:has-text('Login')")
            await page.wait_for_selector("#searchInput", timeout=60000)
            logging.info("Successfully logged in.")
            await page.close() # Close login page, no longer needed

            await process_and_update_sheet(
                context,
                "API",
                id_col_name='Order Number',
                delivery_col_name='Delivery Status',
                amount_col_name='Amount Status'
            )
            await process_and_update_sheet(
                context,
                "CSV",
                id_col_name='ID Numbers',
                delivery_col_name='Delivery Status',
                amount_col_name='Amount Status'
            )

            logging.info("All sheets processed.")

        except Exception as e:
            logging.error(f"Error during main execution: {str(e)}")
            print(f"Error during main execution: {str(e)}")

        finally:
            await browser.close()
            logging.info("Browser closed.")
            time.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())
