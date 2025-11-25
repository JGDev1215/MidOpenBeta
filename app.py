#!/usr/bin/env python3
"""
Financial Prediction Dashboard
Streamlit UI for Prediction Model v3.0

Allows users to:
1. Upload CSV files with OHLCV price data
2. Analyze predictions using the reference level system
3. Visualize results with interactive charts
4. Export predictions as JSON

Enhanced with:
- Data gap remediation using historical price cache
- Reference level source transparency
- Data quality reporting
- Cache management controls
"""

import streamlit as st
import pandas as pd
import json
from datetime import datetime
from pathlib import Path
import traceback
from price_cache_manager import PriceCacheManager
from data_quality_report import DataQualityReport

# Configure page
st.set_page_config(
    page_title="Financial Prediction Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .metric-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        text-align: center;
        margin: 10px 0;
    }
    .bullish {
        color: #00AA00;
        font-weight: bold;
    }
    .bearish {
        color: #FF0000;
        font-weight: bold;
    }
    .neutral {
        color: #FFA500;
        font-weight: bold;
    }
    .main-title {
        font-size: 2.5rem;
        font-weight: bold;
        margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

# Title
st.markdown('<div class="main-title">📊 Financial Prediction Dashboard</div>', unsafe_allow_html=True)
st.markdown("Analyze price data using the Reference Level Prediction System")
st.divider()

# Initialize session state
if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = None
if 'analysis_history' not in st.session_state:
    st.session_state.analysis_history = []

# Sidebar configuration
with st.sidebar:
    st.header("⚙️ Configuration")
    st.markdown("### Analysis Settings")

    analysis_mode = st.radio(
        "Select Analysis Mode",
        ("Upload & Analyze", "View History"),
        help="Choose between analyzing new data or viewing past predictions"
    )

    # Cache Management Section
    st.divider()
    st.markdown("### 🗄️ Cache Management")

    cache_instrument = st.selectbox(
        "Select Instrument for Cache",
        ["US100", "ES", "UK100"],
        help="Manage price cache for a specific instrument"
    )

    timezone_map = {
        'US100': 'America/New_York',
        'ES': 'America/Chicago',
        'UK100': 'Europe/London',
    }

    cache_manager = PriceCacheManager(cache_instrument, timezone_map[cache_instrument])
    cache = cache_manager.load_cache()
    num_cached = len(cache['cached_levels'])

    col1, col2 = st.columns(2)
    with col1:
        if st.button("📊 View Cache", key="view_cache_btn", use_container_width=True):
            with st.expander(f"Cache for {cache_instrument}"):
                if num_cached > 0:
                    st.json(cache)
                else:
                    st.info("Cache is empty")

    with col2:
        if st.button("🗑️ Clear Old", key="cleanup_cache_btn", use_container_width=True):
            removed = cache_manager.cleanup_old_cache(days_threshold=30)
            st.success(f"Removed {removed} old entries")

    st.metric("Cached Levels", num_cached)

# Main content
if analysis_mode == "Upload & Analyze":
    # File upload section
    st.header("📁 Step 1: Upload CSV File")

    uploaded_file = st.file_uploader(
        "Choose a CSV file with OHLCV data",
        type="csv",
        help="Required columns: time, open, high, low, close"
    )

    if uploaded_file is not None:
        # Load CSV
        df = pd.read_csv(uploaded_file)

        # Validate columns
        required_cols = ['time', 'open', 'high', 'low', 'close']
        missing_cols = set(required_cols) - set(df.columns)

        if missing_cols:
            st.error(f"❌ Missing required columns: {', '.join(missing_cols)}")
            st.info(f"Required columns: {', '.join(required_cols)}")
        else:
            # Show preview
            st.subheader("📊 Data Preview")
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Total candles:** {len(df)}")
                st.write(f"**Columns:** {', '.join(df.columns.tolist())}")
            with col2:
                st.write(f"**File size:** {uploaded_file.size / 1024:.1f} KB")
                st.write(f"**Uploaded:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            with st.expander("View sample data (first 10 rows)"):
                st.dataframe(df.head(10), use_container_width=True)

            # Analyze button
            st.divider()
            st.header("📈 Step 2: Run Analysis")

            if st.button("🔍 Analyze Data", key="analyze_btn", use_container_width=True):
                with st.spinner("Running prediction analysis..."):
                    try:
                        # Import prediction engine
                        from extract_and_analyze import DataExtractor
                        from prediction_model_v3 import PredictionEngine, OutputFormatter

                        # Parse time column
                        df['time'] = pd.to_datetime(df['time'], utc=True)
                        df.set_index('time', inplace=True)

                        # Identify instrument from filename
                        filename = uploaded_file.name
                        instrument = "US100"  # Default

                        if "NQ" in filename.upper():
                            instrument = "US100"
                        elif "ES" in filename.upper():
                            instrument = "ES"
                        elif "UK100" in filename.upper() or "FTSE" in filename.upper():
                            instrument = "UK100"

                        # Get timezone mapping
                        timezone_map = {
                            'US100': 'America/New_York',
                            'ES': 'America/Chicago',
                            'UK100': 'Europe/London',
                        }

                        timezone = timezone_map.get(instrument, 'UTC')

                        # Convert timezone
                        df.index = df.index.tz_convert(timezone)

                        # Get latest timestamp
                        latest_timestamp = str(df.index[-1])

                        # Run prediction
                        engine = PredictionEngine(instrument=instrument)
                        result = engine.analyze(df, latest_timestamp)

                        # Store result
                        st.session_state.analysis_result = {
                            'result': result,
                            'instrument': instrument,
                            'timezone': timezone,
                            'timestamp': datetime.now().isoformat(),
                            'filename': filename,
                            'data_length': len(df),
                            'current_price': df.iloc[-1]['close']
                        }

                        # Add to history
                        st.session_state.analysis_history.append(st.session_state.analysis_result)

                        st.success("✅ Analysis completed successfully!")
                        st.rerun()

                    except Exception as e:
                        st.error(f"❌ Analysis failed: {str(e)}")
                        st.info("💡 Make sure the CSV has the required columns: time, open, high, low, close")
                        with st.expander("Show error details"):
                            st.code(traceback.format_exc())

if analysis_mode == "View History":
    st.header("📜 Analysis History")

    if not st.session_state.analysis_history:
        st.info("No analysis history yet. Upload and analyze a CSV file first.")
    else:
        for idx, item in enumerate(reversed(st.session_state.analysis_history)):
            with st.expander(f"📊 {item['instrument']} - {item['timestamp'][:19]}"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.write(f"**Instrument:** {item['instrument']}")
                with col2:
                    st.write(f"**Candles:** {item['data_length']}")
                with col3:
                    st.write(f"**Price:** ${item['current_price']:.2f}")

                # Show result preview
                result = item['result']
                st.write("**Analysis Result:**")
                st.json(result)


# Display results if available
if st.session_state.analysis_result:
    st.divider()
    st.header("📊 Step 3: Analysis Results")

    result = st.session_state.analysis_result['result']
    instrument = st.session_state.analysis_result['instrument']
    current_price = st.session_state.analysis_result['current_price']

    # Main metrics in columns
    col1, col2, col3, col4 = st.columns(4)

    # Bias
    bias = result['analysis']['bias']
    confidence = result['analysis']['confidence']
    bullish_weight = result['analysis']['bullish_weight']
    bearish_weight = result['analysis']['bearish_weight']

    with col1:
        st.metric(
            label="Directional Bias",
            value=bias,
            delta=f"{confidence:.2f}% confidence"
        )
        if bias == "BULLISH":
            st.markdown('<span class="bullish">▲ BULLISH</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="bearish">▼ BEARISH</span>', unsafe_allow_html=True)

    with col2:
        st.metric(
            label="Confidence Score",
            value=f"{confidence:.2f}%",
            delta="Prediction strength"
        )

    with col3:
        st.metric(
            label="Bullish Weight",
            value=f"{bullish_weight*100:.2f}%",
            delta=f"{bullish_weight*100:.2f}% of signals"
        )

    with col4:
        st.metric(
            label="Bearish Weight",
            value=f"{bearish_weight*100:.2f}%",
            delta=f"{bearish_weight*100:.2f}% of signals"
        )

    st.divider()

    # Metadata section
    st.subheader("📋 Analysis Metadata")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.write(f"**Instrument:** {instrument}")
        st.write(f"**Current Price:** ${current_price:.2f}")

    with col2:
        st.write(f"**Timezone:** {st.session_state.analysis_result['timezone']}")
        st.write(f"**Timestamp:** {result['metadata']['timestamp']}")

    with col3:
        st.write(f"**Available Levels:** {result['weights']['available_levels']}/{result['weights']['total_levels']}")
        st.write(f"**Weight Utilization:** {result['weights']['utilization']*100:.2f}%")

    st.divider()

    # Level sources section
    st.subheader("📋 Reference Level Sources")

    level_sources = result.get('level_sources', {})

    if level_sources:
        # Create source tracking display
        source_cols = st.columns(3)
        with source_cols[0]:
            st.write("**Level**")
        with source_cols[1]:
            st.write("**Price**")
        with source_cols[2]:
            st.write("**Source**")

        for level in result['levels']:
            level_name = level['name']
            source = level_sources.get(level_name, "UNKNOWN")

            # Determine color indicator
            if "CURRENT_DATA" in source:
                indicator = "🟢"  # Green: from current CSV
                status = "Current Data"
            elif "CACHE" in source:
                indicator = "🟡"  # Yellow: from historical cache
                status = "Cached (Validated)"
            else:
                indicator = "🔴"  # Red: unavailable
                status = "Unavailable"

            cols = st.columns(3)
            with cols[0]:
                st.write(f"{indicator} {level_name}")
            with cols[1]:
                st.write(f"${level['price']:.2f}" if level['price'] else "N/A")
            with cols[2]:
                st.write(f"**{status}**")
                st.caption(source)

        st.caption("🟢 = From current CSV  |  🟡 = From cache (validated)  |  🔴 = Not available")

    st.divider()

    # Data Quality Report
    st.subheader("📊 Data Quality Report")

    quality_report = DataQualityReport(instrument, st.session_state.analysis_result['timezone'])

    # Analyze data coverage
    expected_levels = [l['name'] for l in result['levels']]
    quality_report.analyze_data_coverage(
        None,  # We don't need the dataframe for this analysis
        expected_levels,
        level_sources
    )

    # Display report
    quality_text = quality_report.generate_report()
    st.text(quality_text)

    st.divider()

    # Reference levels table
    st.subheader("📊 Reference Levels (20)")

    # Convert levels to dataframe for display
    levels_data = []
    for level in result['levels']:
        distance = level['distance_percent'] if level['distance_percent'] is not None else 0.0
        levels_data.append({
            'Level Name': level['name'].replace('_', ' ').title(),
            'Price': f"${level['price']:.2f}",
            'Distance (%)': f"{distance:.3f}%",
            'Position': level['position'],
            'Depreciation': f"{level['depreciation']:.3f}",
            'Effective Weight': f"{level['effective_weight']:.4f}"
        })

    levels_df = pd.DataFrame(levels_data)
    st.dataframe(levels_df, use_container_width=True, hide_index=True)

    st.divider()

    # Export section
    st.subheader("💾 Export Options")

    col1, col2 = st.columns(2)

    with col1:
        # JSON export
        json_data = json.dumps(result, indent=2, default=str)
        st.download_button(
            label="📥 Download JSON",
            data=json_data,
            file_name=f"prediction_{instrument}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            key="json_download"
        )

    with col2:
        # CSV export of levels
        csv_data = levels_df.to_csv(index=False)
        st.download_button(
            label="📥 Download Levels CSV",
            data=csv_data,
            file_name=f"levels_{instrument}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            key="csv_download"
        )

    st.divider()

    # Raw result display
    with st.expander("📄 View Raw JSON Result"):
        st.json(result)


# Footer
st.divider()
st.caption("""
Prediction Model v3.0 — Reference Level-based Analytical Framework
Designed for technical analysis of financial instruments (US100/NASDAQ, ES/S&P500, UK100/FTSE)
""")
