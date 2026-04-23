# SteadFast Return Scraper - Docker Setup

This containerized application automatically scrapes return data from SteadFast and stores it in an Excel file.

## Project Structure

```
.
├── return_scraper.py      # Main Python script (automated version)
├── Dockerfile             # Container configuration
├── docker-compose.yml     # Docker Compose setup
├── requirements.txt       # Python dependencies
├── .env                   # Environment configuration (create from .env.example)
├── .env.example          # Environment configuration template
└── data/                 # Persistent data directory (created automatically)
    └── Return.xlsx       # Scraped data (auto-generated)
```

## Key Changes from Original Script

1. **No Manual Date Input**: Set `TARGET_DATE` environment variable instead
   - Use `today` for current date (default)
   - Or specify date as `YYYY-MM-DD`

2. **Automated File Storage**: Excel files are stored in `/app/data` (mounted to `./data` on host)

3. **Environment-based Configuration**: Credentials and settings via environment variables

4. **Container-ready**: Runs headless, no GUI required

## Setup Instructions

### 1. Configure Environment

Edit the `.env` file with your credentials:

```bash
STEADFAST_USERNAME=your_email@example.com
STEADFAST_PASSWORD=your_password_here
TARGET_DATE=today
```

### 2. Build the Container

```bash
docker-compose build
```

### 3. Run the Scraper

```bash
docker-compose up
```

To run in background (detached mode):

```bash
docker-compose up -d
```

### 4. View Logs

```bash
docker-compose logs -f
```

### 5. Stop the Container

```bash
docker-compose down
```

## Data Persistence

- All Excel files are stored in the `./data` directory on your host machine
- The data persists even when the container is stopped or removed
- You can access `./data/Return.xlsx` directly from your file system

## Running with Different Dates

To scrape data for a specific date, modify the `.env` file:

```bash
# For today's data
TARGET_DATE=today

# For a specific date
TARGET_DATE=2024-01-30
```

Then restart the container:

```bash
docker-compose restart
```

## Scheduled Automation (Optional)

To run the scraper daily at a specific time, you can:

### Option 1: Using Docker Compose with restart policy
The current setup uses `restart: unless-stopped`, so it will re-run if it crashes.

### Option 2: Using Cron (Linux/Mac)
Add to your crontab:

```bash
# Run every day at 8 AM
0 8 * * * cd /path/to/project && docker-compose up
```

### Option 3: Using Windows Task Scheduler
Create a scheduled task that runs:

```cmd
docker-compose -f "C:\path\to\project\docker-compose.yml" up
```

## Troubleshooting

### Container fails to start
- Check logs: `docker-compose logs`
- Verify credentials in `.env` file
- Ensure Docker Desktop is running

### No data being saved
- Check if `./data` directory exists and is writable
- Verify the container has access to the volume: `docker-compose exec return-scraper ls -la /app/data`

### Playwright errors
- The Dockerfile installs all necessary browser dependencies
- If issues persist, try rebuilding: `docker-compose build --no-cache`

## Manual Run (Without Docker Compose)

Build the image:
```bash
docker build -t return-scraper .
```

Run the container:
```bash
docker run -e STEADFAST_USERNAME="your_email@example.com" \
           -e STEADFAST_PASSWORD="your_password" \
           -e TARGET_DATE="today" \
           -v $(pwd)/data:/app/data \
           return-scraper
```

## Environment Variables Reference

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `STEADFAST_USERNAME` | SteadFast login email | (required) | `user@example.com` |
| `STEADFAST_PASSWORD` | SteadFast login password | (required) | `MyPassword123` |
| `TARGET_DATE` | Date to scrape data for | `today` | `today`, `2024-01-30` |
| `DATA_DIR` | Data storage directory | `/app/data` | `/app/data` |
