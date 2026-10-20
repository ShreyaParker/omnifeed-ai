from decimal import Decimal
from pathlib import Path
import sys
from typing import Any
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# Ensure project root is in sys.path when running `streamlit run dashboard/streamlit_app.py`
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dashboard.api_client import (
        ask_copilot,
        check_health,
        diagnose_job,
        download_error_csv,
        get,
        get_base_url,
        get_cached_analytics_categories,
        get_cached_analytics_overview,
        get_cached_ingestion_history,
        post,
        semantic_search,
        upload,
    )
except ModuleNotFoundError:
    from api_client import (
        ask_copilot,
        check_health,
        diagnose_job,
        download_error_csv,
        get,
        get_base_url,
        get_cached_analytics_categories,
        get_cached_analytics_overview,
        get_cached_ingestion_history,
        post,
        semantic_search,
        upload,
    )

st.set_page_config(
    page_title="OmniFeed AI | Operations Command Center",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

def toggle_theme():
    """Seamlessly toggle between Warm Cream Light mode and Slate Dark mode."""
    st.session_state["theme_mode"] = "dark" if st.session_state.get("theme_mode", "light") == "light" else "light"


# Initialize Theme Mode (defaults to Warm Cream Light mode)
if "theme_mode" not in st.session_state:
    st.session_state["theme_mode"] = "light"

is_light = st.session_state["theme_mode"] == "light"


# Curated Executive Palettes (Warm Cream vs Slate Dark, Zero Neon)
if is_light:
    palette = {
        "app_bg": "#FAF8F5",
        "card_bg": "#FFFFFF",
        "card_border": "#E8E2D5",
        "card_shadow": "0 2px 8px rgba(60, 48, 36, 0.04)",
        "header_bg": "#FFFFFF",
        "header_border": "#E8E2D5",
        "text_primary": "#2C221A",
        "text_secondary": "#6E6459",
        "text_muted": "#8A7E70",
        "delta_good": "#1E6B42",        # Muted Forest Sage
        "delta_warn": "#A65E14",        # Warm Toasted Amber
        "delta_danger": "#A82A2A",      # Deep Refined Crimson
        "accent": "#9A5B2D",            # Warm Cognac / Brass
        "accent_light": "rgba(154, 91, 45, 0.08)",
        "badge_gemini_bg": "linear-gradient(90deg, #7C502C, #9A5B2D)",
        "badge_rules_bg": "#EFECE6",
        "badge_rules_color": "#4A4035",
        "badge_rules_border": "#DCD5C8",
        "citation_bg": "#F5EFE6",
        "citation_border": "#DDD3C2",
        "citation_color": "#784E25",
        "summary_bg": "#FFFFFF",
        "summary_border": "#E2D9CC",
        "summary_text": "#3D352E",
        "action_item_bg": "#FFFFFF",
        "action_item_border": "#9A5B2D",
        "action_item_title": "#9A5B2D",
        "action_item_text": "#2C221A",
        "upload_bg": "#FAF7F2",
        "upload_border": "#C8BCAE",
        "diagnostic_panel_bg": "#FFFFFF",
        "diagnostic_panel_border": "#E2D9CC",
        "diagnostic_header_color": "#2C221A",
        "diagnostic_text": "#3D352E",
        "grid_color": "#E8E1D3",
        "bar_colorscale": [[0, "#E8DCCF"], [0.5, "#9A5B2D"], [1.0, "#5E3314"]],
        "donut_palette": ["#4F6D7A", "#5B8A72", "#C08A3E", "#B25D43", "#7D637E"],
        "chart_font": "#4A4138",
    }
else:
    palette = {
        "app_bg": "#0B0F19",
        "card_bg": "#131B2E",
        "card_border": "rgba(255, 255, 255, 0.08)",
        "card_shadow": "0 4px 20px rgba(0, 0, 0, 0.35)",
        "header_bg": "#131B2E",
        "header_border": "rgba(255, 255, 255, 0.08)",
        "text_primary": "#F8FAFC",
        "text_secondary": "#94A3B8",
        "text_muted": "#64748B",
        "delta_good": "#34D399",
        "delta_warn": "#FBBF24",
        "delta_danger": "#F87171",
        "accent": "#38BDF8",
        "accent_light": "rgba(56, 189, 248, 0.08)",
        "badge_gemini_bg": "linear-gradient(90deg, #4F46E5, #7C3AED)",
        "badge_rules_bg": "#1E293B",
        "badge_rules_color": "#CBD5E1",
        "badge_rules_border": "transparent",
        "citation_bg": "rgba(19, 27, 46, 0.8)",
        "citation_border": "rgba(56, 189, 248, 0.3)",
        "citation_color": "#38BDF8",
        "summary_bg": "#131B2E",
        "summary_border": "rgba(255, 255, 255, 0.08)",
        "summary_text": "#CBD5E1",
        "action_item_bg": "#101626",
        "action_item_border": "#38BDF8",
        "action_item_title": "#38BDF8",
        "action_item_text": "#E2E8F0",
        "upload_bg": "rgba(30, 41, 59, 0.3)",
        "upload_border": "rgba(56, 189, 248, 0.35)",
        "diagnostic_panel_bg": "#131B2E",
        "diagnostic_panel_border": "rgba(255, 255, 255, 0.08)",
        "diagnostic_header_color": "#F8FAFC",
        "diagnostic_text": "#E2E8F0",
        "grid_color": "rgba(255, 255, 255, 0.06)",
        "bar_colorscale": "Tealgrn",
        "donut_palette": px.colors.qualitative.Prism,
        "chart_font": "#94A3B8",
    }

# Dynamic CSS Injection
st.markdown(
    f"""
    <style>
    /* Completely hide Streamlit sidebar to avoid clumsy separate menus */
    [data-testid="stSidebar"], [data-testid="collapsedControl"] {{
        display: none !important;
    }}

    /* Global Base */
    [data-testid="stHeader"] {{
        background-color: transparent !important;
        height: 1.5rem !important;
    }}
    .block-container {{
        padding-top: 3.2rem !important;
        padding-bottom: 2.5rem !important;
        max-width: 95% !important;
    }}
    
    /* Viewport & App Container Background */
    body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"], .main {{
        background-color: {palette["app_bg"]} !important;
        color: {palette["text_primary"]} !important;
    }}
    
    /* Executive Navbar Bar */
    .exec-navbar {{
        background: {palette["header_bg"]};
        border: 1px solid {palette["header_border"]};
        border-radius: 12px;
        padding: 14px 22px;
        margin-bottom: 1.0rem;
        box-shadow: {palette["card_shadow"]};
    }}
    
    /* KPI Metric Cards */
    .kpi-card {{
        background: {palette["card_bg"]};
        border: 1px solid {palette["card_border"]};
        border-radius: 12px;
        padding: 16px 18px;
        box-shadow: {palette["card_shadow"]};
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        min-height: 120px;
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }}
    .kpi-card:hover {{
        transform: translateY(-2px);
        box-shadow: 0 6px 16px rgba(0,0,0,0.06);
    }}
    .kpi-header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
    }}
    .kpi-label {{
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: {palette["text_secondary"]};
        font-weight: 650;
    }}
    .kpi-icon {{
        font-size: 1rem;
        opacity: 0.8;
    }}
    .kpi-value {{
        font-size: 1.85rem;
        font-weight: 700;
        color: {palette["text_primary"]};
        line-height: 1.15;
        margin: 6px 0;
        letter-spacing: -0.02em;
    }}
    .kpi-footer {{
        display: flex;
        align-items: center;
    }}
    .kpi-badge {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 0.74rem;
        font-weight: 600;
    }}
    .kpi-badge-good {{
        background: {'rgba(30, 107, 66, 0.08)' if is_light else 'rgba(52, 211, 153, 0.12)'};
        color: {palette["delta_good"]};
        border: 1px solid {'rgba(30, 107, 66, 0.2)' if is_light else 'rgba(52, 211, 153, 0.25)'};
    }}
    .kpi-badge-warn {{
        background: {'rgba(166, 94, 20, 0.08)' if is_light else 'rgba(251, 191, 36, 0.12)'};
        color: {palette["delta_warn"]};
        border: 1px solid {'rgba(166, 94, 20, 0.2)' if is_light else 'rgba(251, 191, 36, 0.25)'};
    }}
    .kpi-badge-danger {{
        background: {'rgba(168, 42, 42, 0.08)' if is_light else 'rgba(248, 113, 113, 0.12)'};
        color: {palette["delta_danger"]};
        border: 1px solid {'rgba(168, 42, 42, 0.2)' if is_light else 'rgba(248, 113, 113, 0.25)'};
    }}
    
    /* Custom Badges */
    .badge-gemini {{
        display: inline-flex;
        align-items: center;
        background: {palette["badge_gemini_bg"]};
        color: #ffffff;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.78rem;
        font-weight: 600;
        letter-spacing: 0.02em;
    }}
    .badge-rules {{
        display: inline-flex;
        align-items: center;
        background: {palette["badge_rules_bg"]};
        color: {palette["badge_rules_color"]};
        border: 1px solid {palette["badge_rules_border"]};
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.78rem;
        font-weight: 600;
    }}
    .tool-citation {{
        background: {palette["citation_bg"]};
        border: 1px solid {palette["citation_border"]};
        border-radius: 8px;
        padding: 8px 12px;
        margin-top: 8px;
        font-size: 0.82rem;
        color: {palette["citation_color"]};
    }}
    
    /* Container Panels */
    .summary-panel {{
        background: {palette["summary_bg"]};
        border: 1px solid {palette["summary_border"]};
        border-radius: 12px;
        padding: 22px;
        margin-top: 10px;
        box-shadow: {palette["card_shadow"]};
    }}
    .action-item-card {{
        background: {palette["action_item_bg"]};
        border: 1px solid {palette["card_border"]};
        border-left: 4px solid {palette["action_item_border"]};
        border-radius: 8px;
        padding: 14px;
        height: 100%;
        box-shadow: {palette["card_shadow"]};
    }}
    .upload-dropzone {{
        background: {palette["upload_bg"]};
        border: 2px dashed {palette["upload_border"]};
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        margin-bottom: 12px;
    }}
    .diagnostic-panel {{
        background: {palette["diagnostic_panel_bg"]};
        border: 1px solid {palette["diagnostic_panel_border"]};
        border-radius: 12px;
        padding: 20px;
        margin-top: 15px;
        box-shadow: {palette["card_shadow"]};
    }}
    
    /* Tab Styling Overrides */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 6px;
        border-bottom: 2px solid {'#E8E2D5' if is_light else 'rgba(255, 255, 255, 0.08)'} !important;
        padding-bottom: 2px;
        margin-bottom: 1.0rem;
    }}
    .stTabs [data-baseweb="tab"] {{
        height: 44px;
        border-radius: 8px 8px 0 0;
        padding: 8px 18px;
        font-weight: 600;
        font-size: 0.92rem;
        color: {palette["text_secondary"]} !important;
        background: transparent !important;
    }}
    .stTabs [aria-selected="true"] {{
        color: {palette["accent"]} !important;
        border-bottom: 2px solid {palette["accent"]} !important;
        background: {palette["accent_light"]} !important;
    }}
    
    /* Modern Button Styling */
    div.stButton > button {{
        border-radius: 8px !important;
        font-weight: 600 !important;
        font-size: 0.82rem !important;
        padding: 6px 14px !important;
        border: 1px solid {palette["card_border"]} !important;
        background: {palette["card_bg"]} !important;
        color: {palette["text_primary"]} !important;
        box-shadow: {palette["card_shadow"]} !important;
        transition: all 0.2s ease-in-out !important;
    }}
    div.stButton > button:hover {{
        border-color: {palette["accent"]} !important;
        color: {palette["accent"]} !important;
    }}
    
    /* Widget & Message Styling */
    [data-testid="stChatMessage"] {{
        background-color: {palette["card_bg"]} !important;
        border: 1px solid {palette["card_border"]} !important;
        border-radius: 12px !important;
        color: {palette["text_primary"]} !important;
        margin-bottom: 10px !important;
        box-shadow: {palette["card_shadow"]};
    }}
    [data-testid="stChatMessage"] * {{
        color: {palette["text_primary"]} !important;
    }}
    div[data-testid="stMetricValue"] {{
        color: {palette["text_primary"]} !important;
    }}
    div[data-testid="stMetricLabel"] {{
        color: {palette["text_secondary"]} !important;
    }}
    [data-testid="stExpander"] {{
        background-color: {palette["app_bg"]} !important;
        border: 1px solid {palette["card_border"]} !important;
        border-radius: 10px !important;
    }}
    [data-testid="stDataFrame"] {{
        border: 1px solid {palette["card_border"]} !important;
        border-radius: 8px !important;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


def format_inr(value: Any) -> str:
    """Format decimal or float value as Indian Rupees ₹ with commas."""
    try:
        dec = Decimal(str(value))
        return f"₹{dec:,.2f}"
    except Exception:
        return f"₹{value}"


# Top Executive Navbar Bar (100% Full-Width Cohesive Header)
base_url = get_base_url()

navbar_col_brand, navbar_col_controls = st.columns([3.8, 1.2], vertical_alignment="center")

with navbar_col_brand:
    st.markdown(
        f"""
        <div style="display: flex; align-items: center; gap: 14px; padding: 4px 0;">
            <div style="font-size: 2.0rem; line-height: 1;">⚡</div>
            <div>
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 1.55rem; font-weight: 800; letter-spacing: -0.025em; color: {palette['text_primary']};">
                        OmniFeed AI
                    </span>
                    <span style="display: inline-flex; align-items: center; padding: 2px 8px; background: {palette['accent_light']}; border: 1px solid {palette['accent']}; color: {palette['accent']}; border-radius: 6px; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">
                        Operations Hub
                    </span>
                    <span style="display: inline-flex; align-items: center; gap: 5px; padding: 2px 8px; background: {'rgba(30, 107, 66, 0.08)' if is_light else 'rgba(52, 211, 153, 0.1)'}; border: 1px solid {palette['delta_good']}; color: {palette['delta_good']}; border-radius: 6px; font-size: 0.72rem; font-weight: 600;">
                        <span style="width: 6px; height: 6px; border-radius: 50%; background-color: {palette['delta_good']}; display: inline-block;"></span>
                        Live DB Connected
                    </span>
                </div>
                <div style="color: {palette['text_secondary']}; font-size: 0.86rem; margin-top: 2px;">
                    Executive Command Center for Real-Time Multi-Format Ingestion, Quality Audits & Copilot Intelligence
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with navbar_col_controls:
    theme_btn_label = "🌙 Dark Mode" if is_light else "☀️ Cream Mode"
    st.button(
        theme_btn_label,
        key="theme_toggle_btn",
        on_click=toggle_theme,
        use_container_width=True,
        help="1-Click Toggle between Warm Cream Light and Slate Dark palettes",
    )

st.markdown(
    f"""<div style="height: 1px; background: {palette['card_border']}; margin: 8px 0 16px 0; opacity: 0.7;"></div>""",
    unsafe_allow_html=True,
)

# Active Backend Wake-Up Check (Cold-Start Guard)
if "backend_ready" not in st.session_state:
    with st.spinner("Connecting to cloud API... If cold starting, this takes ~30 seconds."):
        try:
            check_health(timeout=15)
            st.session_state["backend_ready"] = True
        except Exception:
            try:
                check_health(timeout=20)
                st.session_state["backend_ready"] = True
            except Exception as exc:
                st.error(
                    f"🚨 **Unable to connect to OmniFeed backend API at `{get_base_url()}`**\n\n"
                    f"Please verify that the FastAPI backend server is active (`uvicorn app.main:app --reload`).\n\n"
                    f"Error details: `{exc}`"
                )
                st.stop()

# Fetch Global Inventory Overview (Cached with 30s TTL for instant UI navigation)
overview_data = None
try:
    overview_data = get_cached_analytics_overview()
except Exception as exc:
    st.error(
        f"🚨 **Unable to connect to OmniFeed backend API at `{get_base_url()}`**\n\n"
        f"Please verify that the FastAPI backend server is active (`uvicorn app.main:app --reload`).\n\n"
        f"Error details: `{exc}`"
    )
    st.stop()

# Fetch Categories Data (Cached with 30s TTL)
try:
    categories_data = get_cached_analytics_categories()
except Exception:
    categories_data = []

# Top Navigation Tabs
tab_overview, tab_ingestion, tab_catalog, tab_copilot = st.tabs([
    "📊 Executive Overview",
    "⚡ Ingestion & ETL Studio",
    "🔍 Intelligent Catalog",
    "💬 OmniBot Copilot",
])


# ==============================================================================
# TAB 1: EXECUTIVE OVERVIEW
# ==============================================================================
with tab_overview:
    # 4 High-density KPI cards with Delta indicators
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)

    total_skus = overview_data.get("total_skus", 0)
    total_units = overview_data.get("total_units", 0)
    valuation_val = overview_data.get("inventory_valuation", "0.00")
    low_stock = overview_data.get("low_stock_items", 0)
    out_of_stock = overview_data.get("out_of_stock_items", 0)

    with kpi1:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-header">
                    <span class="kpi-label">Total Catalog Products</span>
                    <span class="kpi-icon">📦</span>
                </div>
                <div class="kpi-value">{total_skus:,}</div>
                <div class="kpi-footer">
                    <span class="kpi-badge kpi-badge-good">↑ {total_units:,} stocked units</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with kpi2:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-header">
                    <span class="kpi-label">Aggregate Valuation</span>
                    <span class="kpi-icon">💰</span>
                </div>
                <div class="kpi-value">{format_inr(valuation_val)}</div>
                <div class="kpi-footer">
                    <span class="kpi-badge kpi-badge-good">● Live Real-Time Portfolio</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with kpi3:
        warn_active = low_stock > 0
        badge_cls = "kpi-badge-warn" if warn_active else "kpi-badge-good"
        badge_text = "⚠️ Reorder Triggers Pending" if warn_active else "✅ Stock Levels Balanced"
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-header">
                    <span class="kpi-label">At-Risk Stock (&lt; 10 Units)</span>
                    <span class="kpi-icon">⚠️</span>
                </div>
                <div class="kpi-value">{low_stock:,}</div>
                <div class="kpi-footer">
                    <span class="kpi-badge {badge_cls}">{badge_text}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with kpi4:
        out_active = out_of_stock > 0
        badge_cls = "kpi-badge-danger" if out_active else "kpi-badge-good"
        badge_text = "🚨 Critical Stockouts" if out_active else "✅ Zero Stockouts"
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-header">
                    <span class="kpi-label">Stockout Outages</span>
                    <span class="kpi-icon">🛑</span>
                </div>
                <div class="kpi-value">{out_of_stock:,}</div>
                <div class="kpi-footer">
                    <span class="kpi-badge {badge_cls}">{badge_text}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.write("")

    # Visual Analytics Row
    chart_col1, chart_col2 = st.columns([3, 2], gap="medium")

    with chart_col1:
        st.subheader("📈 Valuation by Category")
        if categories_data:
            df_cat = pd.DataFrame(categories_data)
            df_cat["total_valuation_num"] = df_cat["total_valuation"].apply(
                lambda v: float(v) if v else 0.0
            )
            df_cat["valuation_formatted"] = df_cat["total_valuation"].apply(format_inr)
            df_cat = df_cat.sort_values(by="total_valuation_num", ascending=True)

            fig_bar = px.bar(
                df_cat,
                x="total_valuation_num",
                y="category",
                orientation="h",
                labels={"total_valuation_num": "Valuation (₹)", "category": "Category"},
                color="total_valuation_num",
                color_continuous_scale=palette["bar_colorscale"],
                custom_data=["valuation_formatted", "total_units", "sku_count"],
            )
            fig_bar.update_traces(
                hovertemplate="<b>%{y}</b><br>Valuation: %{customdata[0]}<br>Units: %{customdata[1]:,}<br>SKUs: %{customdata[2]}<extra></extra>",
                marker=dict(line=dict(width=1, color="rgba(0,0,0,0.08)" if is_light else "rgba(255,255,255,0.2)")),
            )
            fig_bar.update_layout(
                margin=dict(l=20, r=20, t=10, b=20),
                height=320,
                coloraxis_showscale=False,
                xaxis=dict(showgrid=True, gridcolor=palette["grid_color"], tickfont=dict(color=palette["text_secondary"])),
                yaxis=dict(showgrid=False, tickfont=dict(color=palette["text_primary"])),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color=palette["chart_font"]),
            )
            st.plotly_chart(fig_bar, use_container_width=True, config={"responsive": True, "displayModeBar": False})
        else:
            st.info("No category valuation data available yet. Ingest an inventory feed to populate graphs.")

    with chart_col2:
        st.subheader("🍩 Category Stock Distribution")
        if categories_data:
            fig_donut = px.pie(
                df_cat,
                values="total_units",
                names="category",
                hole=0.48,
                color_discrete_sequence=palette["donut_palette"],
            )
            fig_donut.update_traces(
                textposition="inside",
                textinfo="percent+label",
                hovertemplate="<b>%{label}</b><br>Units: %{value:,}<br>Share: %{percent}<extra></extra>",
                marker=dict(line=dict(color="#FAF8F5" if is_light else "#0f172a", width=2)),
            )
            fig_donut.update_layout(
                margin=dict(l=10, r=10, t=10, b=10),
                height=320,
                showlegend=False,
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color=palette["chart_font"]),
            )
            st.plotly_chart(fig_donut, use_container_width=True, config={"responsive": True, "displayModeBar": False})
        else:
            st.info("Stock distribution will appear here after initial ingestion.")

    # Operations Summary Card Generated by Gemini
    st.markdown("---")
    summary_header_col1, summary_header_col2 = st.columns([3, 1])
    with summary_header_col1:
        st.subheader("🤖 Operations Intelligence & Executive Insights")
        st.caption("AI-synthesized inventory summary and actionable recommendations.")
    with summary_header_col2:
        refresh_insights = st.button("✨ Refresh Insights", use_container_width=True)

    if refresh_insights or "cached_insights" not in st.session_state:
        with st.spinner("Synthesizing operations intelligence..."):
            try:
                st.session_state["cached_insights"] = post("/api/v1/ai/insights")
            except Exception as err:
                st.session_state["cached_insights"] = {
                    "source": "rules",
                    "summary": f"Catalog contains {total_skus} SKUs valued at {format_inr(valuation_val)} with {low_stock} low-stock triggers.",
                    "recommendations": ["Review reorder points for low-stock items."],
                }

    insights_data = st.session_state.get("cached_insights", {})
    badge_html = (
        '<span class="badge-gemini">✨ Google Gemini Intelligence</span>'
        if insights_data.get("source") == "gemini"
        else '<span class="badge-rules">⚙️ Deterministic Rules Engine</span>'
    )

    st.markdown(
        f"""
        <div class="summary-panel">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <span style="font-size: 1.05rem; font-weight: 700; color: {palette['text_primary']};">Executive Operations Summary</span>
                {badge_html}
            </div>
            <p style="color: {palette['summary_text']}; font-size: 0.95rem; line-height: 1.6; margin-bottom: 16px;">
                {insights_data.get("summary", "No executive summary available.")}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    recs = insights_data.get("recommendations", [])
    if recs:
        st.markdown(f"<div style='margin-top: 14px; color: {palette['text_primary']};'><b>🎯 Operational Priority Recommendations:</b></div>", unsafe_allow_html=True)
        r_cols = st.columns(min(len(recs), 3))
        for idx, rec in enumerate(recs[:3]):
            with r_cols[idx]:
                st.markdown(
                    f"""
                    <div class="action-item-card">
                        <div style="font-size: 0.82rem; font-weight: 700; color: {palette['action_item_title']}; margin-bottom: 4px;">ACTION ITEM #{idx+1}</div>
                        <div style="font-size: 0.86rem; color: {palette['action_item_text']}; line-height: 1.4;">{rec}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


# ==============================================================================
# TAB 2: INGESTION & ETL STUDIO
# ==============================================================================
with tab_ingestion:
    st.subheader("⚡ Multi-Format Supplier Ingestion Studio")
    st.caption("Universal ETL gateway supporting CSV, JSON, and XML feeds with automatic deduplication and vector embedding generation.")

    upload_col, stats_col = st.columns([3, 2], gap="large")

    with upload_col:
        st.markdown(
            f"""
            <div class="upload-dropzone">
                <div style="font-size: 1.1rem; font-weight: 600; color: {palette['text_primary']}; margin-bottom: 4px;">Drag and Drop Supplier Data Feed</div>
                <div style="color: {palette['text_secondary']}; font-size: 0.85rem;">Supported formats: <b>.CSV</b>, <b>.JSON</b>, <b>.XML</b> (Max upload limit: 10 MB)</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        supplier_file = st.file_uploader(
            "Upload file",
            type=["csv", "json", "xml"],
            label_visibility="collapsed",
            key="supplier_uploader",
        )

        if st.button("🚀 Process & Ingest Feed", type="primary", use_container_width=True):
            if supplier_file is None:
                st.warning("Please choose a valid feed file before starting ingestion.")
            else:
                with st.spinner(f"Ingesting & embedding {supplier_file.name}..."):
                    try:
                        summary = upload("/api/v1/ingest", supplier_file)
                        st.session_state["latest_ingestion_summary"] = summary
                        st.cache_data.clear()
                        st.success(f"Ingestion {summary.get('status', 'completed')}: {supplier_file.name}")
                    except requests.HTTPError as err:
                        st.error(f"Ingestion rejected: {err}")
                    except Exception as err:
                        st.error(f"Ingestion failed: {err}")

    with stats_col:
        st.markdown("##### Latest Processing Metrics")
        latest_summary = st.session_state.get("latest_ingestion_summary")
        if latest_summary:
            im1, im2 = st.columns(2)
            im3, im4 = st.columns(2)

            with im1:
                st.metric("Total Processed", latest_summary.get("records_processed", 0))
            with im2:
                st.metric("Inserted (New)", latest_summary.get("records_inserted", 0))
            with im3:
                st.metric("Updated (Upsert)", latest_summary.get("records_updated", 0))
            with im4:
                failed_cnt = latest_summary.get("records_failed", 0)
                st.metric("Validation Failed", failed_cnt, delta=f"-{failed_cnt}" if failed_cnt > 0 else "0", delta_color="inverse")

            errors_list = latest_summary.get("errors", [])
            if failed_cnt > 0 or errors_list:
                err_df = (
                    pd.DataFrame(errors_list)
                    if errors_list
                    else pd.DataFrame(columns=["row_number", "sku", "error_code", "error_message"])
                )
                display_cols = [
                    c for c in ["row_number", "sku", "error_code", "error_message"] if c in err_df.columns
                ]
                remediation_csv = err_df[display_cols].to_csv(index=False)

                st.download_button(
                    label="📥 Download Vendor Remediation CSV",
                    data=remediation_csv,
                    file_name=f"vendor_remediation_{latest_summary.get('filename', 'feed')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key="download_vendor_remediation_csv_immediate",
                )

                if errors_list:
                    with st.expander(f"⚠️ View {len(errors_list)} Row Validation Errors", expanded=False):
                        st.dataframe(err_df[display_cols], use_container_width=True, hide_index=True)
        else:
            st.info("Upload and process a catalog feed to inspect live row ingestion metrics.")

    st.markdown("---")

    # Ingestion Audit History Table
    st.subheader("📜 Ingestion Audit History")
    st.caption("Chronological audit log of all supplier feed uploads and batch jobs.")

    try:
        hist_resp = get_cached_ingestion_history()
        hist_jobs = hist_resp.get("history", [])
    except Exception:
        hist_jobs = []

    if hist_jobs:
        df_hist = pd.DataFrame(hist_jobs)
        st.dataframe(
            df_hist[["id", "filename", "file_type", "status", "records_processed", "records_inserted", "records_updated", "records_failed", "created_at"]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No past ingestion jobs found in audit history.")

    # Supplier Diagnostic Panel
    st.markdown("---")
    st.subheader("🔬 Supplier Feed Quality Diagnostic & Remediation")
    st.caption("AI-powered diagnostic engine analyzing root causes and generating supplier remediation packages.")

    diag_col1, diag_col2 = st.columns([2, 1])
    with diag_col1:
        job_options = [j["id"] for j in hist_jobs] if hist_jobs else [1]
        selected_job_id = st.selectbox(
            "Select Ingestion Job ID for Quality Diagnostic:",
            options=job_options,
            format_func=lambda j_id: f"Job #{j_id} — {next((j['filename'] for j in hist_jobs if j['id'] == j_id), 'Batch Job')}",
        )

    with diag_col2:
        st.write("")
        st.write("")
        run_diagnostic = st.button("🔍 Diagnose Ingestion Feed", type="primary", use_container_width=True)

    if run_diagnostic:
        with st.spinner(f"Analyzing feed #{selected_job_id} quality & error logs..."):
            try:
                diag_result = diagnose_job(selected_job_id)
                st.session_state[f"diagnostic_{selected_job_id}"] = diag_result
            except Exception as exc:
                st.error(f"Failed to diagnose job #{selected_job_id}: {exc}")

    if f"diagnostic_{selected_job_id}" in st.session_state:
        diag = st.session_state[f"diagnostic_{selected_job_id}"]
        score = diag.get("health_score", 100)
        score_color = palette["delta_good"] if score >= 85 else (palette["delta_warn"] if score >= 60 else palette["delta_danger"])

        st.markdown(
            f"""
            <div class="diagnostic-panel">
                <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid {palette['diagnostic_panel_border']}; padding-bottom: 12px; margin-bottom: 16px;">
                    <div>
                        <h4 style="margin: 0; color: {palette['diagnostic_header_color']};">Diagnostic Report for Job #{diag.get('job_id')}: {diag.get('filename')}</h4>
                        <div style="color: {palette['text_secondary']}; font-size: 0.85rem; margin-top: 4px;">Status: <b>{diag.get('status')}</b> | Failed Records: <b>{diag.get('records_failed')}</b> of {diag.get('records_processed')}</div>
                    </div>
                    <div style="text-align: right;">
                        <span style="font-size: 1.8rem; font-weight: 800; color: {score_color};">{score}</span>
                        <span style="color: {palette['text_secondary']}; font-size: 0.9rem;">/100 Health Score</span>
                    </div>
                </div>
                <p style="color: {palette['diagnostic_text']}; font-size: 0.95rem; line-height: 1.5;">{diag.get('summary', '')}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        d_col1, d_col2 = st.columns(2)
        with d_col1:
            st.markdown("##### 🔍 Root Causes Identified")
            root_causes = diag.get("root_causes", [])
            if root_causes:
                for rc in root_causes:
                    st.markdown(f"• {rc}")
            else:
                st.write("No root causes detected; file was 100% compliant.")

        with d_col2:
            st.markdown("##### 🛠️ Actionable Vendor Instructions")
            instructions = diag.get("actionable_vendor_instructions", [])
            if instructions:
                for inst in instructions:
                    st.markdown(f"1. {inst}")
            else:
                st.write("No remediation instructions necessary.")

        # Download Error CSV Button
        try:
            csv_content = download_error_csv(selected_job_id)
            st.write("")
            st.download_button(
                label="📥 Download Vendor Remediation CSV",
                data=csv_content,
                file_name=f"ingestion_job_{selected_job_id}_errors.csv",
                mime="text/csv",
                use_container_width=True,
                key=f"download_diagnostic_csv_{selected_job_id}",
            )
        except Exception as e:
            st.caption(f"CSV error log export note: {e}")


# ==============================================================================
# TAB 3: INTELLIGENT CATALOG
# ==============================================================================
with tab_catalog:
    st.subheader("🔍 Intelligent Product Catalog Explorer")
    st.caption("Hybrid exploration supporting exact SKU pattern search and pgvector-backed semantic vector search (RAG).")

    # Search Mode Selector
    search_col1, search_col2 = st.columns([1, 2])
    with search_col1:
        search_mode = st.radio(
            "Search Engine:",
            options=["Semantic AI Search (RAG)", "Exact Search"],
            horizontal=True,
        )
    with search_col2:
        catalog_query = st.text_input(
            "Query Catalog:",
            placeholder="Search by keywords, natural concepts (e.g., 'wireless accessories'), or exact SKU...",
            label_visibility="collapsed",
        )

    # Interactive Filters Row
    f_col1, f_col2, f_col3 = st.columns([1, 1, 1])

    with f_col1:
        cat_filter_opts = ["All Categories"]
        if categories_data:
            cat_filter_opts += [c["category"] for c in categories_data]
        selected_cat_filter = st.selectbox("Category Filter:", options=cat_filter_opts)

    with f_col2:
        stock_filter = st.selectbox(
            "Stock Availability Filter:",
            options=["All Statuses", "In Stock (≥ 10)", "Low Stock (1-9)", "Out of Stock (0)"],
        )

    with f_col3:
        max_rows = st.selectbox("Max Results:", options=[10, 25, 50, 100], index=1)

    # Fetch Catalog Items
    catalog_items = []
    loading_error = None

    with st.spinner("Fetching catalog data..."):
        try:
            if search_mode == "Semantic AI Search (RAG)" and catalog_query.strip():
                catalog_items = semantic_search(query=catalog_query.strip(), limit=max_rows)
            else:
                params = {"limit": max_rows, "page": 1}
                if catalog_query.strip():
                    params["search"] = catalog_query.strip()
                if selected_cat_filter != "All Categories":
                    params["category"] = selected_cat_filter
                resp = get("/api/v1/items", params=params)
                catalog_items = resp.get("items", [])
        except Exception as err:
            loading_error = err

    if loading_error:
        st.warning(f"Could not load items: {loading_error}")
    elif not catalog_items:
        st.info("No matching catalog products found. Adjust your search keywords or filter criteria.")
    else:
        df_display = pd.DataFrame(catalog_items)

        # Apply in-memory Category filter for Semantic Search
        if selected_cat_filter != "All Categories" and "category" in df_display.columns:
            df_display = df_display[df_display["category"].str.lower() == selected_cat_filter.lower()]

        # Apply Stock Status Filter
        if "stock_quantity" in df_display.columns:
            if stock_filter == "In Stock (≥ 10)":
                df_display = df_display[df_display["stock_quantity"] >= 10]
            elif stock_filter == "Low Stock (1-9)":
                df_display = df_display[(df_display["stock_quantity"] > 0) & (df_display["stock_quantity"] < 10)]
            elif stock_filter == "Out of Stock (0)":
                df_display = df_display[df_display["stock_quantity"] == 0]

            # Add Stock Badge Column
            def assign_status(qty):
                if qty == 0:
                    return "🔴 Out of Stock"
                elif qty < 10:
                    return f"🟡 Low Stock ({qty})"
                else:
                    return f"🟢 In Stock ({qty})"

            df_display["Status Badge"] = df_display["stock_quantity"].apply(assign_status)

        if "unit_price" in df_display.columns:
            df_display["Formatted Price"] = df_display["unit_price"].apply(format_inr)

        st.caption(f"Displaying {len(df_display)} products")

        cols_order = ["sku", "name", "category", "Status Badge", "Formatted Price"]
        if "similarity_score" in df_display.columns:
            cols_order.append("similarity_score")
        if "search_type" in df_display.columns:
            cols_order.append("search_type")

        existing_show = [c for c in cols_order if c in df_display.columns]
        st.dataframe(
            df_display[existing_show],
            use_container_width=True,
            hide_index=True,
        )


# ==============================================================================
# TAB 4: OMNIBOT COPILOT
# ==============================================================================
with tab_copilot:
    st.subheader("💬 OmniBot Operations Copilot")
    st.caption("Conversational AI analyst powered by Gemini Function Calling with direct read-only SQL grounding.")

    # Initialize Session State Messages
    if "messages" not in st.session_state:
        st.session_state["messages"] = [
            {
                "role": "assistant",
                "content": (
                    "👋 Hello! I am your **OmniBot Operations Copilot**. "
                    "I have live access to your PostgreSQL inventory database. "
                    "You can ask me to evaluate stockout risks, calculate valuations, break down categories, or locate specific products."
                ),
                "tool_used": None,
                "data_sources": [],
            }
        ]

    # Quick Action Pills
    st.markdown("##### ⚡ Quick Prompt Pills")
    quick_options = [
        "Summarize top stock risks",
        "Which category holds the most capital?",
        "Find wireless accessories under ₹1500",
        "Give me an overview of total inventory valuation",
    ]

    selected_pill = st.pills("Select an operational prompt:", options=quick_options, key="copilot_pill")

    # Render Existing Messages
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("tool_used"):
                st.markdown(
                    f'<div class="tool-citation">🏷️ <b>Verified via Live SQL Database:</b> <code>{msg["tool_used"]}</code></div>',
                    unsafe_allow_html=True,
                )
                sources = msg.get("data_sources", [])
                if sources:
                    with st.expander("🔍 View Raw Grounded Database Sources", expanded=False):
                        st.json(sources)

    # Chat Input Box
    user_prompt = st.chat_input("Ask OmniBot about inventory, valuations, stockout risks...")

    # Determine prompt to process
    prompt_to_send = None
    if user_prompt:
        prompt_to_send = user_prompt
    elif selected_pill and ("last_sent_pill" not in st.session_state or st.session_state["last_sent_pill"] != selected_pill):
        prompt_to_send = selected_pill
        st.session_state["last_sent_pill"] = selected_pill

    if prompt_to_send:
        # Append User Message
        st.session_state["messages"].append({"role": "user", "content": prompt_to_send})
        with st.chat_message("user"):
            st.markdown(prompt_to_send)

        # Call Backend Copilot
        with st.chat_message("assistant"):
            with st.spinner("OmniBot querying database & synthesizing response..."):
                try:
                    # Pass recent chat history for context
                    history_context = [
                        {"role": m["role"], "content": m["content"]}
                        for m in st.session_state["messages"][-6:-1]
                    ]
                    bot_resp = ask_copilot(prompt_to_send, history=history_context)

                    resp_text = bot_resp.get("response", "No response generated.")
                    tool_used = bot_resp.get("tool_used")
                    data_sources = bot_resp.get("data_sources", [])

                    st.markdown(resp_text)
                    if tool_used:
                        st.markdown(
                            f'<div class="tool-citation">🏷️ <b>Verified via Live SQL Database:</b> <code>{tool_used}</code></div>',
                            unsafe_allow_html=True,
                        )
                        if data_sources:
                            with st.expander("🔍 View Raw Grounded Database Sources", expanded=False):
                                st.json(data_sources)

                    # Save to session state
                    st.session_state["messages"].append({
                        "role": "assistant",
                        "content": resp_text,
                        "tool_used": tool_used,
                        "data_sources": data_sources,
                    })

                except Exception as exc:
                    err_msg = f"Sorry, I encountered an issue accessing the operations database: {exc}"
                    st.error(err_msg)
                    st.session_state["messages"].append({
                        "role": "assistant",
                        "content": err_msg,
                        "tool_used": None,
                        "data_sources": [],
                    })
