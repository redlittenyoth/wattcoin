# WattNode GUI v2.0 - Changelog

## 🎉 Major Features Added

### **1. Tabbed Interface**
- **Dashboard Tab** - Quick stats, earnings graph, network overview
- **Settings Tab** - Configuration and CPU allocation controls
- **History Tab** - Complete job history with scrollable table

### **2. CPU Allocation Control** 🎛️
- **Slider control** - Choose 25%, 50%, 75%, or 100% CPU usage
- **Real-time display** - Shows "Using X of Y cores"
- **Persistent settings** - Saved to config file
- **Smart allocation** - Prevents system overload

**How it works:**
- Limits concurrent job processing based on allocation
- Lower allocation = fewer simultaneous jobs
- Higher allocation = more throughput, more earnings
- Recommended: 50% for daily use, 75-100% for dedicated nodes

### **3. Real-Time Earnings Graph** 📊
- **Visual earnings tracking** - Line graph shows WATT earned over time
- **Time-series data** - Tracks earnings history with timestamps
- **Automatic updates** - Graph refreshes as jobs complete
- **Professional styling** - Matches WattCoin brand colors

**Powered by matplotlib** - Install with: `pip install matplotlib`

### **4. Enhanced Dashboard**
- **Jobs Completed** - Total jobs processed
- **WATT Earned** - Total earnings from all jobs
- **Wallet Balance** - Current WATT balance (live fetch)
- **Color-coded stats** - Green accent for positive metrics

### **5. Job History Table**
- **Complete history** - Last 100 jobs with details
- **Scrollable view** - Easy to browse past jobs
- **Details shown:**
  - Timestamp (when job completed)
  - Job type (scrape, inference, etc.)
  - WATT earned for that job
- **Persistent storage** - History saved to disk

### **6. Persistent Data**
- **Config file** - `wattnode_config.json` stores settings
- **History file** - `wattnode_history.json` stores job records
- **Auto-save** - All data saved automatically

---

## 🔧 Technical Improvements

### **Better Threading**
- Background stats updater (fetches balance every 30 seconds)
- Non-blocking UI updates
- Thread-safe job completion handling

### **Data Management**
- Deque-based history (efficient memory usage)
- Limited to 100 entries per type
- JSON serialization for persistence

### **Error Handling**
- Graceful fallbacks if matplotlib not installed
- Network request timeouts
- Config validation before starting

---

## 📦 New Dependencies

**Required:**
- `requests>=2.31.0`
- `pillow>=10.0.0`

**Optional (for graphs):**
- `matplotlib>=3.7.0`

**Install all:**
```bash
pip install -r requirements_gui.txt
```

---

## 🎨 UI/UX Improvements

### **Visual Enhancements:**
- Larger window (700x650, was 480x620)
- Resizable window with minimum size constraints
- Better spacing and padding
- Tab navigation for organized features
- Status indicator in header (always visible)

### **Color Consistency:**
- Background: #0f0f0f (near black)
- Surface: #1a1a1a (dark gray)
- Borders: #2a2a2a (medium gray)
- Text: #ffffff (white)
- Accent: #39ff14 (neon green) - matches wattcoin.org
- Error: #ff4444 (red)

---

## 📝 Usage Guide

### **Getting Started:**
1. **Settings Tab** - Configure wallet and node name
2. **Settings Tab** - Adjust CPU allocation (default 50%)
3. **Dashboard** - View your stats
4. **Start Node** - Click green button at bottom

### **Monitoring:**
- **Dashboard Tab** - See real-time earnings graph
- **History Tab** - Review completed jobs
- **Status Indicator** - Check if node is running (top right)

### **CPU Allocation Recommendations:**
- **25%** - Light use, background operation
- **50%** - Balanced, recommended for daily use
- **75%** - High performance, occasional slowdown
- **100%** - Maximum earnings, dedicated node

---

## 🐛 Bug Fixes

- Fixed stats syncing on startup
- Improved error handling for API failures
- Better config validation
- Thread-safe UI updates

---

## 🚀 What's Next (Planned for v2.1)

- **System tray icon** - Minimize to tray
- **Desktop notifications** - Toast when job completes
- **Auto-start** - Launch with Windows
- **Export history** - Download as CSV
- **Performance metrics** - Jobs/hour, avg response time
- **Network stats** - Total nodes online, jobs in queue

---

## 📄 Upgrade Instructions

**From v1.0 to v2.0:**

1. **Backup your config:**
   ```bash
   copy wattnode_config.json wattnode_config.json.backup
   ```

2. **Install dependencies:**
   ```bash
   pip install matplotlib
   ```

3. **Replace the file:**
   - Download `wattnode_gui_v2.py`
   - Rename to `wattnode_gui.py`
   - Or run directly: `python wattnode_gui_v2.py`

4. **Your data will migrate automatically:**
   - Config settings preserved
   - Node ID maintained
   - Previous stats synced from backend

**Note:** Job history from v1.0 won't be imported (fresh start for history feature)

---

## 💡 Tips & Tricks

**Maximize Earnings:**
- Run 24/7 for consistent income
- Allocate more CPU (75-100%)
- Keep internet connection stable
- Check history tab to see which jobs pay best

**Monitor Performance:**
- Watch earnings graph for trends
- Check history for job frequency
- Balance CPU allocation vs system performance

**Troubleshooting:**
- If graph doesn't show: `pip install matplotlib`
- If stats don't update: Check network connection
- If node won't start: Verify registration completed

---

## 🙏 Feedback Welcome!

Found a bug? Have a feature request? 
- GitHub Issues: https://github.com/WattCoin-Org/wattcoin/issues
- Tag with `wattnode` and `gui`

---

**Version:** 2.0.0  
**Release Date:** February 5, 2026  
**Compatibility:** Windows 10/11, Python 3.9+
