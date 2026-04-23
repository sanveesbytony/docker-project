# Scraper Updates - Multiple Return Lots Support

## Latest Update: Multi-Tab Approach (v2)

### Problem Fixed:
The initial implementation using `page.go_back()` caused DOM corruption errors after processing the first return lot. Error:
```
playwright._impl._errors.Error: Protocol error (DOM.describeNode): Cannot find context with specified id
```

### Solution:
**Multi-Tab Strategy** - Instead of navigating back/forward on a single page:
1. Scan return lists page to collect all matching URLs
2. Open each return lot in a separate tab
3. Extract IDs and close each tab
4. Use fresh tab for fetching details

**Result:** ✅ Now successfully processes **unlimited** return lots without DOM errors!

See `MULTI_TAB_APPROACH.md` for detailed technical explanation.

---

## Changes Made

### 1. **Multiple Return Lots Handling**

**Previous Behavior:**
- Only fetched data from the FIRST return lot matching the selected date
- Stopped searching after finding one match (had `break` statement)

**New Behavior:**
- Fetches data from ALL return lots matching the selected date
- Continues searching through all rows, appending IDs from each matching lot
- Reports total number of matching lots and total IDs collected

**Example:**
If you select "January 30, 2026" and there are 3 return lots created on that date:
- Lot 1: 50 IDs
- Lot 2: 30 IDs  
- Lot 3: 20 IDs

**Result:** All 100 IDs will be collected and processed

---

### 2. **Excel Column Headers Updated**

**New Column Order:**
```
SL | Id | Entry Date | Invoice | Charge | Name | Phone | Amount Status | Note | Reason
```

**Column Details:**

| Column | Description | Example |
|--------|-------------|---------|
| **SL** | Serial number (auto-numbered) | 1, 2, 3... |
| **Id** | Consignment ID | SF123456 |
| **Entry Date** | Date the return was created | 01-30-2026 |
| **Invoice** | Invoice number(s) | INV-001, INV-002 |
| **Charge** | Delivery charge | 60 |
| **Name** | Customer name | John Doe |
| **Phone** | Customer phone number | 01712345678 |
| **Amount Status** | COD amount returned | 1500 |
| **Note** | Return note/status | Full Amount Returned |
| **Reason** | Rider notes/reason | Rider Note: Customer refused |

---

### 3. **Auto-Numbering (SL Column)**

The scraper now automatically assigns serial numbers:

**For New Files:**
- Starts from 1

**For Existing Files:**
- Continues from the last SL number
- Example: If existing file has 50 rows (SL 1-50), new entries start at 51

---

## How It Works Now

### Workflow:

1. **Navigate to Return Lists Page**
   ```
   https://steadfast.com.bd/user/returnlists
   ```

2. **Search for ALL Matching Return Lots**
   - Scans all rows in the return lists table
   - Identifies ALL lots that match your selected date
   - Does NOT stop after first match

3. **Extract IDs from Each Lot**
   - Clicks "View" for each matching lot
   - Extracts all consignment IDs
   - Goes back and continues searching
   - Repeats for all matching lots

4. **Append All IDs**
   - Checks if IDs already exist in Excel
   - Only adds NEW IDs (prevents duplicates)
   - Appends to the bottom of existing data

5. **Fetch Details for Each ID**
   - Searches each ID on the dashboard
   - Extracts: Entry Date, Invoice, Charge, Name, Phone, Amount Status, Note, Reason
   - Updates Excel row by row
   - Saves after each ID (crash-safe)

---

## Example Log Output

```
Navigating to return lists page: https://steadfast.com.bd/user/returnlists
Return list rows found.
On return lists page. Searching for ALL return lists for January 30, 2026...

Found return lot #1 for January 30, 2026: January 30, 2026 8:00 AM
Clicked 'View' for lot #1. Extracting ID numbers...
  Extracted ID: SF123456
  Extracted ID: SF123457
  Extracted ID: SF123458
  Total IDs from lot #1: 3

Found return lot #2 for January 30, 2026: January 30, 2026 2:00 PM
Clicked 'View' for lot #2. Extracting ID numbers...
  Extracted ID: SF789012
  Extracted ID: SF789013
  Total IDs from lot #2: 2

Total matching return lots: 2
Total IDs collected: 5

Added 5 new ID(s) to Excel for 2026-01-30
```

---

## Excel File Structure

### Before Scraping Data:
```
| SL | Id       | Entry Date | Invoice | Charge | Name | Phone | Amount Status | Note | Reason |
|----|----------|------------|---------|--------|------|-------|---------------|------|--------|
| 1  | SF123456 |            |         |        |      |       |               |      |        |
| 2  | SF123457 |            |         |        |      |       |               |      |        |
| 3  | SF123458 |            |         |        |      |       |               |      |        |
```

### After Scraping Data:
```
| SL | Id       | Entry Date | Invoice  | Charge | Name      | Phone       | Amount Status | Note                  | Reason              |
|----|----------|------------|----------|--------|-----------|-------------|---------------|-----------------------|---------------------|
| 1  | SF123456 | 01-30-2026 | INV-001  | 60     | John Doe  | 01712345678 | 1500          | Full Amount Returned  | Rider Note: Success |
| 2  | SF123457 | 01-30-2026 | INV-002  | 60     | Jane Doe  | 01798765432 | 1200          | Full Amount Returned  | null                |
| 3  | SF123458 | 01-29-2026 | INV-003  | 70     | Bob Smith | 01655443322 | 800           | Amount has been changed | Rider Note: Partial |
```

---

## Duplicate Prevention

The scraper checks if an ID already exists:

```python
new_ids_to_add = [id_num for id_num in return_ids_for_selected_date 
                  if id_num not in existing_df['Id'].values]
```

**Behavior:**
- ✅ Only NEW IDs are added
- ✅ Existing IDs are skipped
- ✅ No duplicates created

**Example:**
- Existing Excel has: SF123456, SF123457
- New scrape finds: SF123456, SF123458, SF123459
- **Added to Excel:** SF123458, SF123459 only

---

## Testing the Changes

### Test Scenario 1: Single Return Lot
**Date:** January 30, 2026  
**Return Lots:** 1 lot with 10 IDs  
**Expected:** 10 IDs extracted, all processed

### Test Scenario 2: Multiple Return Lots
**Date:** January 30, 2026  
**Return Lots:** 3 lots (50 + 30 + 20 IDs)  
**Expected:** 100 IDs extracted, all processed

### Test Scenario 3: Existing Data
**Date:** January 30, 2026  
**Existing Excel:** 50 IDs already scraped  
**New Return Lot:** 20 IDs (10 duplicates, 10 new)  
**Expected:** Only 10 new IDs added (total 60 rows)

---

## Benefits

✅ **Complete Data Collection** - Never miss return lots  
✅ **Proper Organization** - Clear column headers  
✅ **Auto-Numbering** - Easy to track rows  
✅ **No Duplicates** - Smart ID checking  
✅ **Cumulative** - Data appends to existing file  
✅ **Crash-Safe** - Saves after each ID  

---

## Migration Notes

### If You Have Existing Excel Files:

**Old Format:**
```
| ID Numbers | Note | Amount Status | Reason | Entry Date | Invoice | Phone | Charge | Name |
```

**New Format:**
```
| SL | Id | Entry Date | Invoice | Charge | Name | Phone | Amount Status | Note | Reason |
```

**To Migrate:**
1. The scraper will create a new file with the new format
2. Your old data remains in the old Excel file
3. Or manually copy data to match new column order

**Recommendation:** Start fresh with the new format for new scrapes

---

## Summary

The scraper now:
1. ✅ Finds ALL return lots for your selected date (not just one)
2. ✅ Extracts ALL IDs from ALL matching lots
3. ✅ Appends them all to the Excel file
4. ✅ Uses the correct column headers in the specified order
5. ✅ Auto-numbers rows with SL column
6. ✅ Prevents duplicates
7. ✅ Saves progress after each ID

Your data collection is now complete and properly organized!
