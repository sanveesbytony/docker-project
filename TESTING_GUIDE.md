# Testing the Updated Scraper

## Quick Test

### Option 1: Using the Web Interface (Recommended)

1. **Make sure the web server is running:**
   - Already running at: http://localhost:5000
   - If not, run: `python app.py`

2. **Open your browser:**
   - Go to: http://localhost:5000

3. **Select a date that has return lots:**
   - Click the date picker
   - Choose a date you know has returns

4. **Run the scraper:**
   - Click "Run Scraper"
   - Watch the status bar for progress

5. **Check the results:**
   - Look at the console/terminal logs to see:
     - How many return lots were found
     - Total IDs collected from all lots
   - Download the Excel file
   - Verify columns are in correct order

---

### Option 2: Using Command Line

1. **Stop the web server** (if running)

2. **Set the date** in `.env` file:
   ```env
   TARGET_DATE=2026-01-30
   ```
   Or use today:
   ```env
   TARGET_DATE=today
   ```

3. **Run with Docker:**
   ```bash
   docker-compose up
   ```

4. **Watch the output:**
   - You'll see logs like:
   ```
   Found return lot #1 for January 30, 2026: January 30, 2026 8:00 AM
     Extracted ID: SF123456
     ...
     Total IDs from lot #1: 25
   
   Found return lot #2 for January 30, 2026: January 30, 2026 2:30 PM
     Extracted ID: SF789012
     ...
     Total IDs from lot #2: 15
   
   Total matching return lots: 2
   Total IDs collected: 40
   ```

5. **Check the Excel file:**
   - Open `data/Return.xlsx`
   - Verify column headers:
     ```
     SL | Id | Entry Date | Invoice | Charge | Name | Phone | Amount Status | Note | Reason
     ```

---

## What to Look For

### Console Output Indicators

✅ **Multiple Lots Found:**
```
Found return lot #1 for January 30, 2026: January 30, 2026 8:00 AM
Found return lot #2 for January 30, 2026: January 30, 2026 2:30 PM
Total matching return lots: 2
```

✅ **All IDs Collected:**
```
Total IDs collected: 50
```
(Should be sum of all lots)

✅ **No Duplicates:**
```
Added 10 new ID(s) to Excel
```
(Only new IDs are added)

---

### Excel File Checks

✅ **Correct Column Headers** (in this exact order):
```
SL | Id | Entry Date | Invoice | Charge | Name | Phone | Amount Status | Note | Reason
```

✅ **Auto-Numbered SL Column:**
- Should be: 1, 2, 3, 4, 5...
- No gaps or duplicates

✅ **All IDs Present:**
- Count rows in Excel
- Should match "Total IDs collected" from logs

✅ **Data Populated:**
- Entry Date filled
- Invoice numbers present
- Names and phones populated
- Amount Status has values

---

## Test Scenarios

### Scenario 1: Fresh Start (No Existing File)

**Setup:**
- Delete `data/Return.xlsx` if it exists
- Select a date with return lots

**Expected Result:**
- New Excel file created
- SL starts from 1
- All columns in correct order
- All IDs from all lots included

---

### Scenario 2: Appending to Existing File

**Setup:**
- Run scraper for Date A (creates file with 20 rows)
- Run scraper for Date B (finds 15 new IDs)

**Expected Result:**
- Excel now has 35 rows
- SL continues: 1-20 from Date A, 21-35 from Date B
- No duplicate IDs

---

### Scenario 3: Multiple Lots Same Date

**Setup:**
- Select a date that has 2+ return lots

**Expected Result:**
- Console shows "Found return lot #1", "Found return lot #2", etc.
- All IDs from all lots collected
- Excel has combined data from all lots

---

### Scenario 4: Re-running Same Date

**Setup:**
- Run scraper for January 30 (collects 50 IDs)
- Run scraper for January 30 again

**Expected Result:**
- Console shows: "No new IDs to add to Excel"
- Excel file unchanged (no duplicates)
- SL numbers stay the same

---

## Sample Expected Output

### Console Log:
```
Data directory: /app/data
Excel file path: /app/data/Return.xlsx
Target date set to: 2026-01-30

Navigating to SteadFast dashboard for login...
Logged in successfully.

Navigating to return lists page: https://steadfast.com.bd/user/returnlists
Waiting for return list rows to appear...
Return list rows found.
On return lists page. Searching for ALL return lists for January 30, 2026...

Found return lot #1 for January 30, 2026: January 30, 2026 8:00 AM
Clicked 'View' for lot #1. Extracting ID numbers...
  Extracted ID: SF001234
  Extracted ID: SF001235
  Extracted ID: SF001236
  Total IDs from lot #1: 3

Found return lot #2 for January 30, 2026: January 30, 2026 3:15 PM
Clicked 'View' for lot #2. Extracting ID numbers...
  Extracted ID: SF005678
  Extracted ID: SF005679
  Total IDs from lot #2: 2

Total matching return lots: 2
Total IDs collected: 5

Added 5 new ID(s) to Excel for 2026-01-30: ['SF001234', 'SF001235', 'SF001236', 'SF005678', 'SF005679']

Navigating back to the search consignment page for fetching data...
Auto-saved data.

Processing ID: SF001234
ID SF001234 processed and updated in Excel.

Processing ID: SF001235
ID SF001235 processed and updated in Excel.

Processing ID: SF001236
ID SF001236 processed and updated in Excel.

Processing ID: SF005678
ID SF005678 processed and updated in Excel.

Processing ID: SF005679
ID SF005679 processed and updated in Excel.

All statuses updated successfully!
Browser closed. Script finished.
```

### Excel File (Return.xlsx):
```
| SL | Id       | Entry Date | Invoice    | Charge | Name          | Phone       | Amount Status | Note                  | Reason                    |
|----|----------|------------|------------|--------|---------------|-------------|---------------|-----------------------|---------------------------|
| 1  | SF001234 | 01-30-2026 | INV-10001  | 60     | Ahmed Khan    | 01712345678 | 1500          | Full Amount Returned  | null                      |
| 2  | SF001235 | 01-30-2026 | INV-10002  | 60     | Fatima Begum  | 01798765432 | 1200          | Full Amount Returned  | Rider Note: Success       |
| 3  | SF001236 | 01-29-2026 | INV-10003  | 70     | Karim Mia     | 01655443322 | 500           | Amount has been changed | Rider Note: Partial return|
| 4  | SF005678 | 01-30-2026 | INV-20001  | 65     | Rina Das      | 01911223344 | 2000          | Full Amount Returned  | null                      |
| 5  | SF005679 | 01-30-2026 | INV-20002  | 60     | Sumon Ahmed   | 01822334455 | 1800          | Full Amount Returned  | Rider Note: Delivered     |
```

---

## Troubleshooting

### Issue: Only Finding One Lot

**Symptom:** Console shows only "Found return lot #1"

**Possible Causes:**
- Only one lot exists for that date
- Date format mismatch

**Solution:**
- Try a different date with multiple lots
- Check the return lists page manually

---

### Issue: Wrong Column Headers

**Symptom:** Excel columns not in specified order

**Possible Causes:**
- Using old Excel file with old format

**Solution:**
- Delete `data/Return.xlsx`
- Re-run scraper to create new file with correct format

---

### Issue: SL Numbers Not Sequential

**Symptom:** SL column has gaps or wrong numbers

**Possible Causes:**
- Data corruption

**Solution:**
- Delete `data/Return.xlsx`
- Re-run scraper fresh

---

## Verifying the Fix

To confirm multiple lots are being handled:

1. **Check Return Lists Page Manually:**
   - Go to: https://steadfast.com.bd/user/returnlists
   - Find a date with 2+ return lots
   - Note the times (e.g., 8:00 AM, 3:00 PM)

2. **Run Scraper for That Date:**
   - Use web interface or command line

3. **Verify Logs Show All Lots:**
   - Should see "Found return lot #1", "Found return lot #2", etc.
   - Should match number of lots you saw manually

4. **Count IDs in Excel:**
   - Should match sum of all lot IDs

---

## Next Steps After Testing

Once you verify it's working:

✅ Use the web interface for daily scraping  
✅ Data will accumulate in a single Excel file  
✅ Each run appends new data  
✅ No duplicates  
✅ Proper formatting  

Enjoy your complete, properly formatted return data! 🎉
