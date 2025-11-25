# Data Gap Remediation Strategy: Historical Price Cache with Expiration Validation

## Problem Statement

The current script fails silently when CSV data has gaps or is insufficient to calculate reference price levels for all required time periods. For example:

**Current Behavior:**
- User provides 1-minute data for only the last 1 hour (14:00-15:00 ET)
- Script needs 4-hour open (10:00 ET), but data only goes back to 14:00
- **Result:** Script falls back to earliest available candle (14:00) and uses it as "4-hour open" - **INCORRECT**
- User is not warned that the reference price is wrong

**Desired Behavior:**
- If current CSV doesn't have 4-hour open price, check if user previously provided data containing that historical price
- If historical data exists AND hasn't expired, use it as the reference price
- Only skip the reference level if no valid historical data exists

---

## Solution Architecture

### Core Concept: Historical Price Cache + Expiration Logic

```
┌─────────────────────────────────────────────────────────────┐
│                    User Provides CSV                         │
│                  (14:00-15:00 ET data)                      │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │  Extract Reference Levels          │
        │  (4h_open, 2h_open, daily, etc)   │
        └────────────────┬───────────────────┘
                         │
         ┌───────────────┴────────────────┐
         │                                │
         ▼                                ▼
    ┌─────────────┐          ┌──────────────────────┐
    │ Found in    │          │ Not found in         │
    │ Current CSV │          │ Current CSV          │
    │ = USE IT    │          │ = CHECK CACHE        │
    └─────────────┘          └──────────────┬───────┘
                                            │
                                 ┌──────────┴─────────┐
                                 │                    │
                                 ▼                    ▼
                         ┌────────────────┐   ┌──────────────┐
                         │ Cache hit &    │   │ Not in cache │
                         │ Not expired    │   │ = SKIP LEVEL │
                         │ = USE CACHED   │   └──────────────┘
                         └────────────────┘
```

---

## Implementation Steps

### Phase 1: Create Historical Price Cache System

#### Step 1.1: Design Cache Data Structure

Create a new file: `price_cache_manager.py`

**Cache Storage Format (JSON):**
```json
{
  "instrument": "US100",
  "cached_levels": {
    "4h_open": {
      "price": 24500.50,
      "timestamp": "2025-11-24T10:00:00-05:00",
      "data_date": "2025-11-24",
      "last_accessed": "2025-11-25T15:30:00-05:00"
    },
    "2h_open": {
      "price": 24505.25,
      "timestamp": "2025-11-25T12:00:00-05:00",
      "data_date": "2025-11-25",
      "last_accessed": "2025-11-25T15:30:00-05:00"
    },
    "daily_midnight": {
      "price": 24480.00,
      "timestamp": "2025-11-25T00:00:00-05:00",
      "data_date": "2025-11-25",
      "last_accessed": "2025-11-25T15:30:00-05:00"
    },
    "weekly_open": {
      "price": 24200.00,
      "timestamp": "2025-11-24T00:00:00-05:00",
      "data_date": "2025-11-24",
      "last_accessed": "2025-11-25T15:30:00-05:00"
    },
    "monthly_open": {
      "price": 24100.75,
      "timestamp": "2025-11-01T00:00:00-05:00",
      "data_date": "2025-11-01",
      "last_accessed": "2025-11-25T15:30:00-05:00"
    },
    "ny_open": {
      "price": 24510.00,
      "timestamp": "2025-11-25T09:30:00-05:00",
      "data_date": "2025-11-25",
      "last_accessed": "2025-11-25T15:30:00-05:00"
    }
  }
}
```

**Key Fields:**
- `price`: The reference price value
- `timestamp`: When this price occurred (in instrument's timezone)
- `data_date`: The calendar date the price is from
- `last_accessed`: When this cached price was last used (for cleanup)

#### Step 1.2: Create Cache Manager Class

**File: `price_cache_manager.py`**

```python
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from pathlib import Path
import pytz

class PriceCacheManager:
    """
    Manages historical price data cache to fill gaps in current CSV data.

    Cache location: .cache/price_cache/{instrument}.json
    """

    def __init__(self, instrument: str, timezone_str: str):
        """
        Initialize cache manager.

        Args:
            instrument: 'US100', 'ES', 'UK100', etc.
            timezone_str: 'America/New_York', 'America/Chicago', etc.
        """
        self.instrument = instrument
        self.timezone = pytz.timezone(timezone_str)
        self.cache_dir = Path('.cache/price_cache')
        self.cache_file = self.cache_dir / f'{instrument}_cache.json'
        self._ensure_cache_dir()

    def _ensure_cache_dir(self):
        """Create cache directory if it doesn't exist."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load_cache(self) -> Dict:
        """Load cache from disk."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return self._create_empty_cache()
        return self._create_empty_cache()

    def save_cache(self, cache: Dict):
        """Save cache to disk."""
        with open(self.cache_file, 'w') as f:
            json.dump(cache, f, indent=2)

    def _create_empty_cache(self) -> Dict:
        """Create empty cache structure."""
        return {
            'instrument': self.instrument,
            'cached_levels': {}
        }

    def update_cache(self, levels_dict: Dict, current_timestamp: datetime):
        """
        Update cache with newly extracted levels from current CSV.

        Args:
            levels_dict: Dictionary with level_name -> price mappings
            current_timestamp: Current time when data was extracted
        """
        cache = self.load_cache()

        # List of levels that should be cached as historical references
        cacheable_levels = [
            '4h_open', '2h_open', 'daily_midnight', 'ny_open',
            'weekly_open', 'monthly_open', 'prev_day_high', 'prev_day_low',
            'ny_preopen', 'asian_range_high', 'asian_range_low',
            'london_range_high', 'london_range_low',
            'ny_range_high', 'ny_range_low'
        ]

        for level_name in cacheable_levels:
            if level_name in levels_dict and levels_dict[level_name] is not None:
                # Extract timestamp from levels_dict (should be datetime object)
                level_timestamp = getattr(levels_dict, 'timestamp', current_timestamp)

                cache['cached_levels'][level_name] = {
                    'price': float(levels_dict[level_name]),
                    'timestamp': level_timestamp.isoformat(),
                    'data_date': level_timestamp.date().isoformat(),
                    'last_accessed': current_timestamp.isoformat()
                }

        self.save_cache(cache)

    def get_cached_price(self, level_name: str, current_time: datetime) -> Tuple[Optional[float], bool, str]:
        """
        Get cached price for a level if it exists and hasn't expired.

        Args:
            level_name: Name of the reference level
            current_time: Current time to check expiration

        Returns:
            Tuple of (price, is_valid, reason)
            - price: The cached price or None
            - is_valid: Whether the cached price is still valid
            - reason: Explanation for validity decision
        """
        cache = self.load_cache()

        if level_name not in cache['cached_levels']:
            return None, False, f"No cached data for {level_name}"

        cached_entry = cache['cached_levels'][level_name]
        price = cached_entry['price']
        cached_timestamp = datetime.fromisoformat(cached_entry['timestamp'])

        # Check if cached data has expired
        is_valid, reason = self._check_expiration(level_name, cached_timestamp, current_time)

        if is_valid:
            # Update last_accessed timestamp
            cached_entry['last_accessed'] = current_time.isoformat()
            self.save_cache(cache)

        return price if is_valid else None, is_valid, reason

    def _check_expiration(self, level_name: str, cached_time: datetime, current_time: datetime) -> Tuple[bool, str]:
        """
        Check if cached price has expired based on level type.

        Expiration Rules:
        - 4h_open: Expires when we pass 4 hours from the reference time
        - 2h_open: Expires when we pass 2 hours from the reference time
        - daily_midnight: Expires at next midnight
        - ny_open: Expires at next market open (9:30 AM)
        - weekly_open: Expires at next Monday
        - monthly_open: Expires at next month's 1st
        - Range highs/lows (asian, london, ny): Expires when range ends

        Args:
            level_name: Name of the reference level
            cached_time: When the price was recorded
            current_time: Current time

        Returns:
            Tuple of (is_valid, reason)
        """
        time_diff = current_time - cached_time

        # Intraday levels - expire after their period
        if level_name == '4h_open':
            # 4-hour open expires 4 hours after it was recorded
            if time_diff <= timedelta(hours=4):
                return True, "4h_open still valid (within 4 hours)"
            return False, "4h_open expired (more than 4 hours old)"

        elif level_name == '2h_open':
            # 2-hour open expires 2 hours after it was recorded
            if time_diff <= timedelta(hours=2):
                return True, "2h_open still valid (within 2 hours)"
            return False, "2h_open expired (more than 2 hours old)"

        # Daily levels - expire at next midnight
        elif level_name == 'daily_midnight':
            cached_date = cached_time.date()
            current_date = current_time.date()
            if cached_date == current_date:
                return True, f"daily_midnight still valid (same day as record: {cached_date})"
            return False, f"daily_midnight expired (recorded {cached_date}, now {current_date})"

        elif level_name == 'ny_open':
            cached_date = cached_time.date()
            current_date = current_time.date()
            if cached_date == current_date:
                return True, f"ny_open still valid (same day as record: {cached_date})"
            return False, f"ny_open expired (recorded {cached_date}, now {current_date})"

        # Previous day levels - valid if recorded yesterday
        elif level_name in ['prev_day_high', 'prev_day_low']:
            cached_date = cached_time.date()
            yesterday = (current_time - timedelta(days=1)).date()
            if cached_date == yesterday:
                return True, f"prev_day level valid (recorded {cached_date})"
            return False, f"prev_day level expired (recorded {cached_date}, yesterday was {yesterday})"

        # Weekly levels - expire at next Monday
        elif level_name == 'weekly_open':
            cached_week_start = cached_time - timedelta(days=cached_time.weekday())
            current_week_start = current_time - timedelta(days=current_time.weekday())
            if cached_week_start == current_week_start:
                return True, f"weekly_open still valid (same week)"
            return False, f"weekly_open expired (different week)"

        # Monthly levels - expire on 1st of next month
        elif level_name == 'monthly_open':
            if cached_time.month == current_time.month and cached_time.year == current_time.year:
                return True, f"monthly_open still valid (same month)"
            return False, f"monthly_open expired (different month)"

        # Range levels - expire when range ends
        elif level_name in ['asian_range_high', 'asian_range_low']:
            # Asian range: 20:00 previous day to 00:00 ET (midnight)
            # Expires at midnight
            cached_date = cached_time.date()
            current_date = current_time.date()
            if cached_date == current_date and current_time.hour < 1:
                return True, "asian_range still valid (before 1:00 AM ET)"
            return False, "asian_range expired"

        elif level_name in ['london_range_high', 'london_range_low']:
            # London range: 03:00 - 11:00 ET
            # Expires after 11:00 AM ET
            cached_date = cached_time.date()
            current_date = current_time.date()
            if cached_date == current_date and current_time.hour < 11:
                return True, "london_range still valid (before 11:00 AM ET)"
            return False, "london_range expired"

        elif level_name in ['ny_range_high', 'ny_range_low']:
            # NY range: 09:30 - 14:00 ET
            # Expires after 2:00 PM ET (14:00)
            cached_date = cached_time.date()
            current_date = current_time.date()
            if cached_date == current_date and current_time.hour < 14:
                return True, "ny_range still valid (before 2:00 PM ET)"
            return False, "ny_range expired"

        # Default: data expires after 7 days
        if time_diff <= timedelta(days=7):
            return True, f"Cached within last 7 days"
        return False, f"Cached data older than 7 days"

    def cleanup_old_cache(self, days_threshold: int = 30):
        """
        Remove cache entries older than threshold.

        Args:
            days_threshold: Remove entries not accessed in this many days
        """
        cache = self.load_cache()
        current_time = datetime.now(self.timezone)
        cutoff_time = current_time - timedelta(days=days_threshold)

        levels_to_remove = []
        for level_name, entry in cache['cached_levels'].items():
            last_accessed = datetime.fromisoformat(entry['last_accessed'])
            if last_accessed < cutoff_time:
                levels_to_remove.append(level_name)

        for level_name in levels_to_remove:
            del cache['cached_levels'][level_name]

        if levels_to_remove:
            self.save_cache(cache)

        return len(levels_to_remove)
```

---

### Phase 2: Integrate Cache into Prediction Model

#### Step 2.1: Modify `prediction_model_v3.py`

Update the `_calculate_levels()` method to use cache as fallback:

```python
# In prediction_model_v3.py, modify the __init__ method to initialize cache manager

from price_cache_manager import PriceCacheManager

class PredictionModelV3:
    def __init__(self, df, instrument='US100', timezone_str='America/New_York'):
        self.df = df
        self.instrument = instrument
        self.timezone = pytz.timezone(timezone_str)

        # Initialize cache manager
        self.cache_manager = PriceCacheManager(instrument, timezone_str)

        # ... rest of initialization
```

#### Step 2.2: Modify Level Calculation with Cache Fallback

```python
def _calculate_levels(self, df):
    """
    Calculate reference price levels.
    Use cache as fallback when current data doesn't contain required time periods.
    """
    levels_dict = {}
    opens = df['open']
    current_time = df.index[-1]  # Latest timestamp in data

    # ===== 4-HOUR OPEN =====
    if len(opens) > 240:
        # We have 4+ hours of data
        levels_dict['4h_open'] = opens.iloc[-240]
        source_4h = "CURRENT_DATA"
    else:
        # Not enough data - try cache
        cached_price, is_valid, reason = self.cache_manager.get_cached_price('4h_open', current_time)
        if cached_price is not None and is_valid:
            levels_dict['4h_open'] = cached_price
            source_4h = f"CACHE ({reason})"
        else:
            # No valid cache either
            levels_dict['4h_open'] = None
            source_4h = f"UNAVAILABLE ({reason})"

    # ===== 2-HOUR OPEN =====
    if len(opens) > 120:
        levels_dict['2h_open'] = opens.iloc[-120]
        source_2h = "CURRENT_DATA"
    else:
        cached_price, is_valid, reason = self.cache_manager.get_cached_price('2h_open', current_time)
        if cached_price is not None and is_valid:
            levels_dict['2h_open'] = cached_price
            source_2h = f"CACHE ({reason})"
        else:
            levels_dict['2h_open'] = None
            source_2h = f"UNAVAILABLE ({reason})"

    # ===== DAILY MIDNIGHT =====
    midnight_start = pd.Timestamp(current_time.date(), tz=self.timezone)
    today_data = df[df.index >= midnight_start]

    if len(today_data) > 0:
        levels_dict['daily_midnight'] = today_data['open'].iloc[0]
        source_midnight = "CURRENT_DATA"
    else:
        cached_price, is_valid, reason = self.cache_manager.get_cached_price('daily_midnight', current_time)
        if cached_price is not None and is_valid:
            levels_dict['daily_midnight'] = cached_price
            source_midnight = f"CACHE ({reason})"
        else:
            levels_dict['daily_midnight'] = None
            source_midnight = f"UNAVAILABLE ({reason})"

    # ... Continue for all other levels with same pattern ...

    # Store sources for transparency
    self.level_sources = {
        '4h_open': source_4h,
        '2h_open': source_2h,
        'daily_midnight': source_midnight,
        # ... etc
    }

    # Filter out None values
    levels_dict = {k: v for k, v in levels_dict.items() if v is not None}

    return levels_dict
```

#### Step 2.3: Update Cache After Successful Level Calculation

```python
def calculate(self, current_price: float) -> Dict:
    """
    Main calculation method - returns prediction with bias and confidence.
    Now also updates cache after calculation.
    """
    # Calculate levels
    levels_dict = self._calculate_levels(self.df)

    # Update cache with newly extracted data
    current_time = self.df.index[-1]
    self.cache_manager.update_cache(levels_dict, current_time)

    # ... rest of calculation logic ...

    return {
        'bias': prediction_bias,
        'confidence': confidence_score,
        'level_sources': self.level_sources,  # NEW: Include source info
        'levels': levels_dict
    }
```

---

### Phase 3: Update UI to Show Data Sources

#### Step 3.1: Modify `app.py` to Display Cache Status

```python
# In app.py, update the results display section

def display_results(prediction_result, levels_dict):
    """Display prediction results with data source transparency."""

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("📊 Bias", prediction_result['bias'])
    with col2:
        st.metric("💯 Confidence", f"{prediction_result['confidence']:.1f}%")
    with col3:
        st.metric("📈 Available Levels", len(levels_dict))

    # NEW: Show data sources for each level
    st.subheader("📋 Reference Level Sources")

    sources = prediction_result.get('level_sources', {})

    col_level, col_price, col_source = st.columns(3)
    col_level.write("**Level**")
    col_price.write("**Price**")
    col_source.write("**Source**")

    for level_name, price in levels_dict.items():
        source = sources.get(level_name, "UNKNOWN")

        # Color-code by source
        if "CURRENT_DATA" in source:
            color = "🟢"  # Green: from current CSV
        elif "CACHE" in source:
            color = "🟡"  # Yellow: from historical cache
        else:
            color = "🔴"  # Red: unavailable

        col_level.write(f"{color} {level_name}")
        col_price.write(f"{price:.2f}")
        col_source.write(source)
```

---

### Phase 4: Create Data Validation & Reporting Module

#### Step 4.1: Create `data_quality_report.py`

```python
from datetime import datetime
from typing import Dict, List
import pytz

class DataQualityReport:
    """Generate reports on data completeness and cache usage."""

    def __init__(self, instrument: str, timezone_str: str):
        self.instrument = instrument
        self.timezone = pytz.timezone(timezone_str)
        self.issues = []
        self.warnings = []
        self.info = []

    def analyze_data_coverage(self, df, expected_levels: List[str], actual_sources: Dict[str, str]):
        """Analyze what data is available vs. what's expected."""

        total_levels = len(expected_levels)
        sourced_levels = len([s for s in actual_sources.values() if s != 'UNAVAILABLE'])
        coverage_percent = (sourced_levels / total_levels * 100) if total_levels > 0 else 0

        self.info.append({
            'message': f'Reference Level Coverage: {sourced_levels}/{total_levels} ({coverage_percent:.1f}%)',
            'severity': 'info'
        })

        # Count sources
        current_data_count = sum(1 for s in actual_sources.values() if 'CURRENT_DATA' in s)
        cache_count = sum(1 for s in actual_sources.values() if 'CACHE' in s)
        unavailable_count = sum(1 for s in actual_sources.values() if 'UNAVAILABLE' in s)

        self.info.append({
            'message': f'Data Sources: {current_data_count} from current CSV, {cache_count} from cache, {unavailable_count} unavailable',
            'severity': 'info'
        })

        # Warn if coverage is low
        if coverage_percent < 70:
            self.warnings.append({
                'message': f'Low level coverage ({coverage_percent:.1f}%). Analysis may be less reliable.',
                'severity': 'warning'
            })

        # Check for critical missing levels
        critical_levels = ['daily_midnight', 'ny_open', '4h_open', '2h_open']
        missing_critical = [level for level in critical_levels
                          if actual_sources.get(level, '').startswith('UNAVAILABLE')]
        if missing_critical:
            self.warnings.append({
                'message': f'Missing critical levels: {", ".join(missing_critical)}',
                'severity': 'warning'
            })

    def check_cache_age(self, cache_entries: Dict):
        """Check if cached entries are fresh."""
        current_time = datetime.now(self.timezone)

        old_entries = []
        for level_name, entry in cache_entries.items():
            last_accessed = datetime.fromisoformat(entry['last_accessed'])
            age_days = (current_time - last_accessed).days

            if age_days > 7:
                old_entries.append(f"{level_name} (unused for {age_days} days)")

        if old_entries:
            self.info.append({
                'message': f'Stale cache entries (consider cleanup): {", ".join(old_entries)}',
                'severity': 'info'
            })

    def generate_report(self) -> str:
        """Generate human-readable report."""
        report = f"\n{'='*60}\n"
        report += f"DATA QUALITY REPORT - {self.instrument}\n"
        report += f"Generated: {datetime.now(self.timezone).isoformat()}\n"
        report += f"{'='*60}\n\n"

        if self.issues:
            report += "🔴 ISSUES:\n"
            for issue in self.issues:
                report += f"  - {issue['message']}\n"
            report += "\n"

        if self.warnings:
            report += "🟡 WARNINGS:\n"
            for warning in self.warnings:
                report += f"  - {warning['message']}\n"
            report += "\n"

        if self.info:
            report += "ℹ️  INFO:\n"
            for info in self.info:
                report += f"  - {info['message']}\n"
            report += "\n"

        report += f"{'='*60}\n"
        return report
```

---

### Phase 5: Update Extract and Analyze Module

#### Step 5.1: Modify `extract_and_analyze.py`

```python
# Add to ExtractorAnalyzer class

def prepare_data_with_cache_fallback(self, cache_manager):
    """
    Prepare data, and set up cache manager reference.
    """
    self.cache_manager = cache_manager
    self.load_and_parse()
    return self.df

# Add method to get data quality info
def get_data_quality_info(self):
    """Return information about data coverage."""
    return {
        'total_rows': len(self.df),
        'time_range': f"{self.df.index[0]} to {self.df.index[-1]}",
        'duration_hours': (self.df.index[-1] - self.df.index[0]).total_seconds() / 3600,
        'has_gaps': not self._check_continuity(),
        'timezone': self.timezone.zone
    }

def _check_continuity(self) -> bool:
    """Check if data is continuous (no gaps)."""
    # Assuming 1-minute data
    time_diffs = self.df.index.to_series().diff()
    expected_diff = pd.Timedelta(minutes=1)
    gaps = (time_diffs != expected_diff).sum()
    return gaps == 0  # Only the first NaT difference
```

---

### Phase 6: Update Streamlit App to Show Cache Management

#### Step 6.1: Add Cache Management UI Section

```python
# In app.py, add new section for cache management

import streamlit as st
from price_cache_manager import PriceCacheManager

def show_cache_management_section():
    """Display cache management controls."""
    with st.sidebar:
        st.subheader("🗄️ Cache Management")

        cache_manager = PriceCacheManager(selected_instrument, timezone_mapping[selected_instrument])

        col1, col2 = st.columns(2)

        with col1:
            if st.button("📊 View Cache"):
                cache = cache_manager.load_cache()
                st.json(cache)

        with col2:
            if st.button("🗑️ Clear Old Cache"):
                removed = cache_manager.cleanup_old_cache(days_threshold=30)
                st.success(f"Removed {removed} old cache entries")

        # Cache stats
        cache = cache_manager.load_cache()
        num_cached = len(cache['cached_levels'])
        st.info(f"Currently caching: {num_cached} reference levels")
```

---

## Expiration Rules (Comprehensive)

### Time-Based Expiration Logic

| Level Name | Expires When | Max Age | Notes |
|-----------|-------------|---------|-------|
| `4h_open` | 4 hours after recorded time | 4 hours | Intraday: Only valid for current 4-hour period |
| `2h_open` | 2 hours after recorded time | 2 hours | Intraday: Only valid for current 2-hour period |
| `daily_midnight` | At next midnight ET | 1 day | Valid only for the day it was recorded |
| `ny_open` | At next market day start | 1 day | Valid only for the trading day recorded |
| `ny_preopen` | At next market day start | 1 day | Valid only for the day recorded |
| `prev_day_high` | At next midnight ET | 1 day | Only valid for "previous day" reference |
| `prev_day_low` | At next midnight ET | 1 day | Only valid for "previous day" reference |
| `weekly_open` | At next Monday 00:00 ET | 7 days | Valid for current week only |
| `weekly_high` | At next Monday 00:00 ET | 7 days | Valid for current week only |
| `weekly_low` | At next Monday 00:00 ET | 7 days | Valid for current week only |
| `prev_week_high` | At next Monday 00:00 ET | 14 days | Only valid for "previous week" reference |
| `prev_week_low` | At next Monday 00:00 ET | 14 days | Only valid for "previous week" reference |
| `monthly_open` | At next month 1st 00:00 ET | 30 days | Valid for current month only |
| `asian_range_high` | At 01:00 AM ET | 1 day | Range: 20:00 prev day - 00:00 ET |
| `asian_range_low` | At 01:00 AM ET | 1 day | Range: 20:00 prev day - 00:00 ET |
| `london_range_high` | At 11:00 AM ET | 1 day | Range: 03:00 - 11:00 ET |
| `london_range_low` | At 11:00 AM ET | 1 day | Range: 03:00 - 11:00 ET |
| `ny_range_high` | At 2:00 PM ET (14:00) | 1 day | Range: 09:30 - 14:00 ET |
| `ny_range_low` | At 2:00 PM ET (14:00) | 1 day | Range: 09:30 - 14:00 ET |

---

## Implementation Checklist

- [ ] **Phase 1: Cache System**
  - [ ] Create `price_cache_manager.py`
  - [ ] Design cache JSON structure
  - [ ] Implement `PriceCacheManager` class
  - [ ] Test cache read/write operations
  - [ ] Implement expiration logic for all 20 levels

- [ ] **Phase 2: Integration**
  - [ ] Update `prediction_model_v3.py` to initialize cache manager
  - [ ] Modify `_calculate_levels()` to use cache fallback
  - [ ] Add level source tracking
  - [ ] Update `calculate()` to update cache after processing
  - [ ] Test cache fallback logic

- [ ] **Phase 3: UI Updates**
  - [ ] Update `app.py` to display level sources
  - [ ] Add color-coding for source types (current vs cache vs unavailable)
  - [ ] Show confidence/reliability indicators

- [ ] **Phase 4: Quality Reporting**
  - [ ] Create `data_quality_report.py`
  - [ ] Add coverage analysis
  - [ ] Add cache age checking
  - [ ] Generate quality reports in UI

- [ ] **Phase 5: Data Module Updates**
  - [ ] Modify `extract_and_analyze.py` to work with cache
  - [ ] Add data continuity checks
  - [ ] Add data quality info retrieval

- [ ] **Phase 6: UI Cache Management**
  - [ ] Add sidebar controls for cache viewing
  - [ ] Add cache cleanup button
  - [ ] Show cache statistics

- [ ] **Testing**
  - [ ] Test gap handling with partial data (1 hour only)
  - [ ] Test cache fallback for missing levels
  - [ ] Test expiration logic for all level types
  - [ ] Test cache cleanup
  - [ ] Test concurrent user scenarios
  - [ ] Verify no stale data is used after expiration

- [ ] **Documentation**
  - [ ] Update README with cache behavior explanation
  - [ ] Add cache troubleshooting guide
  - [ ] Document expiration rules for users

---

## Testing Scenarios

### Scenario 1: Insufficient Current Data
```
Input: 1-minute CSV with only last 1 hour (14:00-15:00 ET)
Expected Output:
  ✓ 4h_open: Uses cached value from 10:00 AM (if available & not expired)
  ✓ 2h_open: Uses cached value from 12:00 PM (if available & not expired)
  ✓ daily_midnight: Uses cached value from 00:00 (if same day & not expired)
  ✗ ny_open: Unavailable (no cache from morning session)
```

### Scenario 2: Expired Cache
```
Input: Data from Monday, but now it's Wednesday with 1-hour current data
Expected Output:
  ✓ 4h_open: Uses cache from today if available
  ✗ weekly_open: Cache from Monday is expired (different week)
  ✗ prev_day_high: Cache from Monday is too old
```

### Scenario 3: Valid Cache Usage
```
Input: Friday 15:30 ET, last 1 hour CSV + previous cache from Friday 10:00 AM
Expected Output:
  ✓ 4h_open: Uses cache from 10:00 AM (recorded Friday, still same day)
  ✓ daily_midnight: Uses cache from Friday midnight (still valid)
  ✓ weekly_open: Uses cache from Monday (still same week)
```

---

## Benefits

1. **Eliminates Silent Failures**: No more using wrong fallback prices without warning
2. **Preserves Historical Context**: Old CSV data is reused intelligently when current data has gaps
3. **Transparent to User**: Clear indication of which prices come from cache vs. current data
4. **Time-Aware Validation**: Cache respects expiration windows (don't use Monday's data on Thursday)
5. **Graceful Degradation**: System still works with incomplete data, but users know why
6. **Audit Trail**: Data sources tracked for every reference level
7. **Automatic Cleanup**: Old cache automatically removed after threshold

---

## Example User Experience

**User provides:** 1-hour 1-minute data (14:00-15:00 ET)

**System behavior:**
```
📋 Reference Level Sources
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 4h_open          24500.50     CURRENT_DATA
🟡 2h_open          24505.25     CACHE (2h_open still valid - within 2 hours)
🟢 daily_midnight   24480.00     CURRENT_DATA
🟡 ny_open          24510.00     CACHE (ny_open still valid - same day)
🟡 weekly_open      24200.00     CACHE (weekly_open still valid - same week)
🟡 monthly_open     24100.75     CACHE (monthly_open still valid - same month)
🔴 asian_range_high UNAVAILABLE  (no historical data & expired)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🟢 = From current CSV  |  🟡 = From cache (validated)  |  🔴 = Not available

✓ Reference Level Coverage: 18/20 (90%)
✓ Data quality: Good - Most levels sourced from valid data
```

---

## File Changes Summary

**New Files:**
- `price_cache_manager.py` - Core cache management
- `data_quality_report.py` - Quality reporting

**Modified Files:**
- `prediction_model_v3.py` - Add cache integration
- `app.py` - Add UI for sources and cache management
- `extract_and_analyze.py` - Add data quality checks

**Configuration:**
- `.cache/price_cache/{instrument}.json` - Cache storage location

