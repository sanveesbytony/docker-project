# Project Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Your Computer                            │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              Docker Container                          │ │
│  │                                                        │ │
│  │  ┌──────────────────────────────────────┐             │ │
│  │  │   return_scraper.py                  │             │ │
│  │  │   - Reads TARGET_DATE env var        │             │ │
│  │  │   - Logs into SteadFast              │             │ │
│  │  │   - Scrapes return data              │             │ │
│  │  │   - Saves to /app/data/Return.xlsx   │             │ │
│  │  └──────────────────────────────────────┘             │ │
│  │                      ↓                                 │ │
│  │  ┌──────────────────────────────────────┐             │ │
│  │  │   /app/data/Return.xlsx              │ ◄───────────┼─┼─ Volume Mount
│  │  │   (Inside container)                 │             │ │
│  │  └──────────────────────────────────────┘             │ │
│  └────────────────────────────────────────────────────────┘ │
│                         ║                                    │
│                         ║ (Volume mapping)                   │
│                         ▼                                    │
│  ┌────────────────────────────────────────────────────────┐ │
│  │   ./data/Return.xlsx                                   │ │
│  │   (On your computer)                                   │ │
│  │   - Persists after container stops                     │ │
│  │   - Accessible directly from file system               │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Data Flow

```
1. Configuration
   .env file → Environment Variables → Container
   
2. Execution
   Container starts → Python script runs → Playwright browser (headless)
   
3. Scraping
   Login to SteadFast → Navigate to returns → Extract data
   
4. Storage
   Python script → Excel file (/app/data/) → Volume mount → ./data/
   
5. Access
   You can open ./data/Return.xlsx from your file system
```

## Directory Structure

```
steadfast-scraper/
│
├── return_scraper.py          # Main Python script
├── Dockerfile                 # Container image definition
├── docker-compose.yml         # Docker orchestration config
├── requirements.txt           # Python dependencies
│
├── .env                       # Your configuration (credentials, date)
├── .env.example              # Template for .env
├── .gitignore                # Git ignore rules
│
├── manage.sh                 # Linux/Mac helper script
├── manage.bat                # Windows helper script
│
├── README.md                 # Full documentation
├── QUICKSTART.md             # Quick setup guide
├── CHANGES.md                # What changed from original
├── AUTOMATION.md             # Automation examples
├── ARCHITECTURE.md           # This file
│
└── data/                     # Data directory (auto-created)
    └── Return.xlsx           # Scraped data (auto-generated)
```

## Component Interaction

```
┌──────────────┐
│ .env file    │
│ - USERNAME   │
│ - PASSWORD   │
│ - DATE       │
└──────┬───────┘
       │
       ▼
┌──────────────────────┐
│ docker-compose.yml   │
│ - Reads .env         │
│ - Passes to container│
│ - Maps volumes       │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ Dockerfile           │
│ - Base image         │
│ - Install deps       │
│ - Setup Playwright   │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────────────┐
│ Container Runtime            │
│ - Executes return_scraper.py │
│ - Writes to /app/data/       │
└──────┬───────────────────────┘
       │
       ▼
┌──────────────────────┐
│ Volume Mount         │
│ /app/data ↔ ./data   │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ Return.xlsx          │
│ (Persistent storage) │
└──────────────────────┘
```

## Key Features

### 1. Environment-Based Configuration
- No hardcoded values
- Easy to change without modifying code
- Secure credential management

### 2. Data Persistence
- Volume mounting ensures data survives container restarts
- Excel file accessible from host system
- No data loss on container removal

### 3. Automated Date Handling
- No manual input required
- Set via environment variable
- Supports 'today' or specific dates (YYYY-MM-DD)

### 4. Containerization Benefits
- Consistent environment across systems
- No dependency conflicts
- Easy deployment and scaling
- Isolated from host system

### 5. Cross-Platform Support
- Works on Windows, Linux, and Mac
- Platform-specific helper scripts (manage.sh, manage.bat)
- Docker handles OS differences

## Network Flow

```
Container → Internet → SteadFast Website
    ↓
Login with credentials
    ↓
Navigate to return lists
    ↓
Extract data for target date
    ↓
Parse and process data
    ↓
Save to Excel file
    ↓
Volume mount → Host filesystem
```

## Security Considerations

1. **Credentials**: Stored in `.env` file (not committed to git)
2. **Network**: Container uses host network to access SteadFast
3. **Data**: Excel file stored locally, no external transmission
4. **Isolation**: Container runs isolated from host system

## Scaling Possibilities

### Single Date
```bash
TARGET_DATE=today docker-compose up
```

### Multiple Dates (Sequential)
```bash
for date in 2024-01-01 2024-01-02 2024-01-03; do
  TARGET_DATE=$date docker-compose up
done
```

### Parallel Processing (Advanced)
```bash
# Run multiple containers for different dates simultaneously
TARGET_DATE=2024-01-01 docker-compose up -d
TARGET_DATE=2024-01-02 docker-compose -f docker-compose2.yml up -d
```
