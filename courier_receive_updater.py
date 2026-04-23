import asyncio
import json
import logging
import os
import re
import signal
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

import tempfile

import aiohttp
import pandas as pd
from playwright.async_api import async_playwright


WEBAPP_URL = os.environ.get(
    "WEBAPP_URL",
    "https://script.google.com/macros/s/AKfycbyTj9gJR2BnNJhDgkSMkhHK6Si1H8eZeJsKSA0voG1v9I9NeKFJxlFh650sZHjgzAhNtg/exec",
)
STEADFAST_USERNAME = os.environ.get("STEADFAST_USERNAME", "sanveesbytony08@gmail.com")
STEADFAST_PASSWORD = os.environ.get("STEADFAST_PASSWORD", "Sanvees321@")

DELIVERY_STATUSES_TO_PROCESS = {"Delivered", "Partial Delivered", "Price Changed", "Cancelled"}

SHEET_API = "API"
SHEET_CSV = "CSV"

API_ID_HEADER = "Order Number"
CSV_ID_HEADER = "ID Numbers"
DELIVERY_STATUS_HEADER = "Delivery Status"
COURIER_CHARGE_HEADER = "Courier Charge"
PAYMENT_STATUS_HEADER = "Payment Status"

MAX_CONCURRENT_TABS = int(os.environ.get("MAX_CONCURRENT_TABS", "6"))
PAYMENTS_SCAN_PAGES_LIMIT = int(os.environ.get("PAYMENTS_SCAN_PAGES_LIMIT", "0"))  # 0 = no limit
RETURNLISTS_SCAN_PAGES_LIMIT = int(os.environ.get("RETURNLISTS_SCAN_PAGES_LIMIT", "0"))  # 0 = no limit
BATCH_UPDATE_SIZE = int(os.environ.get("BATCH_UPDATE_SIZE", "80"))
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
DEBUG_SAMPLE = int(os.environ.get("DEBUG_SAMPLE", "0"))

RETURN_TARGET_DATE = os.environ.get("RETURN_TARGET_DATE", "today")  # 'today' or YYYY-MM-DD


@dataclass
class SheetRowTask:
    sheet_name: str
    identifier_header: str
    identifier_value: str
    delivery_status: str


DELIVERY_STATUSES_TO_PROCESS_REFINED = {"Delivered", "Partial Delivered", "Price Changed", "Cancelled"}
PAYMENT_STATUS_TO_PROCESS_REFINED = {"", "Pending"}


def _normalize_identifier(val: str) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _parse_money_to_int(val: str) -> Optional[int]:
    if val is None:
        return None

    # If it's already numeric, convert safely.
    if isinstance(val, (int,)):
        return int(val)
    if isinstance(val, float):
        # pandas uses NaN for empty cells
        if val != val:  # NaN check
            return None
        if val == float("inf") or val == float("-inf"):
            return None
        # Excel sometimes gives floats like 593.0; int(...) keeps correct value.
        return int(round(val))

    s = str(val).strip()
    if not s:
        return None

    # Keep digits, optional minus, and at most one decimal point.
    # This avoids the old behavior where "593.0" became "5930".
    cleaned = re.sub(r"[^0-9.\-]", "", s)
    if cleaned in {"", ".", "-", "-."}:
        return None

    # If multiple dots exist (e.g., thousand separators in some locales), keep the first.
    if cleaned.count(".") > 1:
        first, *rest = cleaned.split(".")
        cleaned = first + "." + "".join(rest)

    try:
        num = float(cleaned)
    except Exception:
        return None

    return int(round(num))


async def fetch_sheet(session: aiohttp.ClientSession, sheet_name: str) -> pd.DataFrame:
    params = {"sheetName": sheet_name}

    last_err: Optional[BaseException] = None
    for attempt in range(1, 6):
        try:
            async with session.get(WEBAPP_URL, params=params, timeout=aiohttp.ClientTimeout(total=180)) as resp:
                # Reading as bytes first is more robust when the connection drops mid-transfer.
                body = await resp.read()
                text = body.decode("utf-8", errors="replace")
                payload = json.loads(text)
                if payload.get("status") != "success":
                    raise RuntimeError(f"Failed to fetch sheet '{sheet_name}': {payload}")
                rows = payload.get("data", [])
                if not rows:
                    return pd.DataFrame()
                return pd.DataFrame(rows)
        except (aiohttp.ClientPayloadError, aiohttp.ClientConnectionError, asyncio.TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            sleep_s = min(30, 2**attempt)
            logging.warning(
                "Fetch sheet '%s' failed (attempt %s/5): %s. Retrying in %ss",
                sheet_name,
                attempt,
                repr(e),
                sleep_s,
            )
            await asyncio.sleep(sleep_s)

    raise RuntimeError(f"Failed to fetch sheet '{sheet_name}' after retries: {last_err}")


async def send_batch_updates(session: aiohttp.ClientSession, batch_updates: List[dict]) -> Optional[dict]:
    if not batch_updates:
        return None
    if DRY_RUN:
        logging.info("DRY_RUN=1; skipping POST updates. Would send %s updates.", len(batch_updates))
        return {"status": "dry_run", "count": len(batch_updates)}

    headers = {"Content-Type": "application/json"}
    async with session.post(WEBAPP_URL, data=json.dumps(batch_updates), headers=headers, timeout=180) as resp:
        text = await resp.text()
        try:
            return json.loads(text)
        except Exception:
            logging.error("Non-JSON response from web app: %s", text)
            return None


async def steadfast_login(context) -> None:
    if not STEADFAST_USERNAME or not STEADFAST_PASSWORD:
        raise RuntimeError("Missing STEADFAST_USERNAME/STEADFAST_PASSWORD env vars")

    page = await context.new_page()
    await page.goto("https://packzy.com/login", timeout=60000)
    await page.fill("input[name='email']", STEADFAST_USERNAME)
    await page.fill("input#pass", STEADFAST_PASSWORD)
    await page.click("button:has-text('Login')")
    await page.wait_for_load_state("networkidle")
    await page.close()


async def scrape_returnlists_build_sets(context) -> Tuple[Set[str], Set[str], pd.DataFrame, Dict[str, str], Dict[str, str]]:
    invoices: Set[str] = set()
    order_ids: Set[str] = set()
    return_dfs: List[pd.DataFrame] = []
    invoice_to_returnlist_id: Dict[str, str] = {}
    order_id_to_returnlist_id: Dict[str, str] = {}

    page = await context.new_page()

    async def download_and_parse(download_page) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        for attempt in range(1, 4):
            try:
                # extract returnlist id from page before downloading
                try:
                    rid_el = await download_page.query_selector("xpath=//*[@id='app']/div[2]/div[2]/div[2]/div/div/div[1]/h6")
                    rid_txt = (await rid_el.text_content()) if rid_el else ""
                    m = re.search(r"(\d+)", rid_txt or "")
                    returnlist_id = m.group(1) if m else None
                except Exception:
                    returnlist_id = None

                async with download_page.expect_download(timeout=60000) as dl_info:
                    await download_page.click("xpath=//*[@id='app']/div[2]/div[2]/div[2]/div/div/div[2]/div[1]/a")
                download = await dl_info.value
                temp_path = await download.path()
                if not temp_path:
                    tmp_dir = tempfile.mkdtemp(prefix="steadfast_ret_dl_")
                    temp_path = os.path.join(tmp_dir, download.suggested_filename)
                    await download.save_as(temp_path)
                return pd.read_excel(temp_path, sheet_name="Worksheet"), returnlist_id
            except Exception as e:
                logging.warning("Returnlist XLSX download/parse failed (attempt %s/3): %s", attempt, repr(e))
                await asyncio.sleep(min(10, 2**attempt))
        return (None, None)

    try:
        page_num = 1
        while True:
            if RETURNLISTS_SCAN_PAGES_LIMIT and page_num > RETURNLISTS_SCAN_PAGES_LIMIT:
                break

            await page.goto(f"https://packzy.com/user/returnlists?page={page_num}", timeout=60000)
            await page.wait_for_load_state("networkidle")

            found_any = False
            for row_idx in range(1, 11):
                view_xpath = f"//*[@id='app']/div[2]/div[2]/div[2]/div/div/div[2]/div/div[2]/div[{row_idx}]/div[7]"
                view_el = await page.query_selector(f"xpath={view_xpath}")
                if not view_el:
                    break
                found_any = True

                await view_el.click()
                await page.wait_for_load_state("networkidle")

                df, returnlist_id = await download_and_parse(page)
                if df is not None and not df.empty:
                    # attach returnlist id as a column for traceability
                    if returnlist_id:
                        try:
                            df['Return List ID'] = str(returnlist_id)
                        except Exception:
                            pass
                    # Keep the raw DF for later merging/saving
                    return_dfs.append(df)
                    # Returnlist XLSX mapping:
                    # - Invoice column: E (index 4)
                    # - Order ID column: C (index 2)
                    for _, r in df.iterrows():
                        inv = _normalize_identifier(r.iloc[4] if len(r) > 4 else "")
                        oid = _normalize_identifier(r.iloc[2] if len(r) > 2 else "")
                        if inv:
                            invoices.add(inv)
                            if returnlist_id and inv not in invoice_to_returnlist_id:
                                invoice_to_returnlist_id[inv] = str(returnlist_id)
                        if oid:
                            order_ids.add(oid)
                            if returnlist_id and oid not in order_id_to_returnlist_id:
                                order_id_to_returnlist_id[oid] = str(returnlist_id)

                await page.go_back()
                await page.wait_for_load_state("networkidle")

            if not found_any:
                break
            page_num += 1

    finally:
        await page.close()

    merged_returns = pd.concat(return_dfs, ignore_index=True) if return_dfs else pd.DataFrame()
    # ensure 'Return List ID' is in Excel column P (index 15, 0-based)
    try:
        if 'Return List ID' in merged_returns.columns:
            cols = merged_returns.columns.tolist()
            cols.remove('Return List ID')
            insert_at = min(15, len(cols))
            cols.insert(insert_at, 'Return List ID')
            merged_returns = merged_returns[cols]
    except Exception:
        pass

    return invoices, order_ids, merged_returns, invoice_to_returnlist_id, order_id_to_returnlist_id


async def scrape_payments_build_lookups(context) -> Tuple[Dict[str, int], Dict[str, int], pd.DataFrame, Dict[str, str], Dict[str, str]]:
    invoice_to_bills: Dict[str, int] = {}
    order_id_to_bills: Dict[str, int] = {}
    payments_dfs: List[pd.DataFrame] = []
    invoice_to_payment_date: Dict[str, str] = {}
    order_id_to_payment_date: Dict[str, str] = {}

    page = await context.new_page()

    async def download_and_parse(download_page) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        for attempt in range(1, 4):
            try:
                # extract payment date text from the detail page before download
                try:
                    date_el = await download_page.query_selector("xpath=//*[@id='app']/div[2]/div[2]/div[2]/div/div[2]/div[1]/div[2]/div/p[2]")
                    date_txt = (await date_el.text_content()) if date_el else ""
                    m = re.search(r"(\d{2}-\d{2}-\d{2})", date_txt or "")
                    payment_date = m.group(1) if m else None
                except Exception:
                    payment_date = None

                async with download_page.expect_download(timeout=60000) as dl_info:
                    await download_page.click("xpath=//*[@id='app']/div[2]/div[2]/div[2]/div/div[1]/a")
                download = await dl_info.value
                temp_path = await download.path()
                if not temp_path:
                    tmp_dir = tempfile.mkdtemp(prefix="steadfast_dl_")
                    temp_path = os.path.join(tmp_dir, download.suggested_filename)
                    await download.save_as(temp_path)
                return pd.read_excel(temp_path, sheet_name="Worksheet"), payment_date
            except Exception as e:
                logging.warning("Payments XLSX download/parse failed (attempt %s/3): %s", attempt, repr(e))
                await asyncio.sleep(min(10, 2**attempt))
        return (None, None)

    try:
        page_num = 1
        while True:
            if PAYMENTS_SCAN_PAGES_LIMIT and page_num > PAYMENTS_SCAN_PAGES_LIMIT:
                break

            await page.goto(f"https://packzy.com/user/payments?page={page_num}", timeout=60000)
            await page.wait_for_load_state("networkidle")

            found_any = False
            for row_idx in range(1, 11):
                view_xpath = f"//*[@id='app']/div[2]/div[2]/div[2]/div/div[1]/div[2]/div/div[2]/div[{row_idx}]/div[9]"
                view_el = await page.query_selector(f"xpath={view_xpath}")
                if not view_el:
                    break
                found_any = True

                await view_el.click()
                await page.wait_for_load_state("networkidle")

                df, payment_date = await download_and_parse(page)
                if df is not None and not df.empty:
                    # attach payment date column for traceability
                    if payment_date:
                        try:
                            df['Payment Date'] = payment_date
                        except Exception:
                            pass
                    # Keep the raw DF for later merging/saving
                    payments_dfs.append(df)
                    # Payments detail XLSX mapping:
                    # - Invoice column: E (index 4), starting from row 2
                    # - Order ID column: C (index 2), starting from row 2
                    # - Bills column: N (index 13), header: 'Shipping Charge'
                    shipping_charge_col = None
                    try:
                        cols_lower = {str(c).strip().lower(): i for i, c in enumerate(df.columns.tolist())}
                        shipping_charge_col = cols_lower.get("shipping charge")
                    except Exception:
                        shipping_charge_col = None
                    for _, r in df.iterrows():
                        invoice = _normalize_identifier(r.iloc[4] if len(r) > 4 else "")
                        order_id = _normalize_identifier(r.iloc[2] if len(r) > 2 else "")
                        bills_val = None
                        if shipping_charge_col is not None and len(r) > shipping_charge_col:
                            raw_charge = r.iloc[shipping_charge_col]
                            bills_val = _parse_money_to_int(raw_charge)
                        if bills_val is None and len(r) > 13:
                            bills_val = _parse_money_to_int(r.iloc[13])
                        if bills_val is None:
                            continue

                        if invoice and invoice not in invoice_to_bills:
                            invoice_to_bills[invoice] = bills_val
                        if invoice and payment_date and invoice not in invoice_to_payment_date:
                            invoice_to_payment_date[invoice] = payment_date
                        if order_id and order_id not in order_id_to_bills:
                            order_id_to_bills[order_id] = bills_val
                        if order_id and payment_date and order_id not in order_id_to_payment_date:
                            order_id_to_payment_date[order_id] = payment_date

                await page.go_back()
                await page.wait_for_load_state("networkidle")

            if not found_any:
                break

            page_num += 1

    finally:
        await page.close()

    merged_payments = pd.concat(payments_dfs, ignore_index=True) if payments_dfs else pd.DataFrame()
    # ensure 'Payment Date' is in Excel column P (index 15, 0-based)
    try:
        if 'Payment Date' in merged_payments.columns:
            cols = merged_payments.columns.tolist()
            cols.remove('Payment Date')
            insert_at = min(15, len(cols))
            cols.insert(insert_at, 'Payment Date')
            merged_payments = merged_payments[cols]
    except Exception:
        pass

    return (
        invoice_to_bills,
        order_id_to_bills,
        merged_payments,
        invoice_to_payment_date,
        order_id_to_payment_date,
    )


def build_tasks_from_sheet(df: pd.DataFrame, sheet_name: str, id_header: str) -> List[SheetRowTask]:
    if df is None or df.empty:
        return []

    for col in (id_header, DELIVERY_STATUS_HEADER, PAYMENT_STATUS_HEADER):
        if col not in df.columns:
            raise RuntimeError(f"Sheet '{sheet_name}' missing required column '{col}'")

    tasks: List[SheetRowTask] = []

    for _, row in df.iterrows():
        identifier = _normalize_identifier(row.get(id_header, ""))
        if not identifier:
            continue

        status = _normalize_identifier(row.get(DELIVERY_STATUS_HEADER, ""))
        payment_status = _normalize_identifier(row.get(PAYMENT_STATUS_HEADER, ""))

        if payment_status not in PAYMENT_STATUS_TO_PROCESS_REFINED:
            continue
        if status not in DELIVERY_STATUSES_TO_PROCESS_REFINED:
            continue

        tasks.append(
            SheetRowTask(
                sheet_name=sheet_name,
                identifier_header=id_header,
                identifier_value=identifier,
                delivery_status=status,
            )
        )

    return tasks


async def process_tasks_and_prepare_updates(
    tasks: List[SheetRowTask],
    invoice_to_bills: Dict[str, int],
    order_id_to_bills: Dict[str, int],
    return_invoices: Set[str],
    return_order_ids: Set[str],
    invoice_to_payment_date: Dict[str, str],
    order_id_to_payment_date: Dict[str, str],
    invoice_to_returnlist_id: Dict[str, str],
    order_id_to_returnlist_id: Dict[str, str],
) -> List[dict]:
    updates: List[dict] = []

    for t in tasks:
        courier_charge_val: Optional[int] = None
        received = False
        payment_date_val: Optional[str] = None
        returnlist_id_val: Optional[str] = None

        if t.sheet_name == SHEET_API:
            courier_charge_val = invoice_to_bills.get(t.identifier_value)
            payment_date_val = invoice_to_payment_date.get(t.identifier_value)
            returnlist_id_val = invoice_to_returnlist_id.get(t.identifier_value)

            if t.delivery_status in {"Delivered", "Price Changed"}:
                received = courier_charge_val is not None
            else:
                # Partial Delivered + Cancelled: require payments match then return-list match by invoice
                received = courier_charge_val is not None and (t.identifier_value in return_invoices)
        else:
            courier_charge_val = order_id_to_bills.get(t.identifier_value)
            payment_date_val = order_id_to_payment_date.get(t.identifier_value)
            returnlist_id_val = order_id_to_returnlist_id.get(t.identifier_value)

            if t.delivery_status in {"Delivered", "Price Changed"}:
                received = courier_charge_val is not None
            else:
                # Partial Delivered + Cancelled: require payments match then return-list match by order id
                received = courier_charge_val is not None and (t.identifier_value in return_order_ids)

        payment_status = "Received" if received else "Pending"

        update_fields: Dict[str, str] = {PAYMENT_STATUS_HEADER: payment_status}
        if received and courier_charge_val is not None:
            update_fields[COURIER_CHARGE_HEADER] = str(courier_charge_val)
        else:
            # Leave courier charge empty when pending
            update_fields[COURIER_CHARGE_HEADER] = ""

        # Payment Date: set when payment is received and we have a source date
        pd_val = payment_date_val if (payment_date_val and payment_status == 'Received') else ""
        update_fields['Payment Date'] = pd_val

        # Return List ID: include when available
        update_fields['Return List ID'] = str(returnlist_id_val) if returnlist_id_val else ""

        updates.append(
            {
                "sheetName": t.sheet_name,
                "identifier": t.identifier_value,
                "idColumnIndex": 1,
                "updates": update_fields,
            }
        )

    return updates


def compute_id_column_index_from_df(df: pd.DataFrame, sheet_name: str, id_header: str) -> int:
    headers = df.columns.tolist() if df is not None and not df.empty else []
    if id_header not in headers:
        raise RuntimeError(f"Header '{id_header}' not found in sheet '{sheet_name}'.")
    return headers.index(id_header) + 1


def _save_df_to_desktop(df: pd.DataFrame, prefix: str) -> Optional[str]:
    """Save merged DataFrame to both Desktop and DATA_DIR (if available).

    Returns the path inside DATA_DIR if saved there, otherwise the desktop path.
    """
    try:
        if df is None or df.empty:
            logging.info("No %s data to save.", prefix)
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_merged_{timestamp}.xlsx"

        paths_tried = []

        # 1) Save to DATA_DIR if provided via environment or default ./data
        data_dir_env = os.environ.get('DATA_DIR')
        if data_dir_env:
            try:
                os.makedirs(data_dir_env, exist_ok=True)
                data_path = os.path.join(data_dir_env, filename)
                df.to_excel(data_path, index=False, sheet_name=prefix.capitalize())
                logging.info("Saved merged %s file to data dir: %s", prefix, data_path)
                return data_path
            except Exception:
                logging.exception("Failed saving merged %s to DATA_DIR %s", prefix, data_dir_env)
                paths_tried.append(('data_dir', data_dir_env))

        # 2) Fallback: save into ./data relative to script
        try:
            local_data = os.path.join(os.path.dirname(__file__), 'data')
            os.makedirs(local_data, exist_ok=True)
            local_path = os.path.join(local_data, filename)
            df.to_excel(local_path, index=False, sheet_name=prefix.capitalize())
            logging.info("Saved merged %s file to local data dir: %s", prefix, local_path)
            return local_path
        except Exception:
            logging.exception("Failed saving merged %s to local ./data", prefix)
            paths_tried.append(('local_data', local_data))

        # 3) Finally, save to Desktop as a convenience for the user
        try:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            os.makedirs(desktop, exist_ok=True)
            desk_path = os.path.join(desktop, filename)
            df.to_excel(desk_path, index=False, sheet_name=prefix.capitalize())
            logging.info("Saved merged %s file to Desktop: %s", prefix, desk_path)
            return desk_path
        except Exception:
            logging.exception("Failed saving merged %s to Desktop", prefix)
            return None
    except Exception as e:
        logging.exception("Unexpected error while saving merged %s file: %s", prefix, repr(e))
        return None


def _graceful_exit_handler(sig, frame):
    logging.info("Signal received, exiting gracefully.")
    sys.exit(0)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    signal.signal(signal.SIGINT, _graceful_exit_handler)
    signal.signal(signal.SIGTERM, _graceful_exit_handler)

    async with aiohttp.ClientSession() as session:
        api_df = await fetch_sheet(session, SHEET_API)
        csv_df = await fetch_sheet(session, SHEET_CSV)

    # Compute idColumnIndex from the initial fetch to avoid refetching huge sheets again.
    api_id_col_index = compute_id_column_index_from_df(api_df, SHEET_API, API_ID_HEADER)
    csv_id_col_index = compute_id_column_index_from_df(csv_df, SHEET_CSV, CSV_ID_HEADER)

    tasks_api = build_tasks_from_sheet(api_df, SHEET_API, API_ID_HEADER)
    tasks_csv = build_tasks_from_sheet(csv_df, SHEET_CSV, CSV_ID_HEADER)
    tasks = tasks_api + tasks_csv

    logging.info("Tasks to process: API=%s, CSV=%s, total=%s", len(tasks_api), len(tasks_csv), len(tasks))
    if not tasks:
        logging.info("No eligible rows found. Exiting.")
        return

    needs_returnlists = any(t.delivery_status in {"Partial Delivered", "Cancelled"} for t in tasks)
    # initialize merged DF holders so they're always available
    payments_merged_df = pd.DataFrame()
    returns_merged_df = pd.DataFrame()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        try:
            logging.info("Logging into Steadfast...")
            await steadfast_login(context)
            logging.info("Logged in.")

            logging.info("Scraping payments and building lookup maps (Invoice->Bills, Order ID->Bills)...")
            (
                invoice_to_bills,
                order_id_to_bills,
                payments_merged_df,
                invoice_to_payment_date,
                order_id_to_payment_date,
            ) = await scrape_payments_build_lookups(context)
            logging.info(
                "Lookups ready. invoices=%s order_ids=%s payments_dates=%s return_dates_map_size=%s",
                len(invoice_to_bills),
                len(order_id_to_bills),
                len(invoice_to_payment_date),
                len(order_id_to_payment_date),
            )

            if needs_returnlists:
                logging.info("Partial Delivered/Cancelled rows detected; scraping return lists for verification...")

                logging.info("Downloading & parsing returnlists XLSX files...")
                (
                    return_invoices,
                    return_order_ids,
                    returns_merged_df,
                    invoice_to_returnlist_id,
                    order_id_to_returnlist_id,
                ) = await scrape_returnlists_build_sets(context)
                logging.info(
                    "Returnlist sets collected. invoices=%s order_ids=%s returnlist_map=%s",
                    len(return_invoices),
                    len(return_order_ids),
                    len(invoice_to_returnlist_id),
                )
            else:
                logging.info("No Partial Delivered/Cancelled rows detected; skipping return list scraping.")
                return_invoices = set()
                return_order_ids = set()
                returns_merged_df = pd.DataFrame()
                invoice_to_returnlist_id = {}
                order_id_to_returnlist_id = {}

        finally:
            await browser.close()

    # Save merged payment/return Excel files to Desktop (if any)
    try:
        _save_df_to_desktop(payments_merged_df, "payments")
    except Exception:
        logging.exception("Error saving merged payments file")
    try:
        _save_df_to_desktop(returns_merged_df, "returns")
    except Exception:
        logging.exception("Error saving merged returns file")

    prepared_updates = await process_tasks_and_prepare_updates(
        tasks,
        invoice_to_bills,
        order_id_to_bills,
        return_invoices,
        return_order_ids,
        invoice_to_payment_date if 'invoice_to_payment_date' in locals() else {},
        order_id_to_payment_date if 'order_id_to_payment_date' in locals() else {},
        invoice_to_returnlist_id if 'invoice_to_returnlist_id' in locals() else {},
        order_id_to_returnlist_id if 'order_id_to_returnlist_id' in locals() else {},
    )

    if DEBUG_SAMPLE > 0:
        sample_pd_can = [
            t
            for t in tasks
            if t.delivery_status in {"Partial Delivered", "Cancelled"}
        ][:DEBUG_SAMPLE]

        api_pay_match = 0
        api_ret_match = 0
        csv_pay_match = 0
        csv_ret_match = 0

        for t in sample_pd_can:
            if t.sheet_name == SHEET_API:
                pay_ok = t.identifier_value in invoice_to_bills
                ret_ok = t.identifier_value in return_invoices
                api_pay_match += int(pay_ok)
                api_ret_match += int(ret_ok)
            else:
                pay_ok = t.identifier_value in order_id_to_bills
                ret_ok = t.identifier_value in return_order_ids
                csv_pay_match += int(pay_ok)
                csv_ret_match += int(ret_ok)

            logging.info(
                "DEBUG_SAMPLE %s: sheet=%s status=%s id=%s payments_match=%s return_match=%s",
                DEBUG_SAMPLE,
                t.sheet_name,
                t.delivery_status,
                t.identifier_value,
                pay_ok,
                ret_ok,
            )

        logging.info(
            "DEBUG summary (first %s PD/Cancelled tasks): API(pay=%s ret=%s) CSV(pay=%s ret=%s)",
            len(sample_pd_can),
            api_pay_match,
            api_ret_match,
            csv_pay_match,
            csv_ret_match,
        )

    # Assign id column indexes and group updates by sheet to avoid mixing different sheets
    updates_by_sheet: Dict[str, List[dict]] = {}
    for u in prepared_updates:
        if u["sheetName"] == SHEET_API:
            u["idColumnIndex"] = api_id_col_index
        elif u["sheetName"] == SHEET_CSV:
            u["idColumnIndex"] = csv_id_col_index
        # group
        updates_by_sheet.setdefault(u.get("sheetName", ""), []).append(u)

    # Send updates in per-sheet batches to ensure the WebApp receives homogeneous batches
    async with aiohttp.ClientSession() as session:
        for sheet_name, updates in updates_by_sheet.items():
            if not updates:
                continue
            for i in range(0, len(updates), BATCH_UPDATE_SIZE):
                chunk = updates[i : i + BATCH_UPDATE_SIZE]
                resp = await send_batch_updates(session, chunk)
                logging.info(
                    "Sent batch for sheet %s items %s-%s (%s items). Response: %s",
                    sheet_name,
                    i + 1,
                    i + len(chunk),
                    len(chunk),
                    resp,
                )

    logging.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
