# 🚀 Quick Start Guide - Web Interface

## ⚡ Get Started in 3 Steps

### Step 1: Install Dependencies
```bash
pip install -r requirements-web.txt
```

### Step 2: Start the Server

**Windows:**
```bash
start_web.bat
```
Or:
```bash
python app.py
```

**Mac/Linux:**
```bash
chmod +x start_web.sh
./start_web.sh
```
Or:
```bash
python app.py
```

### Step 3: Open Your Browser

Navigate to: **http://localhost:5000**

---

## 📱 First Time Setup

1. **Click "Edit Login Credentials"**
2. **Enter your SteadFast username and password**
3. **Click "Save Configuration"**

That's it! You're ready to use the app.

---

## 🎯 How to Use

### Run the Scraper

1. Select a date (or click "Today")
2. Click "Run Scraper"
3. Wait for completion (2-10 minutes)
4. Download the Excel file

### Access from Another Device

1. Find your computer's IP address:
   - Windows: `ipconfig` → Look for IPv4 Address
   - Mac: System Preferences → Network
   - Linux: `ip addr`

2. Share this link with others on your network:
   ```
   http://YOUR_IP_ADDRESS:5000
   ```

---

## 🔧 Troubleshooting

### Port Already in Use

If you get "Address already in use" error, change the port in `app.py`:

```python
app.run(debug=True, host='0.0.0.0', port=8080)  # Changed from 5000
```

Then access: `http://localhost:8080`

### Can't Access from Other Devices

**Windows**: Allow port through firewall
```powershell
New-NetFirewallRule -DisplayName "Flask App" -Direction Inbound -LocalPort 5000 -Protocol TCP -Action Allow
```

### Docker Not Running

Make sure Docker Desktop is running before clicking "Run Scraper"

---

## 📖 Full Documentation

For complete documentation, see:
- **WEB_APP_GUIDE.md** - Comprehensive guide
- **README.md** - Docker scraper documentation
- **ARCHITECTURE.md** - System architecture

---

## 🎨 What's Included

✅ Beautiful web interface  
✅ Date picker for selecting target date  
✅ One-click scraper execution  
✅ Real-time status updates  
✅ Download Excel files  
✅ Configuration management  
✅ File browser for previous scrapes  
✅ Mobile-responsive design  

---

## 🌐 Features

- **No Command Line** - Everything through the web
- **Remote Access** - Use from any device on your network
- **Easy Configuration** - Edit credentials through UI
- **Auto-Updates** - Status refreshes automatically
- **Download Manager** - Easy file downloads
- **Progress Tracking** - See scraper status in real-time

---

## 📦 What You Need

- ✅ Docker Desktop (already installed)
- ✅ Python 3.7+ (already installed)
- ✅ Flask (installed in Step 1)
- ✅ Your existing scraper setup

---

## 🎓 Next Steps

Want to do more?

1. **Schedule Automatic Runs** - See WEB_APP_GUIDE.md
2. **Add Security** - Add authentication
3. **Cloud Deployment** - Deploy to AWS/Azure/Heroku
4. **Email Notifications** - Get notified when done

---

## 💡 Pro Tips

- Keep the terminal/command prompt open while using the web interface
- The scraper runs in Docker, just like before
- All your existing data in `./data/` is still accessible
- You can still use `docker-compose up` if you prefer command line

---

## ❓ Need Help?

Check the troubleshooting section above or review the full documentation in **WEB_APP_GUIDE.md**

Enjoy your new web interface! 🎉
