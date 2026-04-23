import signal
import sys
import time
import re
import os
import argparse
import pandas as pd
from threading import Timer
from playwright.sync_api import sync_playwright
from datetime import datetime

# Configuration from environment variables
DATA_DIR = os.environ.get('DATA_DIR', '/app/data')
EXCEL_FILE_PATH = os.path.join(DATA_DIR, 'Return.xlsx')
USERNAME = os.environ.get('STEADFAST_USERNAME', '')
PASSWORD = os.environ.get('STEADFAST_PASSWORD', '')
TARGET_DATE = os.environ.get('TARGET_DATE', 'today')  # Format: YYYY-MM-DD or 'today'
FORCE_NEW_FILE = False
APPEND_TO_EXISTING = os.environ.get('APPEND_TO_EXISTING', '0') == '1'

df = None

def get_status_and_update(page, id_number, retries=2):
    """
    Fetches status and other details for a given ID number from the search page.
    Includes retry mechanism for robustness.
    """
    try:
        search_box = page.wait_for_selector("input[placeholder='Search Consignment']", timeout=15000)
        search_box.fill(id_number)
        search_box.press("Enter")

        page.wait_for_selector("#searchResults div li a p", timeout=20000)
        first_result = page.query_selector("#searchResults div li a p")
        first_result.click()

        page.wait_for_selector(".alert", timeout=15000)

        note_text, amount_status, rider_note_text = "", "", ""

        change_element = page.query_selector("p.txt-black:has-text('Amount has been changed')")
        if change_element:
            amounts = re.findall(r'\d+', change_element.inner_text())
            if len(amounts) == 2:
                amount_status = int(amounts[0]) - int(amounts[1])
                note_text = change_element.inner_text()
        else:
            cod_elements = page.query_selector_all("h6:has-text('COD: ৳')")
            if cod_elements:
                cod_text = cod_elements[0].inner_text()
                amount_match = re.search(r'৳ (\d+)', cod_text)
                if amount_match:
                    amount_status = int(amount_match.group(1))
                    note_text = "Full Amount Returned"

        rider_notes_elements = page.query_selector_all("p.txt-black:has-text('Rider Note:')")
        if rider_notes_elements:
            rider_notes = [el.inner_text().replace("Rider Note:", "").strip() for el in rider_notes_elements]
            rider_note_text = "Rider Note: " + " ".join(rider_notes)
        else:
            rider_note_text = "null"

        created_at_element = page.query_selector("p:has-text('Created at')")
        entry_date = ""
        if created_at_element:
            date_text = created_at_element.inner_text()
            match = re.search(r'Created at\s*:\s*(\w+ \d{1,2}, \d{4})', date_text)
            if match:
                raw_date = match.group(1)
                parsed_date = pd.to_datetime(raw_date)
                entry_date = parsed_date.strftime("%m-%d-%Y")

        invoice_elements = page.query_selector_all("p:has-text('Invoice :')")
        invoice_numbers = []
        for el in invoice_elements:
            span = el.query_selector("span")
            if span:
                invoice_numbers.append(span.inner_text().strip())
        invoice_combined = ", ".join(invoice_numbers)

        phone_number_element = page.query_selector("p:has-text('Phone Number :') span")
        phone_number = ""
        if phone_number_element:
            phone_number = phone_number_element.inner_text().strip()

        charge_element = page.query_selector("p:has-text('Delivery Charge') span.txt-black")
        delivery_charge = ""
        if charge_element:
            charge_text = charge_element.inner_text()
            match = re.search(r'(\d+)', charge_text)
            if match:
                delivery_charge = match.group(1)

        name_element = page.query_selector("p:has-text('Name :') span")
        customer_name = ""
        if name_element:
            customer_name = name_element.inner_text().strip()

        return note_text, amount_status, rider_note_text, entry_date, invoice_combined, phone_number, delivery_charge, customer_name

    except Exception as e:
        if retries > 0:
            time.sleep(3)
            page.go_back()
            page.wait_for_selector("input[placeholder='Search Consignment']", timeout=15000)
            return get_status_and_update(page, id_number, retries - 1)
        print(f"Error fetching status for ID {id_number}: {str(e)}")
        return "Error", "Error", "Error", "Error", "Error", "Error", "Error", "Error"

def get_return_ids_for_date(context, target_date):
    """
    Navigates to the return lists page, finds ALL return lists for the target date,
    opens each in a new tab to extract IDs, then closes tabs.
    Uses multi-tab approach to avoid DOM corruption issues.
    """
    return_ids = []
    # Normalize the target date to compare only year, month, day
    target_date_normalized = target_date.replace(hour=0, minute=0, second=0, microsecond=0)

    # Create initial page for scanning return lists
    main_page = context.new_page()
    
    print(f"Navigating to return lists page: https://steadfast.com.bd/user/returnlists")
    main_page.goto("https://steadfast.com.bd/user/returnlists")
    main_page.wait_for_load_state("networkidle")

    try:
        print("Waiting for return list rows to appear...")
        main_page.wait_for_selector(".tbody-row.d-flex", timeout=30000)
        print("Return list rows found.")
    except Exception as e:
        print(f"ERROR: Return list rows did not appear within timeout: {e}")
        print("Exiting get_return_ids_for_date as essential elements are missing.")
        main_page.close()
        return []

    print(f"On return lists page. Searching for ALL return lists for {target_date.strftime('%B %d, %Y')}...")

    # First pass: collect all "View" URLs for matching dates
    return_rows = main_page.query_selector_all(".tbody-row.d-flex")
    view_urls = []
    
    for i, row in enumerate(return_rows):
        try:
            date_cell = row.query_selector(".cell.cell_1")
            if date_cell:
                row_full_date_text = date_cell.inner_text().strip()

                try:
                    # Attempt to parse the date in the format "Month Day, Year Hour:Minute AM/PM"
                    # Try different formats to handle "03:14 pm" format
                    parsed_row_date = None
                    for date_format in ["%B %d, %Y %I:%M %p", "%B %d, %Y %I:%M %P"]:
                        try:
                            parsed_row_date = datetime.strptime(row_full_date_text, date_format)
                            break
                        except ValueError:
                            continue
                    
                    if parsed_row_date is None:
                        # Try lowercase am/pm
                        row_full_date_text_upper = row_full_date_text.replace(' pm', ' PM').replace(' am', ' AM')
                        parsed_row_date = datetime.strptime(row_full_date_text_upper, "%B %d, %Y %I:%M %p")
                    
                    parsed_row_date_normalized = parsed_row_date.replace(hour=0, minute=0, second=0, microsecond=0)

                    if parsed_row_date_normalized == target_date_normalized:
                        view_link = row.query_selector("a.view-details")
                        if view_link:
                            # Get the href URL instead of clicking
                            href = view_link.get_attribute("href")
                            if href:
                                # Construct full URL
                                if href.startswith('/'):
                                    full_url = f"https://steadfast.com.bd{href}"
                                else:
                                    full_url = href
                                view_urls.append({
                                    'url': full_url,
                                    'date_text': row_full_date_text
                                })
                                print(f"Found return lot #{len(view_urls)} for {target_date.strftime('%B %d, %Y')}: {row_full_date_text}")
                except ValueError as ve:
                    print(f"DEBUG: Row {i}: Could not parse date '{row_full_date_text}': {ve}")
                except Exception as e:
                    print(f"DEBUG: Row {i}: An unexpected error occurred during date processing: {e}")
        except Exception as e:
            print(f"ERROR: Processing row {i}: {e}")
            continue

    print(f"\nTotal matching return lots found: {len(view_urls)}")
    
    # Second pass: open each URL in a new tab and extract IDs
    for lot_num, lot_info in enumerate(view_urls, 1):
        try:
            print(f"\nOpening lot #{lot_num} in new tab: {lot_info['date_text']}")
            lot_page = context.new_page()
            lot_page.goto(lot_info['url'])
            lot_page.wait_for_load_state("networkidle")
            
            print(f"Extracting ID numbers from lot #{lot_num}...")
            lot_page.wait_for_selector(".tbody-row.d-flex .cell.cell_1 strong", timeout=15000)

            id_elements = lot_page.query_selector_all(".tbody-row.d-flex .cell.cell_1 strong")
            lot_ids = []
            for id_element in id_elements:
                id_number = id_element.inner_text().strip()
                return_ids.append(id_number)
                lot_ids.append(id_number)
                print(f"  Extracted ID: {id_number}")

            print(f"  Total IDs from lot #{lot_num}: {len(lot_ids)}")
            
            # Close the tab
            lot_page.close()
            print(f"Closed tab for lot #{lot_num}")
            
        except Exception as e:
            print(f"ERROR: Failed to process lot #{lot_num}: {e}")
            try:
                lot_page.close()
            except:
                pass
            continue

    # Close the main page
    main_page.close()

    if not return_ids:
        print(f"\nNo return lists found for {target_date.strftime('%B %d, %Y')}.")
    else:
        print(f"\n{'='*60}")
        print(f"Total matching return lots: {len(view_urls)}")
        print(f"Total IDs collected: {len(return_ids)}")
        print(f"{'='*60}\n")

    return return_ids

def update_statuses(page):
    """
    Reads ID numbers from the Excel file, fetches their statuses,
    and updates the Excel file with the fetched data.
    Column order: SL, Id, Entry Date, Invoice, Charge, Name, Phone, Amount Status, Note, Reason
    """
    global df
    try:
        df = pd.read_excel(EXCEL_FILE_PATH, sheet_name='Return', dtype={'Id': str})

        required_cols = ['Entry Date', 'Invoice', 'Charge', 'Name', 'Phone', 'Amount Status', 'Note', 'Reason', 'Buying Price', 'Selling Price', 'Quantity']
        for col in required_cols:
            if col not in df.columns:
                df[col] = ""
        df[required_cols] = df[required_cols].astype(str).fillna("")

        for idx, row in df.iterrows():
            id_number = row['Id']
            if pd.isna(id_number) or id_number == "":
                continue

            print(f"Processing ID: {id_number}")
            note, amount_status, rider_note, entry_date, invoice, phone, charge, name = get_status_and_update(page, id_number)

            df.at[idx, 'Entry Date'] = entry_date
            df.at[idx, 'Invoice'] = invoice
            df.at[idx, 'Charge'] = charge
            df.at[idx, 'Name'] = name
            df.at[idx, 'Phone'] = phone
            df.at[idx, 'Amount Status'] = amount_status
            df.at[idx, 'Note'] = note
            df.at[idx, 'Reason'] = rider_note

            # Reorder columns to match required format (add new price/qty columns at end as K/L/M)
            column_order = ['SL', 'Id', 'Entry Date', 'Invoice', 'Charge', 'Name', 'Phone', 'Amount Status', 'Note', 'Reason', 'Buying Price', 'Selling Price', 'Quantity']
            df = df[column_order]

            # Save after each ID to ensure progress is not lost on crash
            df.to_excel(EXCEL_FILE_PATH, sheet_name='Return', index=False)
            print(f"ID {id_number} processed and updated in Excel.")

        print("All statuses updated successfully!")
    except Exception as e:
        print(f"Error updating statuses: {str(e)}")

def final_save_data():
    """
    Final save of the DataFrame to the Excel file.
    """
    global df
    try:
        if df is not None:
            df.to_excel(EXCEL_FILE_PATH, sheet_name='Return', index=False)
            print("Final save completed.")
    except Exception as e:
        print(f"Final save error: {str(e)}")

def signal_handler(sig, frame):
    """
    Handles termination signals to ensure data is saved before exiting.
    """
    global df
    print("Saving data before exit...")
    if df is not None:
        df.to_excel(EXCEL_FILE_PATH, sheet_name='Return', index=False)
        print("Data saved.")
    sys.exit(0)

def parse_date_input(date_input):
    """
    Parses the date input and returns a datetime object.
    Accepts 'today' or a date in YYYY-MM-DD format.
    """
    date_input = date_input.strip().lower()
    if date_input == 'today':
        return datetime.now()
    else:
        try:
            return datetime.strptime(date_input, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Invalid date format: {date_input}. Use YYYY-MM-DD or 'today'.")

def main():
    """
    Main function to orchestrate the entire workflow.
    """
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Validate credentials
    if not USERNAME or not PASSWORD:
        print("ERROR: STEADFAST_USERNAME and STEADFAST_PASSWORD environment variables must be set.")
        sys.exit(1)

    # Ensure data directory exists
    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"Data directory: {DATA_DIR}")
    print(f"Excel file path: {EXCEL_FILE_PATH}")

    # If instructed to create a new file for this run, remove existing file first
    try:
        # For range runs, do not remove existing file if we are appending
        if FORCE_NEW_FILE and (not APPEND_TO_EXISTING) and os.path.exists(EXCEL_FILE_PATH):
            print(f"Removing existing file to force new output: {EXCEL_FILE_PATH}")
            os.remove(EXCEL_FILE_PATH)
    except Exception as e:
        print(f"Warning: failed to remove existing Excel file: {e}")

    # Parse the target date from environment variable
    try:
        selected_date = parse_date_input(TARGET_DATE)
        print(f"Target date set to: {selected_date.strftime('%Y-%m-%d')}")
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        
        # Create a page for login
        login_page = context.new_page()
        
        print("Navigating to SteadFast dashboard for login...")
        login_page.goto("https://steadfast.com.bd/dashboard")
        login_page.fill("input[name='email']", USERNAME)
        login_page.fill("input#pass", PASSWORD)
        login_page.click("button:has-text('Login')")
        login_page.wait_for_load_state("networkidle")
        print("Logged in successfully.")
        
        # Close login page (session is maintained in context)
        login_page.close()

        # Get return IDs using multi-tab approach (pass context instead of page)
        return_ids_for_selected_date = get_return_ids_for_date(context, selected_date)

        if return_ids_for_selected_date:
            global df
            try:
                existing_df = pd.read_excel(EXCEL_FILE_PATH, sheet_name='Return', dtype={'Id': str})

                new_ids_to_add = [id_num for id_num in return_ids_for_selected_date if id_num not in existing_df['Id'].values]

                if new_ids_to_add:
                    # Create DataFrame with proper column structure
                    new_ids_df = pd.DataFrame({'Id': new_ids_to_add})
                    # Add SL numbers starting from the last SL in existing_df
                    start_sl = len(existing_df) + 1
                    new_ids_df['SL'] = range(start_sl, start_sl + len(new_ids_to_add))
                    
                    # Add empty columns for other fields
                    new_ids_df['Entry Date'] = ""
                    new_ids_df['Invoice'] = ""
                    new_ids_df['Charge'] = ""
                    new_ids_df['Name'] = ""
                    new_ids_df['Phone'] = ""
                    new_ids_df['Amount Status'] = ""
                    new_ids_df['Note'] = ""
                    new_ids_df['Reason'] = ""
                    # Initialize new price/qty columns empty
                    new_ids_df['Buying Price'] = ""
                    new_ids_df['Selling Price'] = ""
                    new_ids_df['Quantity'] = ""
                    
                    # Reorder columns (ensure K/L/M are at the end)
                    new_ids_df = new_ids_df[['SL', 'Id', 'Entry Date', 'Invoice', 'Charge', 'Name', 'Phone', 'Amount Status', 'Note', 'Reason', 'Buying Price', 'Selling Price', 'Quantity']]
                    
                    df = pd.concat([existing_df, new_ids_df], ignore_index=True)
                    df.to_excel(EXCEL_FILE_PATH, sheet_name='Return', index=False)
                    print(f"Added {len(new_ids_to_add)} new ID(s) to Excel for {selected_date.strftime('%Y-%m-%d')}: {new_ids_to_add}")
                else:
                    df = existing_df
                    print(f"No new IDs to add to Excel for {selected_date.strftime('%Y-%m-%d')}.")

            except FileNotFoundError:
                # Create new DataFrame with proper structure
                df = pd.DataFrame({
                    'SL': range(1, len(return_ids_for_selected_date) + 1),
                    'Id': return_ids_for_selected_date,
                    'Entry Date': "",
                    'Invoice': "",
                    'Charge': "",
                    'Name': "",
                    'Phone': "",
                    'Amount Status': "",
                    'Note': "",
                    'Reason': "",
                    'Buying Price': "",
                    'Selling Price': "",
                    'Quantity': ""
                })
                # Ensure column order
                df = df[['SL', 'Id', 'Entry Date', 'Invoice', 'Charge', 'Name', 'Phone', 'Amount Status', 'Note', 'Reason', 'Buying Price', 'Selling Price', 'Quantity']]
                df.to_excel(EXCEL_FILE_PATH, sheet_name='Return', index=False)
                print(f"Created new Excel file with {len(return_ids_for_selected_date)} ID(s) for {selected_date.strftime('%Y-%m-%d')}: {return_ids_for_selected_date}")

            # Create new page for fetching details
            print("Creating new page for fetching data...")
            details_page = context.new_page()
            details_page.goto("https://steadfast.com.bd/dashboard")
            details_page.wait_for_selector("input[placeholder='Search Consignment']", timeout=20000)

            update_statuses(details_page)
            
            # Final save after all updates
            final_save_data()
            
            details_page.close()
        else:
            print(f"No return IDs found for {selected_date.strftime('%Y-%m-%d')}. Skipping data fetching.")

        browser.close()
        print("Browser closed. Script finished.")
        print("\n" + "="*60)
        print("SCRAPING COMPLETED SUCCESSFULLY")
        print("="*60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run SteadFast return scraper")
    parser.add_argument("--date", "-d", help="Target date (YYYY-MM-DD) or 'today'", default=None)
    parser.add_argument("--output", "-o", help="Output Excel file path", default=None)
    args = parser.parse_args()

    # Apply CLI args to globals
    if args.date:
        TARGET_DATE = args.date
    if args.output:
        # Ensure directory exists and update paths
        output_path = os.path.abspath(args.output)
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        # instruct script to write to a new file instead of the default Return.xlsx
        FORCE_NEW_FILE = True
        EXCEL_FILE_PATH = output_path

    main()
    # Ensure clean exit
    sys.exit(0)
