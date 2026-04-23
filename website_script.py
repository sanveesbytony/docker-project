import asyncio
import sys
import time
from datetime import datetime

import requests
from playwright.async_api import async_playwright, Page, expect

# Credentials and URLs
import os as _os
ADMIN_URL = "https://sanveesbytony.com/admin"
ADMIN_EMAIL = _os.environ.get("ADMIN_EMAIL", "sanenime@gmail.com")
ADMIN_PASSWORD = _os.environ.get("ADMIN_PASSWORD", "25694470910")
# Prefer COURIER_WEBAPP_URL, fall back to APPS_SCRIPT_URL, then default
APPS_SCRIPT_URL = _os.environ.get("COURIER_WEBAPP_URL", _os.environ.get("APPS_SCRIPT_URL", "https://script.google.com/macros/s/AKfycbw77x5WhZUB23CF-fR0CSIv6qbkzXmrnS_HqgwPEltxQnyFP1RO6cT05iXYdw3KOwk/exec"))

BASE_SHIPMENT_URL = "https://sanveesbytony.com/admin/shipments"
BASE_INVOICE_URL = "https://sanveesbytony.com/order/{sbt_id}/invoice"

# Playwright Configuration
HEADLESS_MODE = True  # Set to False to see the browser UI
LOOP_DELAY_SECONDS = 30  # Time to wait if no new data is found
BATCH_SIZE = 20       # <<< ADD THIS LINE
SUBMISSION_BATCH_SIZE = 100
# Selectors
SELECTOR_EMAIL_INPUT = "#data\\.email"
SELECTOR_PASSWORD_INPUT = "#data\\.password"
SELECTOR_LOGIN_BUTTON = "#form > div.fi-form-actions > div > button"
DASHBOARD_READY_SELECTOR = "main > div > section"

# --- Helper Functions ---

async def login(page: Page):
    """Logs into the admin panel."""
    print("Attempting to log in...")
    await page.goto(ADMIN_URL, wait_until="networkidle")
    await page.fill(SELECTOR_EMAIL_INPUT, ADMIN_EMAIL)
    await page.fill(SELECTOR_PASSWORD_INPUT, ADMIN_PASSWORD)
    await page.click(SELECTOR_LOGIN_BUTTON)
    try:
        await expect(page.locator(DASHBOARD_READY_SELECTOR)).to_be_visible(timeout=30000)
        print("Login successful.")
        return True
    except Exception as e:
        print(f"Login failed: {e}")
        return False



# --- Date Selection Helper ---
def get_target_date():
    """
    Gets the target date from the environment variable TARGET_DATE (format: YYYY-MM-DD or MM-DD-YYYY).
    Returns None if not set or invalid.
    """
    date_str = _os.environ.get("TARGET_DATE")
    if not date_str:
        print("TARGET_DATE not set in environment. Please set a date from the web interface.")
        return None
    # Accept both YYYY-MM-DD and MM-DD-YYYY
    try:
        if '-' in date_str:
            parts = date_str.split('-')
            if len(parts[0]) == 4:
                # YYYY-MM-DD
                return date_str
            elif len(parts[2]) == 4:
                # MM-DD-YYYY -> convert to YYYY-MM-DD
                return f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
    except Exception:
        pass
    print(f"Invalid TARGET_DATE format: {date_str}")
    return None


def get_courier_sheets_from_google():
    """Fetches the list of all courier sheet names from the Google Sheet."""
    print("Fetching courier sheet names from Google Sheet...")
    try:
        params = {"action": "getAllCourierSheets"}
        response = requests.get(APPS_SCRIPT_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if "courierSheets" in data:
            print(f"Found sheets: {data['courierSheets']}")
            return data["courierSheets"]
        else:
            print(f"Error from Apps Script: {data.get('error', 'Could not parse sheet names')}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching sheet names from Google Sheet: {e}")
        return None

def fetch_seen_ids_from_sheet():
    """Fetches all existing SBT IDs from the Google Sheet."""
    print("Fetching all seen SBT IDs from Google Sheet...")
    try:
        params = {"action": "getAllSbtIds"}
        response = requests.get(APPS_SCRIPT_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if "sbtIds" in data:
            sbt_ids_set = set(data["sbtIds"])
            print(f"Found {len(sbt_ids_set)} existing IDs in the Google Sheet.")
            return sbt_ids_set
        else:
            print(f"Error from Apps Script: {data.get('error', 'Unknown error')}")
            return set()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching IDs from Google Sheet: {e}")
        return set()

def send_data_to_sheet(payload):
    """Sends data to the Google Sheet via a POST request."""
    try:
        headers = {"Content-Type": "application/json"}
        response = requests.post(APPS_SCRIPT_URL, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error sending data to Google Sheet: {e}")
        return {"status": "error", "message": str(e)}

async def collect_single_order_details(page: Page, sbt_id: str):
    """
    Fetches detailed order info for a single SBT ID and returns the details.
    This function will no longer send data to the sheet.
    """
    invoice_url = BASE_INVOICE_URL.format(sbt_id=sbt_id)
    print(f"  > Scraping details for {sbt_id} at {invoice_url}")

    details = {}
    try:
        await page.goto(invoice_url, wait_until="domcontentloaded")
        # Ensure we are on the correct page by checking for a unique element
        await expect(page.locator('xpath=/html/body/div/div[1]/table[2]/tbody')).to_be_visible()

        # Scrape all the details using the new explicit XPaths
        date_locator = page.locator('xpath=/html/body/div/div[1]/table[2]/tbody/tr[3]/td[2]/span[2]')
        customer_name_locator = page.locator('xpath=/html/body/div/div[2]/table/tbody/tr[2]/td')
        address_locator = page.locator('xpath=/html/body/div/div[2]/table/tbody/tr[3]/td')
        price_locator = page.locator('xpath=/html/body/div/div[4]/table/tbody/tr/td[2]/table/tbody/tr[1]/td')
        shipping_cost_locator = page.locator('xpath=/html/body/div/div[4]/table/tbody/tr/td[2]/table/tbody/tr[2]/td')
        total_amount_locator = page.locator('xpath=/html/body/div/div[4]/table/tbody/tr/td[2]/table/tbody/tr[3]/td/b')

        details = {
            "date": await date_locator.text_content(),
            "customerName": await customer_name_locator.text_content(),
            "address": await address_locator.text_content(),
            "price": await price_locator.text_content(),
            "shippingCost": await shipping_cost_locator.text_content(),
            "totalAmount": await total_amount_locator.text_content(),
        }

        # Clean up the data
        for key, value in details.items():
            details[key] = value.strip().replace(" Taka", "").replace(",", "")

    except Exception as e:
        print(f"  > Error scraping details for {sbt_id}: {e}")
        # Return an empty dictionary to signal an error
        details = {}

    return details


async def process_new_orders(page: Page, start_date_str: str):
    """
    Finds new IDs from the website (stopping when an existing ID is found),
    compares them against existing IDs, then scrapes and saves details for
    only the new IDs in batches.
    """
    global seen_sbt_ids
    print("\n--- Starting to find new orders to scrape ---")

    # Accept either ISO (YYYY-MM-DD) or US-style (MM-DD-YYYY) input
    parsed = None
    for fmt in ("%Y-%m-%d", "%m-%d-%Y"):
        try:
            parsed = datetime.strptime(start_date_str, fmt)
            break
        except ValueError:
            continue
    if not parsed:
        raise ValueError(f"Invalid start_date format: {start_date_str}. Expected YYYY-MM-DD or MM-DD-YYYY")
    date_obj = parsed
    formatted_date = date_obj.strftime("%Y-%m-%d")

    current_page = 1
    website_orders = []
    should_stop_page_discovery = False  # New flag to control the outer loop

    while not should_stop_page_discovery:
        # Step 1: Discover all SBT IDs from the website for the given date, stopping on a match.
        url = (
            f"{BASE_SHIPMENT_URL}?tableFilters[created_at][date_start]={formatted_date}+00%3A00%3A00&page={current_page}"
        )
        print(f"Navigating to page {current_page} to discover IDs: {url}")
        try:
            # Increase timeout for navigation as the first page load can sometimes be slow
            await page.goto(url, wait_until="networkidle", timeout=60000)
        except Exception as e:
            print(f"Error navigating to page {current_page}: {e}. Skipping this page.")
            current_page += 1
            continue

        rows = await page.locator("tbody > tr").all()
        if not rows:
            print("No results found on this page. Ending ID discovery.")
            should_stop_page_discovery = True
            break  # Exit the while loop

        found_old_order_on_page = False
        orders_on_current_page = []

        for i in range(len(rows)):
            sbt_id_selector = f"//tbody/tr[{i + 1}]/td[2]//span"
            courier_selector = f"//tbody/tr[{i + 1}]/td[4]//span"

            try:
                sbt_id = (await page.locator(sbt_id_selector).text_content()).strip()
                courier_name = (await page.locator(courier_selector).text_content()).strip()

                if sbt_id in seen_sbt_ids:
                    # Found an order that is already in the sheet. Stop immediately.
                    print(f"  > Found existing order {sbt_id}. Stopping page discovery.")
                    found_old_order_on_page = True
                    break  # Break the inner for loop
                else:
                    # Found a NEW order. Collect it.
                    orders_on_current_page.append({"sbt_id": sbt_id, "courier_name": courier_name})
                    print(f"  > Identified as new order: {sbt_id} | Courier: {courier_name} (Page {current_page})")

            except Exception as e:
                print(f"Error processing row {i + 1}: {e}")
                continue

        # Add all newly discovered orders from this page to the main list
        website_orders.extend(orders_on_current_page)

        if found_old_order_on_page:
            # We stopped because we found an old order, so we break the outer while loop
            should_stop_page_discovery = True
        elif len(rows) < 10:
            # This happens on the last page of results, even if all are new.
            print(f"Fewer than 10 results on page {current_page}. Assuming last page. Ending ID discovery.")
            should_stop_page_discovery = True

        current_page += 1

    # After page discovery, website_orders ONLY contains NEW orders.
    new_orders_to_scrape = website_orders

    print(f"\nDiscovered {len(new_orders_to_scrape)} truly NEW orders across all checked pages.")

    if not new_orders_to_scrape:
        print("No new orders to scrape. Ending process.")
        return False

    print(f"\n--- Starting batched scraping for {len(new_orders_to_scrape)} new orders ---")

    all_results_for_payload = []

    # Step 2: Scrape details for the *new* IDs in manageable batches.
    # The rest of the function remains the same, as the discovery step now pre-filters the list.

    for i in range(0, len(new_orders_to_scrape), BATCH_SIZE):
        batch_orders = new_orders_to_scrape[i:i + BATCH_SIZE]
        print(
            f"Processing batch {i // BATCH_SIZE + 1} of {len(new_orders_to_scrape) // BATCH_SIZE + 1} with {len(batch_orders)} orders...")

        scrape_tasks = []
        for order_info in batch_orders:
            # Important: We must add the newly scraped ID to the seen set *before* sending it,
            # so the next loop doesn't try to re-scrape it if the sheet save is delayed.
            seen_sbt_ids.add(order_info["sbt_id"])

            new_page = await page.context.new_page()
            task = asyncio.create_task(collect_single_order_details(new_page, order_info["sbt_id"]))
            scrape_tasks.append({"task": task, "page": new_page, **order_info})

        batch_results = await asyncio.gather(*[t["task"] for t in scrape_tasks])

        for t in scrape_tasks:
            await t["page"].close()

        for j, details in enumerate(batch_results):
            if details:
                order_info = batch_orders[j]
                all_results_for_payload.append({
                    "courier": order_info["courier_name"],
                    "sbtId": order_info["sbt_id"],
                    "details": details
                })
            # Note: If details is empty (scraping error), the ID is still in `seen_sbt_ids`,
            # so it won't be re-scraped, but it won't be saved to the sheet either. This is safe.

    print("--- Scraping complete. Starting batched data submission ---")

    # Step 3: Submit the scraped data to the Google Sheet.
    for i in range(0, len(all_results_for_payload), SUBMISSION_BATCH_SIZE):
        batch_to_send = all_results_for_payload[i:i + SUBMISSION_BATCH_SIZE]

        payload = {
            "action": "saveFullOrderDataBatch",
            "data": batch_to_send
        }

        print(f"Sending a batch request for {len(batch_to_send)} orders to the Apps Script.")
        response = send_data_to_sheet(payload)

        if response.get("status") == "error":
            print(f"Error submitting batch: {response.get('message')}")
        else:
            print(f"Apps Script Batch Response: {response}")

    print("--- All data batches sent successfully ---")

    return True


async def main():
    """Main function to run the continuous automation loop."""
    global seen_sbt_ids

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS_MODE)
        context = await browser.new_context()
        page = await context.new_page()

        if not await login(page):
            await browser.close()
            return


        while True:
            # Step 1: Fetch all existing IDs from the Google Sheet
            seen_sbt_ids = fetch_seen_ids_from_sheet()

            target_date = get_target_date()
            if not target_date:
                print("No valid target date set. Stopping.")
                break

            new_data_was_found = await process_new_orders(page, target_date)

            if not new_data_was_found:
                print(f"\nLoop complete. No new data found. Waiting for {LOOP_DELAY_SECONDS} seconds...")
                time.sleep(LOOP_DELAY_SECONDS)
            else:
                print("\nLoop complete. Restarting immediately to check for more data.")

        await browser.close()


if __name__ == "__main__":
    if not all([ADMIN_EMAIL, ADMIN_PASSWORD, APPS_SCRIPT_URL]):
        print("Error: Missing ADMIN_EMAIL/ADMIN_PASSWORD/APPS_SCRIPT_URL. Please set config.")
        sys.exit(1)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProcess interrupted by user. Exiting.")