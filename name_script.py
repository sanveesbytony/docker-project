import pandas as pd
import asyncio
from playwright.async_api import async_playwright, Page, expect
import requests
import os
import sys
import time
import signal

# --- Configuration (unchanged) ---
ADMIN_URL = "https://sanveesbytony.com/admin"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "sanenime@gmail.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "25694470910")

SELECTOR_EMAIL_INPUT = "#data\\.email"
SELECTOR_PASSWORD_INPUT = "#data\\.password"
SELECTOR_LOGIN_BUTTON = "#form > div.fi-form-actions > div > button"
DASHBOARD_READY_SELECTOR = "main > div > section"

# --- Google Sheets Web App Configuration ---
# Provide your deployed Apps Script Web App URL (the /exec URL).
WEB_APP_URL = os.environ.get(
    "WEBAPP_URL",
    os.environ.get(
        "SHEETS_WEB_APP_URL",
        "https://script.google.com/macros/s/AKfycbx34ODMPZFRG8DNOzaYVzQwfxE7w5f2PWYM3yNpxUAM1UFELkXAiyG_B2jWS53H1DUj9A/exec",
    ),
).strip()
SHEET_NAME = "API"
ORDER_NUMBER_COLUMN = "Order Number"
MODERATOR_NAME_COLUMN = "Moderator's Name"

# --- Concurrency Setting (unchanged) ---
CONCURRENT_TABS = 50


# --- Playwright Login Function (unchanged) ---
async def login(page: Page):
    print(f"Navigating to login page: {ADMIN_URL}")
    try:
        await page.goto(ADMIN_URL, wait_until="networkidle")
    except Exception as e:
        print(f"Error navigating to login page: {e}")
        return False

    print("Entering credentials...")
    try:
        await page.fill(SELECTOR_EMAIL_INPUT, ADMIN_EMAIL)
        await page.fill(SELECTOR_PASSWORD_INPUT, ADMIN_PASSWORD)
    except Exception as e:
        print(f"Error finding/filling login elements: {e}")
        return False

    print("Attempting login...")
    try:
        await page.click(SELECTOR_LOGIN_BUTTON)
        await page.wait_for_timeout(1000)
    except Exception as e:
        print(f"Error clicking login button: {e}")
        return False

    print("Waiting for dashboard to load and become ready...")
    try:
        await page.wait_for_selector(DASHBOARD_READY_SELECTOR, state="visible", timeout=30000)
        print("Dashboard element found and is visible.")
        print("Login successful.")
        return True
    except Exception as e:
        print(f"Login failed or dashboard did not load/become visible within timeout: {e}")
        return False


# --- Modified: Function to process a single invoice page ---
async def process_invoice_page(page: Page, index: int, order_number: str, df_sales_ref: pd.DataFrame, context):
    """
    Navigates to an invoice URL, extracts moderator name (if present),
    and updates the DataFrame. This function operates on a single Playwright Page object.
    """
    invoice_url = f"https://sanveesbytony.com/order/{order_number}/invoice"
    print(f"Processing row {index} | Order: {order_number} | Navigating to: {invoice_url}")

    try:
        await page.goto(invoice_url, wait_until="networkidle")

        moderator_name_selector = "p:has(span.gry-color.small:has-text('Created by:')) span.strong"

        # --- KEY CHANGE HERE ---
        # Instead of wait_for_selector, use locator.text_content() with a shorter timeout
        # and handle the TimeoutError specifically.
        try:
            # Using page.locator().text_content() is more direct.
            # We add a specific timeout for this locator check.
            moderator_name = await page.locator(moderator_name_selector).text_content(timeout=3000)  # 3 seconds timeout
            print(f"Found Moderator's Name for {order_number}: {moderator_name}")
            df_sales_ref.at[index, MODERATOR_NAME_COLUMN] = moderator_name.strip()

        except Exception as locator_error:  # Catch any error from text_content, often TimeoutError
            if "Timeout 3000ms exceeded" in str(locator_error):
                print(
                    f"Moderator's Name element not found for {order_number} (row {index}) within timeout. Assuming customer created.")
                df_sales_ref.at[index, MODERATOR_NAME_COLUMN] = "CUSTOMER CREATED"  # Assign a specific value
            else:
                print(f"Error finding Moderator's Name for {order_number} (row {index}): {locator_error}")
                df_sales_ref.at[index, MODERATOR_NAME_COLUMN] = "ERROR"  # General error

    except Exception as e:  # Catch errors during page navigation itself
        print(f"Error navigating or processing {order_number} (row {index}): {e}")
        df_sales_ref.at[
            index, MODERATOR_NAME_COLUMN] = "NAVIGATION ERROR"  # Assign a specific error for navigation failures

    finally:
        await page.close()


def _require_web_app_url():
    if not WEB_APP_URL:
        raise RuntimeError(
            "Missing Google Sheets Web App URL. Set env var SHEETS_WEB_APP_URL or edit WEB_APP_URL in the script."
        )


def fetch_sheet_data(sheet_name: str) -> pd.DataFrame:
    _require_web_app_url()
    try:
        resp = requests.get(WEB_APP_URL, params={"sheetName": sheet_name}, timeout=60)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Error loading Google Sheet: {e}")
    payload = resp.json()
    if payload.get("status") != "success":
        raise RuntimeError(f"Web App GET failed: {payload}")
    data = payload.get("data", [])
    return pd.DataFrame(data)


def post_batch_updates(sheet_name: str, id_column_index_1_based: int, updates: list[dict]):
    _require_web_app_url()
    if not updates:
        return

    payload = []
    for item in updates:
        payload.append(
            {
                "sheetName": sheet_name,
                "identifier": item["identifier"],
                "idColumnIndex": id_column_index_1_based,
                "updates": item["updates"],
            }
        )

    try:
        resp = requests.post(WEB_APP_URL, json=payload, timeout=120)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Error saving data to Google Sheet: {e}")
    result = resp.json()
    if result.get("status") != "success":
        raise RuntimeError(f"Web App POST failed: {result}")


# --- Data Fetching and Saving Function (unchanged outside process_invoice_page call) ---
async def fetch_and_save_moderator_names():
    global df_sales

    try:
        df_sales = fetch_sheet_data(SHEET_NAME)
        print(f"Successfully loaded '{SHEET_NAME}' from Google Sheets Web App")
    except Exception as e:
        print(f"Error loading Google Sheet: {e}")
        return

    if MODERATOR_NAME_COLUMN not in df_sales.columns:
        df_sales[MODERATOR_NAME_COLUMN] = None
        print(f"Added new column: '{MODERATOR_NAME_COLUMN}'")

    if MODERATOR_NAME_COLUMN in df_sales.columns:
        df_sales[MODERATOR_NAME_COLUMN] = df_sales[MODERATOR_NAME_COLUMN].astype(str)

    async with async_playwright() as p:
        browser = None
        context = None
        try:
            print("Launching new browser and logging in...")
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            await context.add_init_script(
                "window.print = function() { console.log('Print function suppressed by Playwright.'); };")
            print("Injected script to suppress print dialogs.")

            login_page = await context.new_page()
            if not await login(login_page):
                print("Failed to log in. Exiting.")
                await login_page.close()
                return
            await login_page.close()

            print("Starting concurrent data fetching process...")

            headers = list(df_sales.columns)
            if ORDER_NUMBER_COLUMN not in headers:
                raise RuntimeError(f"Missing '{ORDER_NUMBER_COLUMN}' column in sheet headers: {headers}")
            id_column_index_1_based = headers.index(ORDER_NUMBER_COLUMN) + 1

            rows_to_process = []
            for index, row in df_sales.iterrows():
                current_moderator_name = str(row.get(MODERATOR_NAME_COLUMN, "")).strip().lower()
                # Column N in the sheet, but we rely on header name.
                if current_moderator_name in ["", "none", "nan", "error", "customer created", "navigation error"]:
                    rows_to_process.append((index, row.get(ORDER_NUMBER_COLUMN)))

            total_rows = len(rows_to_process)
            print(f"Total rows to process: {total_rows}")

            for i in range(0, total_rows, CONCURRENT_TABS):
                batch_rows = rows_to_process[i: i + CONCURRENT_TABS]
                tasks = []
                batch_updates = []

                print(f"\nProcessing batch starting from row {i} (batch size: {len(batch_rows)})...")

                for index, order_number in batch_rows:
                    if pd.isna(order_number):
                        print(f"Skipping row {index} in batch: No '{ORDER_NUMBER_COLUMN}' found.")
                        continue

                    page = await context.new_page()
                    tasks.append(process_invoice_page(page, index, order_number, df_sales, context))

                await asyncio.gather(*tasks)

                for index, order_number in batch_rows:
                    if pd.isna(order_number):
                        continue
                    moderator_value = str(df_sales.at[index, MODERATOR_NAME_COLUMN]) if MODERATOR_NAME_COLUMN in df_sales.columns else ""
                    batch_updates.append(
                        {
                            "identifier": str(order_number),
                            "updates": {MODERATOR_NAME_COLUMN: moderator_value},
                        }
                    )

                print(f"Batch processed. Saving progress for rows {i} to {min(i + CONCURRENT_TABS, total_rows)} to Google Sheet...")
                post_batch_updates(SHEET_NAME, id_column_index_1_based, batch_updates)

            print("\nData fetching complete for all pending rows.")
            # Final save: update all processed rows in a single batch to be safe.
            final_updates = []
            for index, order_number in rows_to_process:
                if pd.isna(order_number):
                    continue
                moderator_value = str(df_sales.at[index, MODERATOR_NAME_COLUMN]) if MODERATOR_NAME_COLUMN in df_sales.columns else ""
                final_updates.append(
                    {
                        "identifier": str(order_number),
                        "updates": {MODERATOR_NAME_COLUMN: moderator_value},
                    }
                )
            post_batch_updates(SHEET_NAME, id_column_index_1_based, final_updates)

        except Exception as e:
            print(f"An unexpected error occurred during the main process: {e}")
            # We keep already-sent batches in the sheet; no local persistence here.
        finally:
            if browser:
                await browser.close()
            print("Browser closed.")


# --- Interruption Handler (unchanged) ---
df_sales = None


def signal_handler(signum, frame):
    print("\nInterruption detected! Attempting to save current progress...")
    global df_sales
    print("No local file is used; any completed batches were already saved to Google Sheets.")
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)

if __name__ == "__main__":
    asyncio.run(fetch_and_save_moderator_names())