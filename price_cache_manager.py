#!/usr/bin/env python3
"""
Price Cache Manager - Historical Price Data Cache System

Manages historical price data to fill gaps in current CSV data.
Implements expiration validation to ensure cached data is still relevant.

Cache location: .cache/price_cache/{instrument}.json
"""

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
            'ny_range_high', 'ny_range_low', 'previous_hourly',
            'weekly_high', 'weekly_low', 'prev_week_high', 'prev_week_low'
        ]

        for level_name in cacheable_levels:
            if level_name in levels_dict and levels_dict[level_name] is not None:
                cache['cached_levels'][level_name] = {
                    'price': float(levels_dict[level_name]),
                    'timestamp': current_timestamp.isoformat(),
                    'data_date': current_timestamp.date().isoformat(),
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

        elif level_name == 'previous_hourly':
            # Previous hourly expires 1 hour after it was recorded
            if time_diff <= timedelta(hours=1):
                return True, "previous_hourly still valid (within 1 hour)"
            return False, "previous_hourly expired (more than 1 hour old)"

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

        elif level_name == 'ny_preopen':
            cached_date = cached_time.date()
            current_date = current_time.date()
            if cached_date == current_date:
                return True, f"ny_preopen still valid (same day as record: {cached_date})"
            return False, f"ny_preopen expired (recorded {cached_date}, now {current_date})"

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

        elif level_name in ['weekly_high', 'weekly_low']:
            cached_week_start = cached_time - timedelta(days=cached_time.weekday())
            current_week_start = current_time - timedelta(days=current_time.weekday())
            if cached_week_start == current_week_start:
                return True, f"weekly level still valid (same week)"
            return False, f"weekly level expired (different week)"

        # Previous week levels
        elif level_name in ['prev_week_high', 'prev_week_low']:
            cached_week_start = cached_time - timedelta(days=cached_time.weekday())
            current_week_start = current_time - timedelta(days=current_time.weekday())
            prev_week_start = current_week_start - timedelta(weeks=1)
            if cached_week_start == prev_week_start:
                return True, f"prev_week level valid (recorded in previous week)"
            return False, f"prev_week level expired"

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

        Returns:
            Number of entries removed
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

    def clear_cache(self):
        """
        Clear all cached data for this instrument.

        Returns:
            Number of entries removed
        """
        cache = self.load_cache()
        num_entries = len(cache['cached_levels'])
        self.save_cache(self._create_empty_cache())
        return num_entries
