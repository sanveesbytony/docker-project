# SteadFast Return Scraper - Web Interface

## 🌟 Overview

This web application provides a user-friendly interface to run the SteadFast return scraper without touching the command line. Users can:

- **Select a date** to scrape data for
- **Run the scraper** with one click
- **Download the Excel file** after scraping completes
- **Configure login credentials** through the web interface

---

## 📋 Prerequisites

1. **Docker Desktop** - Must be installed and running
2. **Python 3.7+** - For running the web server
3. **Existing scraper setup** - Your current Docker scraper must be configured

---

## 🚀 Quick Start

### Step 1: Install Web App Dependencies

```bash
pip install -r requirements-web.txt
```

### Step 2: Start the Web Server

```bash
python app.py
```

The server will start on `http://localhost:5000`

### Step 3: Access the Web Interface

Open your browser and navigate to:
```
http://localhost:5000
```

Or from another device on the same network:
```
http://YOUR_IP_ADDRESS:5000
```

To find your IP address:
- **Windows**: `ipconfig` (look for IPv4 Address)
- **Mac/Linux**: `ifconfig` or `ip addr`

---

## 📱 How to Use

### 1. **Configure Credentials** (First Time Only)

1. Click the **"Edit Login Credentials"** button
2. Enter your SteadFast username and password
3. Click **"Save Configuration"**

This will update your `.env` file automatically.

### 2. **Run the Scraper**

1. Select a date using the date picker (or click "Today")
2. Click **"Run Scraper"**
3. Watch the status bar for progress updates
4. Wait for the scraping to complete (usually 2-10 minutes)

### 3. **Download Results**

Once scraping completes:
1. The **"Download Results"** section will appear
2. Click **"Download Excel File"**
3. The file will download to your browser's default location

### 4. **View Previous Files**

The **"Previous Files"** section shows all Excel files in your `data/` directory with:
- File name
- File size
- Last modified date

---

## 🏗️ Architecture

```
┌──────────────────┐
│   Web Browser    │ ← User accesses http://localhost:5000
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Flask Web App   │ ← app.py (Web interface)
│  (Port 5000)     │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Docker Compose  │ ← Runs your existing scraper
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Scraper Container│ ← return_scraper.py
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  ./data/         │ ← Excel files saved here
│  Return.xlsx     │
└──────────────────┘
```

---

## 🔧 Configuration

### Environment Variables

The web app uses the same `.env` file as your scraper:

```env
STEADFAST_USERNAME=your_email@example.com
STEADFAST_PASSWORD=your_password
TARGET_DATE=today
```

You can edit these through:
1. The web interface (recommended)
2. Directly editing the `.env` file
3. The `config.json` file (auto-generated)

### Config File Location

- **`.env`** - Main configuration file
- **`config.json`** - Web app configuration cache

---

## 🌐 Remote Access

To access the web app from other devices on your network:

### Option 1: Local Network Access

1. Find your computer's IP address
2. Share the link: `http://YOUR_IP:5000`
3. Anyone on your network can access it

### Option 2: Internet Access (Advanced)

Use a tunneling service like:
- **ngrok**: `ngrok http 5000`
- **localhost.run**: `ssh -R 80:localhost:5000 localhost.run`

**Security Warning**: Be careful when exposing your app to the internet. Consider adding authentication.

---

## 📊 API Endpoints

The web app exposes these endpoints:

| Method | Endpoint    | Description                    |
|--------|-------------|--------------------------------|
| GET    | `/`         | Main web interface             |
| POST   | `/scrape`   | Start scraping process         |
| GET    | `/status`   | Get current scraper status     |
| GET    | `/download` | Download the Excel file        |
| GET    | `/config`   | Get current configuration      |
| POST   | `/config`   | Update configuration           |
| GET    | `/files`    | List all Excel files           |

### Example: Start Scraper via API

```bash
curl -X POST http://localhost:5000/scrape \
  -H "Content-Type: application/json" \
  -d '{"date": "2024-01-30"}'
```

### Example: Check Status

```bash
curl http://localhost:5000/status
```

Response:
```json
{
  "running": true,
  "message": "Scraping data for 2024-01-30...",
  "last_run": "2024-01-30 14:30:00"
}
```

---

## 🔒 Security Considerations

### Current Setup (Local Use)

- **No authentication** - Anyone with network access can use the app
- **Credentials stored** in `.env` and `config.json` files
- **No HTTPS** - Traffic is unencrypted

### Recommended for Production

If you want to make this publicly accessible:

1. **Add Authentication**
   ```python
   from flask_httpauth import HTTPBasicAuth
   auth = HTTPBasicAuth()
   ```

2. **Use HTTPS**
   - Use a reverse proxy (nginx)
   - Get SSL certificate (Let's Encrypt)

3. **Environment Security**
   - Use stronger password protection
   - Add rate limiting
   - Implement user sessions

---

## 🐛 Troubleshooting

### Web Server Won't Start

**Error**: `Address already in use`

**Solution**: Change the port in `app.py`:
```python
app.run(debug=True, host='0.0.0.0', port=8080)  # Changed from 5000
```

### Scraper Not Starting

**Check**:
1. Docker Desktop is running
2. `.env` file exists with valid credentials
3. View logs: `docker-compose logs`

### Can't Download File

**Issue**: "Excel file not found"

**Solution**:
1. Run the scraper first
2. Check if `./data/Return.xlsx` exists
3. Verify file permissions

### Can't Access from Another Device

**Check**:
1. Both devices on same network
2. Firewall allows port 5000
3. Using correct IP address (not 127.0.0.1)

**Windows Firewall**:
```powershell
# Allow inbound traffic on port 5000
New-NetFirewallRule -DisplayName "Flask App" -Direction Inbound -LocalPort 5000 -Protocol TCP -Action Allow
```

---

## 🎨 Customization

### Change Theme Colors

Edit `static/css/style.css`:

```css
/* Change primary gradient */
background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);

/* To something else */
background: linear-gradient(135deg, #FF6B6B 0%, #4ECDC4 100%);
```

### Change Port

Edit `app.py`:
```python
app.run(debug=True, host='0.0.0.0', port=YOUR_PORT)
```

### Add Custom Features

The Flask app is easy to extend:

```python
@app.route('/custom-endpoint')
def custom_feature():
    # Your code here
    return jsonify({"message": "Custom feature"})
```

---

## 🔄 Running as a Service

### Windows (Task Scheduler)

1. Create a batch file `start_web.bat`:
```bat
@echo off
cd C:\path\to\project
python app.py
```

2. Create scheduled task to run at startup

### Linux (systemd)

1. Create `/etc/systemd/system/steadfast-web.service`:
```ini
[Unit]
Description=SteadFast Web Interface
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/project
ExecStart=/usr/bin/python3 app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

2. Enable and start:
```bash
sudo systemctl enable steadfast-web
sudo systemctl start steadfast-web
```

---

## 📦 Project Structure

```
.
├── app.py                    # Flask web server
├── templates/
│   └── index.html           # Main web interface
├── static/
│   ├── css/
│   │   └── style.css        # Styling
│   └── js/
│       └── script.js        # Client-side logic
├── requirements-web.txt     # Web app dependencies
├── config.json              # Auto-generated config
├── .env                     # Credentials
├── data/                    # Excel files
│   └── Return.xlsx
├── return_scraper.py        # Scraper script
├── Dockerfile               # Docker config
└── docker-compose.yml       # Docker orchestration
```

---

## 🚦 Status Indicators

| Icon | Status | Description |
|------|--------|-------------|
| ⚪   | Ready  | System ready to run |
| 🟡   | Running | Scraper is currently running |
| 🟢   | Success | Scraping completed successfully |
| 🔴   | Error  | An error occurred |

---

## 💡 Tips & Best Practices

1. **First Time Setup**
   - Always configure credentials before first run
   - Test with today's date first

2. **Regular Use**
   - Run scraper during off-peak hours
   - Download files immediately after scraping
   - Keep credentials updated if they change

3. **Monitoring**
   - Watch the status bar for real-time updates
   - Check "Previous Files" to verify completions
   - Review Docker logs if issues occur

4. **Data Management**
   - Files are named with timestamps
   - Old files are kept in `./data/`
   - Manually delete old files if needed

---

## 📞 Support

For issues or questions:

1. Check the **Troubleshooting** section above
2. Review Docker logs: `docker-compose logs`
3. Check browser console for JavaScript errors (F12)

---

## 🎯 Next Steps

Want to enhance this further?

1. **Add Email Notifications** when scraping completes
2. **Schedule Automatic Runs** (daily at specific time)
3. **Add User Authentication** for security
4. **Create Mobile App** using React Native
5. **Add Data Visualization** dashboard
6. **Multi-user Support** with different credentials
7. **Cloud Deployment** (AWS, Azure, Heroku)

Let me know if you'd like help implementing any of these features!
