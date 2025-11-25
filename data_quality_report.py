#!/usr/bin/env python3
"""
Data Quality Report Generator

Analyzes data completeness and cache usage to provide transparency about
the quality of prediction inputs.
"""

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
        """
        Analyze what data is available vs. what's expected.

        Args:
            df: DataFrame with price data
            expected_levels: List of expected reference levels
            actual_sources: Dictionary mapping level names to their sources
        """
        total_levels = len(expected_levels)
        sourced_levels = len([s for s in actual_sources.values() if 'UNAVAILABLE' not in s])
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

        # Analyze data continuity
        if df is not None and len(df) > 1:
            time_diffs = df.index.to_series().diff()
            expected_diff = df.index[1] - df.index[0]
            gaps = (time_diffs != expected_diff).sum() - 1  # Subtract first NaT
            if gaps > 0:
                self.warnings.append({
                    'message': f'Data has {gaps} time gaps (may indicate incomplete data)',
                    'severity': 'warning'
                })

    def check_cache_age(self, cache_entries: Dict):
        """
        Check if cached entries are fresh.

        Args:
            cache_entries: Dictionary of cached level entries
        """
        if not cache_entries:
            return

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

    def check_data_recency(self, df):
        """
        Check how recent the data is.

        Args:
            df: DataFrame with price data
        """
        if df is None or len(df) == 0:
            return

        latest_timestamp = df.index[-1]
        current_time = datetime.now(self.timezone)

        # Handle timezone-aware timestamps
        if hasattr(latest_timestamp, 'tz_localize'):
            if latest_timestamp.tz is None:
                latest_timestamp = latest_timestamp.tz_localize(self.timezone)
        elif not hasattr(latest_timestamp, 'tz'):
            # Convert to timezone-aware if needed
            try:
                latest_timestamp = pytz.timezone(self.timezone).localize(latest_timestamp)
            except:
                pass

        age_minutes = (current_time - latest_timestamp).total_seconds() / 60

        if age_minutes < 5:
            self.info.append({
                'message': f'Data is very fresh (less than 5 minutes old)',
                'severity': 'info'
            })
        elif age_minutes < 60:
            self.info.append({
                'message': f'Data is {int(age_minutes)} minutes old',
                'severity': 'info'
            })
        elif age_minutes > 24 * 60:  # More than 1 day old
            self.warnings.append({
                'message': f'Data is {int(age_minutes / 60)} hours old - may be stale',
                'severity': 'warning'
            })

    def generate_report(self) -> str:
        """
        Generate human-readable report.

        Returns:
            Formatted report string
        """
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
            report += "ℹ️ INFO:\n"
            for info in self.info:
                report += f"  - {info['message']}\n"
            report += "\n"

        report += f"{'='*60}\n"
        return report

    def to_dict(self) -> Dict:
        """
        Convert report to dictionary format for JSON serialization.

        Returns:
            Dictionary representation of the report
        """
        return {
            'instrument': self.instrument,
            'timestamp': datetime.now(self.timezone).isoformat(),
            'issues': self.issues,
            'warnings': self.warnings,
            'info': self.info,
            'summary': {
                'total_issues': len(self.issues),
                'total_warnings': len(self.warnings),
                'total_info': len(self.info),
                'overall_quality': self._calculate_quality_score()
            }
        }

    def _calculate_quality_score(self) -> str:
        """
        Calculate overall data quality score.

        Returns:
            Quality score label (Excellent, Good, Fair, Poor)
        """
        if len(self.issues) > 0:
            return 'Poor'
        elif len(self.warnings) > 2:
            return 'Fair'
        elif len(self.warnings) > 0:
            return 'Good'
        else:
            return 'Excellent'
