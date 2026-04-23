# -- coding: utf-8 --
import os
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import requests
import json

# --- Configuration ---
USER_EMAIL = os.environ.get('STEADFAST_USERNAME')
USER_PASSWORD = os.environ.get('STEADFAST_PASSWORD')
# GOOGLE_WEB_APP_URL can be provided via env var `GOOGLE_WEB_APP_URL` when running in container
GOOGLE_WEB_APP_URL = os.environ.get('GOOGLE_WEB_APP_URL', "https://script.google.com/macros/s/AKfycbzFweu8tDY91eGolHgs9hStuntqMt5gJdrbZgMWU1zoz_mvVPMY_hDTUENgMVQP9J9K/exec")


# --- Selector for Notification Button ---
NOTIFICATION_BUTTON_SELECTOR = 'div.quick-action-link.position-relative.dropdown-toggle[data-bs-toggle="dropdown"]'


# --- Helper Functions ---

def extract_parcel_id(notification_text: str) -> str | None:
    """Extracts Parcel ID from notification text using regex."""
    match = re.search(r"Parcel\s*#(\d+)", notification_text)
    if match:
        return match.group(1)
    return None


def parse_time_ago(time_text: str) -> int | None:
    """Converts 'X minutes/hours ago' text to minutes."""
    time_text = time_text.lower().strip()
    if "a few seconds ago" in time_text or "seconds ago" in time_text:
        return 0
    if "a minute ago" == time_text:
        return 1

    match_minutes = re.search(r"(\d+)\s+minutes?\s+ago", time_text)
    if match_minutes:
        return int(match_minutes.group(1))

    if "an hour ago" == time_text:
        return 60

    match_hours = re.search(r"(\d+)\s+hours?\s+ago", time_text)
    if match_hours:
        return int(match_hours.group(1)) * 60

    print(f"Warning: Could not parse time string: '{time_text}'")
    return None


def send_data_to_google_sheet(data: dict) -> dict:
    """Sends parcel data to the Google Web App and returns its response."""
    if not GOOGLE_WEB_APP_URL or GOOGLE_WEB_APP_URL == "YOUR_GOOGLE_WEB_APP_URL_HERE":
        print("ERROR: Google Web App URL not configured. Data will not be sent to Google Sheet.")
        return {"status": "error", "message": "Google Web App URL not set."}

    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(GOOGLE_WEB_APP_URL, data=json.dumps(data), headers=headers, timeout=10)
        print(f"DEBUG: Raw response status code: {response.status_code}")
        print(f"DEBUG: Raw response text from Google Web App: '{response.text}'")
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        print("ERROR: Request to Google Web App timed out.")
        return {"status": "error", "message": "Request timed out."}
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Failed to send data to Google Web App: {e}")
        return {"status": "error", "message": f"Request failed: {e}"}
    except json.JSONDecodeError:
        print(f"ERROR: Could not decode JSON response from Google Web App. Response was: '{response.text}'")
        return {"status": "error", "message": "Invalid JSON response."}


def save_to_file(filepath: Path, data: str, parcel_id_to_mark_processed: str):
    """
    Appends the data to the specified local file with a serial number.
    This is now a secondary storage/backup, primary is Google Sheet.
    """
    # Local saving disabled � records are sent to Google Sheet only.
    return


def login(page, email, password):
    """Logs into the website."""
    print("Navigating to login page: https://packzy.com/login")
    page.goto("https://packzy.com/login", wait_until="networkidle", timeout=60000)
    print("Filling email...")
    page.locator('input[name="email"]').fill(email)
    print("Filling password...")
    page.locator('input[type="password"]').fill(password)
    print("Clicking login button...")
    page.locator('button[type="submit"]:has-text("Login")').click()

    try:
        print("Waiting for dashboard to load (checking for notification icon)...")
        page.wait_for_selector(NOTIFICATION_BUTTON_SELECTOR, timeout=30000)
        print("Login successful. Dashboard loaded.")
    except PlaywrightTimeoutError:
        print("Login failed or dashboard did not load as expected within timeout.")
        if page.locator(":text('Invalid credentials')").is_visible():
            print("Login error: Invalid credentials detected on page.")
        raise Exception("Login failed. Please check credentials or website status.")

def format_phone_number(phone_number: str) -> str:
    """
    Formats a phone number:
    1. Removes '+88' prefix if present.
    2. Ensures the number starts with '0'.
    """
    # Remove any non-digit characters first, except for leading '+'
    cleaned_number = re.sub(r'[^\d+]', '', phone_number)

    # 1. Remove '+88' prefix if present
    if cleaned_number.startswith('+88'):
        cleaned_number = cleaned_number[3:] # Remove the '+88'

    # 2. Ensure it starts with '0'
    if not cleaned_number.startswith('0'):
        # This handles cases like '1750138107' becoming '01750138107'
        # and also cases where the number might be just '8801...' after cleaning
        cleaned_number = '0' + cleaned_number

    return cleaned_number

# --- Main Script ---
def main_script():
    if not USER_EMAIL or not USER_PASSWORD:
        print("ERROR: Credentials not found. Set STEADFAST_USERNAME and STEADFAST_PASSWORD environment variables.")
        return

    # No local file storage. Keep processed IDs in-memory for this run only.
    processed_parcel_ids = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # For regular use
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36"
        )
        page = context.new_page()

        try:
            # --- Login ---
            login(page, USER_EMAIL, USER_PASSWORD)

            # --- Continuous Checking Loop ---
            while True:
                print("\n--- Starting new notification check cycle ---")
                try:
                    print("Reloading page to refresh notifications...")
                    page.reload(wait_until="networkidle", timeout=60000)

                    print("Clicking notification icon...")
                    notification_icon = page.locator(NOTIFICATION_BUTTON_SELECTOR)
                    notification_icon.wait_for(state="visible", timeout=20000)
                    notification_icon.click()

                    # Wait for the notification dropdown to be populated
                    page.wait_for_selector('div.single_notification', timeout=15000)
                    print("Notification dropdown opened.")

                except PlaywrightTimeoutError as e:
                    print(f"Error opening or finding notifications: {e}. Retrying after 1 minute.")
                    time.sleep(60)
                    continue  # Restart the loop
                except Exception as e:
                    print(f"An unexpected error occurred while accessing notifications: {e}. Retrying after 1 minute.")
                    time.sleep(60)
                    continue

                notifications_elements = page.query_selector_all('div.single_notification')
                print(f"Found {len(notifications_elements)} notifications in the current view.")

                new_notifications_to_process_details = []

                for el in notifications_elements:
                    try:
                        p_element = el.query_selector('div.notify_text p')
                        time_element = el.query_selector('div.notify_text span.txt-primary')

                        if not p_element or not time_element:
                            print("Skipping a notification: missing text or time element.")
                            continue

                        notification_text = p_element.inner_text()
                        time_text = time_element.inner_text()

                        parcel_id = extract_parcel_id(notification_text)
                        minutes_ago = parse_time_ago(time_text)

                        if parcel_id and minutes_ago is not None:
                            print(f"Checking Parcel ID: {parcel_id}, Time: '{time_text}' ({minutes_ago} mins ago)")
                            if parcel_id in processed_parcel_ids:
                                print(f"Parcel ID {parcel_id} already processed locally. Skipping.")
                                continue

                            if minutes_ago <= 30:
                                print(f"Parcel ID {parcel_id} is new and relevant. Adding to fetch queue.")
                                new_notifications_to_process_details.append({
                                    "id": parcel_id,
                                    "note": notification_text.strip()
                                })
                            else:
                                print(f"Parcel ID {parcel_id} is older than 30 minutes ({minutes_ago} mins). Skipping.")

                    except Exception as e:
                        print(f"Error processing a notification element: {e}")

                try:
                    page.locator('body').click(position={'x': 0, 'y': 0}, delay=100,
                                               force=True)
                    print("Clicked body to potentially close notification dropdown.")
                except Exception as e_click_body:
                    print(f"Minor issue trying to close notification dropdown: {e_click_body}")

                if not new_notifications_to_process_details:
                    print("No new, relevant notifications found in this check. Waiting for 1 minute.")
                    time.sleep(60)
                    continue

                print(f"\n--- Fetching details for {len(new_notifications_to_process_details)} new parcel(s) ---")
                for item_data in new_notifications_to_process_details:
                    parcel_id = item_data["id"]
                    original_note = item_data["note"]
                    print(f"\n--- Processing Parcel ID: {parcel_id} ---")

                    try:
                        print(f"Searching for Parcel ID: {parcel_id}...")
                        search_input_selector = 'input#searchInput[placeholder="Search Consignment"]'
                        page.wait_for_selector(search_input_selector, timeout=15000)
                        page.fill(search_input_selector, parcel_id)

                        print("Waiting for search result link...")
                        search_result_link_locator = page.locator(f'a[href="/user/consignment/{parcel_id}"][data-v-b253672d], '
                                                                  f'a[href="/user/consignment/{parcel_id}"]:has-text("ID: {parcel_id}")')


                        search_result_link_locator.wait_for(state="visible", timeout=15000)

                        print(f"Search result for {parcel_id} found. Clicking...")
                        search_result_link_locator.click()

                        print("Waiting for consignment details page to load...")
                        page.wait_for_load_state('networkidle', timeout=45000)
                        print(f"Navigated to details page for {parcel_id}.")

                        # Extract Customer's Phone Number
                        customer_phone_locator = page.locator('//p[small[contains(text(), "Phone Number")]]/span[1]')
                        customer_phone = customer_phone_locator.inner_text(timeout=10000).strip()
                        # --- Apply formatting to customer_phone ---
                        formatted_customer_phone = format_phone_number(customer_phone)


                        # Extract Rider's Name and Phone Number
                        rider_name_locator = page.locator('div.rider-name p.my-3 small.txt-black')
                        rider_full_text = rider_name_locator.inner_text(timeout=10000)
                        rider_name = re.split(r"\s*Rate Me|\s*\(", rider_full_text, 1)[0].strip()

                        rider_phone_locator = page.locator('div.rider-name p.cell span').first
                        rider_phone = rider_phone_locator.inner_text(timeout=10000).strip()
                        # --- Apply formatting to rider_phone ---
                        formatted_rider_phone = format_phone_number(rider_phone)


                        print(f"  Customer's Phone (Original): {customer_phone}")
                        print(f"  Customer's Phone (Formatted): {formatted_customer_phone}")
                        print(f"  Rider's Name: {rider_name}")
                        print(f"  Rider's Phone (Original): {rider_phone}")
                        print(f"  Rider's Phone (Formatted): {formatted_rider_phone}")
                        print(f"  Note: {original_note}")

                        # Prepare data for Google Sheet - Use formatted numbers
                        data_to_send = {
                            "parcel_id": parcel_id,
                            "customer_phone": formatted_customer_phone, # Use the formatted number here
                            "note": original_note,
                            "rider_name": rider_name,
                            "rider_phone": formatted_rider_phone      # Use the formatted number here
                        }

                        # Send data to Google Sheet
                        print(f"Sending Parcel ID {parcel_id} to Google Sheet...")
                        response_from_sheet = send_data_to_google_sheet(data_to_send)
                        print(f"Google Sheet response for {parcel_id}: {response_from_sheet}")

                        if response_from_sheet.get("status") == "success":
                            processed_parcel_ids.add(parcel_id)
                            output_data_local = (
                                f"Parcel ID#{parcel_id}\n"
                                f"Customer's Number: {formatted_customer_phone}\n" # Use formatted number for local file too
                                f"Note: {original_note}\n"
                                f"Rider's Name: {rider_name}\n"
                                f"Call: {formatted_rider_phone}"                     # Use formatted number for local file too
                            )
                            save_to_file(output_file_path, output_data_local, parcel_id)
                        elif response_from_sheet.get("status") == "duplicate":
                            print(f"Parcel ID {parcel_id} was already a duplicate in Google Sheet. Marking as processed locally.")
                            processed_parcel_ids.add(parcel_id)
                        else:
                            print(f"Failed to add Parcel ID {parcel_id} to Google Sheet: {response_from_sheet.get('message', 'Unknown error')}")


                    except PlaywrightTimeoutError as e:
                        print(f"Timeout error fetching details for Parcel ID {parcel_id}: {e}")
                        print("This parcel might be skipped or retried in a later cycle if it reappears.")
                    except Exception as e:
                        print(f"An error occurred while fetching details for Parcel ID {parcel_id}: {e}")

                    time.sleep(3)

                print("\n--- Finished processing batch. Starting new check cycle shortly. ---")
                time.sleep(5)

        except KeyboardInterrupt:
            print("\nScript interrupted by user. Exiting...")
        except Exception as e:
            print(f"\nAn critical error occurred in the main script: {e}")
        finally:
            print("Closing browser.")
            if 'browser' in locals() and browser:
                browser.close()


if __name__ == "__main__":
    if USER_EMAIL == "YOUR_EMAIL_HERE" or USER_PASSWORD == "YOUR_PASSWORD_HERE":
        print("ERROR: Please replace 'YOUR_EMAIL_HERE' and 'YOUR_PASSWORD_HERE' with your actual credentials.")
    elif GOOGLE_WEB_APP_URL == "YOUR_GOOGLE_WEB_APP_URL_HERE":
        print("ERROR: Please replace 'YOUR_GOOGLE_WEB_APP_URL_HERE' with your deployed Google Web App URL.")
    else:
        main_script()