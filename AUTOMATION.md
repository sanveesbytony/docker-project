# Automation Examples

## Daily Automated Execution

### Option 1: Windows Task Scheduler

1. Open Task Scheduler
2. Create a new task with these settings:
   - **Trigger**: Daily at your preferred time (e.g., 8:00 AM)
   - **Action**: Start a program
   - **Program**: `docker-compose`
   - **Arguments**: `up`
   - **Start in**: `C:\path\to\your\project`

Or use this PowerShell command to create the task:

```powershell
$action = New-ScheduledTaskAction -Execute "docker-compose" -Argument "up" -WorkingDirectory "C:\path\to\project"
$trigger = New-ScheduledTaskTrigger -Daily -At 8am
Register-ScheduledTask -Action $action -Trigger $trigger -TaskName "SteadFast Return Scraper" -Description "Daily return data scraping"
```

### Option 2: Linux/Mac Cron Job

Edit crontab:
```bash
crontab -e
```

Add this line to run daily at 8 AM:
```bash
0 8 * * * cd /path/to/project && docker-compose up >> /path/to/project/scraper.log 2>&1
```

### Option 3: Docker Restart Policy

Modify `docker-compose.yml` to add restart behavior:

```yaml
services:
  return-scraper:
    # ... existing config ...
    restart: "no"  # Change to "always" for auto-restart
```

Then run once daily using Task Scheduler or cron.

## Advanced Automation Scenarios

### Scenario 1: Run for Yesterday's Data

Create a wrapper script that sets the date:

**Linux/Mac** (`run-yesterday.sh`):
```bash
#!/bin/bash
export TARGET_DATE=$(date -d "yesterday" +%Y-%m-%d)
docker-compose up
```

**Windows** (`run-yesterday.bat`):
```batch
@echo off
for /f "tokens=1-3 delims=/ " %%a in ('date /t') do (
    set TODAY=%%c-%%a-%%b
)
REM You'll need to calculate yesterday manually or use PowerShell
docker-compose up
```

**Windows PowerShell** (`run-yesterday.ps1`):
```powershell
$yesterday = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
$env:TARGET_DATE = $yesterday
docker-compose up
```

### Scenario 2: Run for Multiple Dates

Create a script to run for a date range:

**Linux/Mac** (`run-date-range.sh`):
```bash
#!/bin/bash
START_DATE="2024-01-01"
END_DATE="2024-01-31"

current_date=$START_DATE
while [ "$current_date" != "$END_DATE" ]; do
    echo "Processing $current_date"
    export TARGET_DATE=$current_date
    docker-compose up
    current_date=$(date -I -d "$current_date + 1 day")
done
```

### Scenario 3: Email Notification on Completion

**Linux/Mac with mailx**:
```bash
#!/bin/bash
cd /path/to/project
docker-compose up > scraper.log 2>&1
if [ $? -eq 0 ]; then
    mail -s "SteadFast Scraper: Success" admin@example.com < scraper.log
else
    mail -s "SteadFast Scraper: FAILED" admin@example.com < scraper.log
fi
```

### Scenario 4: Backup Data After Scraping

**Linux/Mac**:
```bash
#!/bin/bash
cd /path/to/project
docker-compose up

# Backup after successful run
if [ $? -eq 0 ]; then
    BACKUP_DIR="./backups"
    mkdir -p $BACKUP_DIR
    DATE=$(date +%Y-%m-%d_%H-%M-%S)
    cp ./data/Return.xlsx "$BACKUP_DIR/Return_$DATE.xlsx"
    echo "Backup created: Return_$DATE.xlsx"
fi
```

**Windows PowerShell**:
```powershell
cd C:\path\to\project
docker-compose up

if ($LASTEXITCODE -eq 0) {
    $backupDir = ".\backups"
    New-Item -ItemType Directory -Force -Path $backupDir
    $timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
    Copy-Item ".\data\Return.xlsx" "$backupDir\Return_$timestamp.xlsx"
    Write-Host "Backup created: Return_$timestamp.xlsx"
}
```

## Monitoring and Logging

### View Real-time Logs
```bash
docker-compose logs -f
```

### Save Logs to File
```bash
docker-compose logs > scraper_$(date +%Y-%m-%d).log
```

### Check if Container is Running
```bash
docker-compose ps
```

### Health Check Script

**Linux/Mac** (`health-check.sh`):
```bash
#!/bin/bash
if docker-compose ps | grep -q "Up"; then
    echo "Scraper is running"
    exit 0
else
    echo "Scraper is not running"
    exit 1
fi
```

## Cloud Deployment

### Running on AWS EC2 / DigitalOcean / etc.

1. SSH into your server
2. Install Docker and Docker Compose
3. Clone/upload your project
4. Set up cron job:
   ```bash
   0 8 * * * cd /home/user/scraper && docker-compose up >> /var/log/scraper.log 2>&1
   ```

### Running on GitHub Actions

Create `.github/workflows/scraper.yml`:

```yaml
name: Daily Return Scraper

on:
  schedule:
    - cron: '0 8 * * *'  # Run daily at 8 AM UTC
  workflow_dispatch:      # Allow manual trigger

jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Set up Docker
        uses: docker/setup-buildx-action@v1
      
      - name: Run scraper
        env:
          STEADFAST_USERNAME: ${{ secrets.STEADFAST_USERNAME }}
          STEADFAST_PASSWORD: ${{ secrets.STEADFAST_PASSWORD }}
          TARGET_DATE: today
        run: docker-compose up
      
      - name: Upload results
        uses: actions/upload-artifact@v2
        with:
          name: return-data
          path: data/Return.xlsx
```

Remember to add secrets in GitHub repository settings!

## Tips

1. **Test First**: Always test your automation manually before scheduling
2. **Check Logs**: Regularly review logs to catch issues early
3. **Backup Data**: Implement automatic backups of the Excel file
4. **Monitor Failures**: Set up alerts for failed runs
5. **Update Credentials**: If you change your password, update the `.env` file
