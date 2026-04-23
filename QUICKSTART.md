# Quick Start Guide

## Setup in 3 Steps

### 1. Verify Configuration
Your `.env` file is already configured with your credentials. The scraper will run for **today's date** by default.

To change the date, edit `.env`:
```
TARGET_DATE=today          # For today
TARGET_DATE=2024-01-30     # For specific date
```

### 2. Build the Container
```bash
docker-compose build
```

### 3. Run the Scraper

**Option A: Run in foreground (see logs in real-time)**
```bash
docker-compose up
```

**Option B: Run in background**
```bash
docker-compose up -d
```

View logs:
```bash
docker-compose logs -f
```

## Using the Management Scripts

### Windows
```cmd
manage.bat build      # Build image
manage.bat start      # Start in background
manage.bat logs       # View logs
manage.bat stop       # Stop scraper
```

### Linux/Mac
```bash
./manage.sh build     # Build image
./manage.sh start     # Start in background
./manage.sh logs      # View logs
./manage.sh stop      # Stop scraper
```

## Where is the Data Stored?

All scraped data is saved in:
- **Container path**: `/app/data/Return.xlsx`
- **Your computer**: `./data/Return.xlsx` (in the project folder)

The `data` folder will be created automatically on first run.

## Changing the Target Date

Edit `.env` file:
```bash
TARGET_DATE=2024-02-15
```

Then restart:
```bash
docker-compose restart
```

## Stopping the Scraper

```bash
docker-compose down
```

Your data in `./data/Return.xlsx` will be preserved!

## Troubleshooting

**Container won't start?**
- Check Docker Desktop is running
- View logs: `docker-compose logs`

**No data being saved?**
- Check if `data` folder exists
- Check logs for errors: `docker-compose logs`

**Wrong credentials?**
- Edit `.env` file with correct credentials
- Rebuild: `docker-compose build`
- Restart: `docker-compose restart`
