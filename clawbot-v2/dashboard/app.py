"""
CLAWBOT v2 Dashboard - Dark theme, full KPIs.
Accessible on local network at http://<ip>:8050
"""
import json
import os
from datetime import datetime, timezone
from dash import Dash, html, dcc, dash_table
from dash.dependencies import Input, Output
from config import settings


def create_dashboard(risk_manager, position_manager):
    """Create and configure the Dash dashboard."""
    app = Dash(__name__, title="CLAWBOT v2")

    # Dark theme CSS
    dark_style = {
        "backgroundColor": "#1a1a2e",
        "color": "#e0e0e0",
        "fontFamily": "'Segoe UI', Tahoma, sans-serif",
        "minHeight": "100vh",
        "padding": "20px",
    }

    card_style = {
        "backgroundColor": "#16213e",
        "borderRadius": "10px",
        "padding": "20px",
        "margin": "10px",
        "boxShadow": "0 4px 6px rgba(0,0,0,0.3)",
    }

    kpi_style = {
        "textAlign": "center",
        "padding": "15px",
        "backgroundColor": "#0f3460",
        "borderRadius": "8px",
        "margin": "5px",
        "minWidth": "150px",
    }

    app.layout = html.Div(style=dark_style, children=[
        # Header
        html.Div(style={"textAlign": "center", "marginBottom": "20px"}, children=[
            html.H1("CLAWBOT v2", style={"color": "#e94560", "marginBottom": "5px"}),
            html.P("AI-Powered Trading System", style={"color": "#888", "fontSize": "14px"}),
            html.P(id="last-update", style={"color": "#666", "fontSize": "12px"}),
        ]),

        # Auto-refresh
        dcc.Interval(id="interval", interval=5000, n_intervals=0),

        # KPI Row
        html.Div(id="kpi-row", style={
            "display": "flex", "justifyContent": "center",
            "flexWrap": "wrap", "marginBottom": "20px",
        }),

        # Status Banner
        html.Div(id="status-banner", style={
            "textAlign": "center", "padding": "10px",
            "borderRadius": "8px", "marginBottom": "20px",
        }),

        # Open Positions Table
        html.Div(style=card_style, children=[
            html.H3("Open Positions", style={"color": "#e94560", "marginBottom": "15px"}),
            html.Div(id="positions-table"),
        ]),

        # Scan History
        html.Div(style=card_style, children=[
            html.H3("Recent Activity", style={"color": "#e94560", "marginBottom": "15px"}),
            html.Div(id="activity-log", style={
                "maxHeight": "300px", "overflowY": "auto",
                "fontFamily": "monospace", "fontSize": "12px",
            }),
        ]),

        # Hidden data stores
        dcc.Store(id="risk-data"),
        dcc.Store(id="position-data"),
    ])

    @app.callback(
        [
            Output("kpi-row", "children"),
            Output("status-banner", "children"),
            Output("status-banner", "style"),
            Output("positions-table", "children"),
            Output("last-update", "children"),
        ],
        Input("interval", "n_intervals"),
    )
    def update_dashboard(n):
        now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

        # Get risk status
        risk_status = risk_manager.get_status()
        balance = risk_status.get("balance", 0)
        equity = risk_status.get("equity", 0)
        daily_pnl_pct = risk_status.get("daily_pnl_pct", 0)
        daily_pnl_usd = risk_status.get("daily_pnl_usd", 0)
        open_pos = risk_status.get("open_positions", 0)

        # KPIs
        pnl_color = "#4ecca3" if daily_pnl_pct >= 0 else "#e94560"
        kpis = html.Div(style={
            "display": "flex", "justifyContent": "center",
            "flexWrap": "wrap", "gap": "10px",
        }, children=[
            _kpi_card("Balance", f"${balance:,.2f}", "#4ecca3"),
            _kpi_card("Equity", f"${equity:,.2f}", "#4ecca3"),
            _kpi_card("Daily P&L", f"{daily_pnl_pct:+.2f}%", pnl_color),
            _kpi_card("Daily P&L $", f"${daily_pnl_usd:+.2f}", pnl_color),
            _kpi_card("Open Positions", str(open_pos), "#e0e0e0"),
            _kpi_card("Mode",
                       "KILLED" if risk_status.get("killed") else
                       "RECOVERY" if risk_status.get("recovery_mode") else "NORMAL",
                       "#e94560" if risk_status.get("killed") else
                       "#ffa500" if risk_status.get("recovery_mode") else "#4ecca3"),
        ])

        # Status banner
        if risk_status.get("killed"):
            banner = "KILL SWITCH ACTIVE - Trading halted"
            banner_style = {"backgroundColor": "#e94560", "color": "white",
                           "textAlign": "center", "padding": "10px",
                           "borderRadius": "8px", "marginBottom": "20px",
                           "fontWeight": "bold", "fontSize": "18px"}
        elif risk_status.get("recovery_mode"):
            banner = "RECOVERY MODE - Risk reduced 50%"
            banner_style = {"backgroundColor": "#ffa500", "color": "black",
                           "textAlign": "center", "padding": "10px",
                           "borderRadius": "8px", "marginBottom": "20px",
                           "fontWeight": "bold"}
        else:
            banner = "System Active"
            banner_style = {"backgroundColor": "#1a472a", "color": "#4ecca3",
                           "textAlign": "center", "padding": "10px",
                           "borderRadius": "8px", "marginBottom": "20px"}

        # Positions table
        positions = position_manager.get_status()
        if positions:
            table = dash_table.DataTable(
                data=positions,
                columns=[
                    {"name": "Ticket", "id": "ticket"},
                    {"name": "Symbol", "id": "symbol"},
                    {"name": "Side", "id": "action"},
                    {"name": "Lots", "id": "lot_size"},
                    {"name": "Entry", "id": "entry"},
                    {"name": "Current", "id": "current"},
                    {"name": "SL", "id": "sl"},
                    {"name": "TP", "id": "tp"},
                    {"name": "P&L", "id": "pnl"},
                    {"name": "R", "id": "r_multiple"},
                    {"name": "BE", "id": "breakeven"},
                    {"name": "TP1", "id": "tp1_done"},
                    {"name": "Trail", "id": "trailing"},
                ],
                style_header={
                    "backgroundColor": "#0f3460",
                    "color": "#e0e0e0",
                    "fontWeight": "bold",
                },
                style_data={
                    "backgroundColor": "#16213e",
                    "color": "#e0e0e0",
                },
                style_data_conditional=[
                    {"if": {"filter_query": "{pnl} > 0"}, "color": "#4ecca3"},
                    {"if": {"filter_query": "{pnl} < 0"}, "color": "#e94560"},
                ],
                style_cell={
                    "textAlign": "center",
                    "padding": "8px",
                    "border": "1px solid #333",
                },
            )
        else:
            table = html.P("No open positions", style={"color": "#666", "textAlign": "center"})

        return kpis, banner, banner_style, table, f"Last update: {now}"

    @app.callback(
        Output("activity-log", "children"),
        Input("interval", "n_intervals"),
    )
    def update_activity(n):
        """Load recent activity from trade log."""
        log_file = os.path.join(
            settings.TRADE_LOG_DIR,
            f"trades_{datetime.utcnow().strftime('%Y-%m-%d')}.log"
        )
        if not os.path.exists(log_file):
            return html.P("No activity today", style={"color": "#666"})

        try:
            with open(log_file, "r") as f:
                lines = f.readlines()[-50:]  # Last 50 lines

            return html.Pre(
                "".join(reversed(lines)),
                style={"color": "#aaa", "whiteSpace": "pre-wrap"}
            )
        except Exception:
            return html.P("Error reading log", style={"color": "#e94560"})

    return app


def _kpi_card(title: str, value: str, color: str) -> html.Div:
    """Create a single KPI card."""
    return html.Div(style={
        "textAlign": "center",
        "padding": "15px 25px",
        "backgroundColor": "#0f3460",
        "borderRadius": "8px",
        "minWidth": "140px",
    }, children=[
        html.P(title, style={"color": "#888", "fontSize": "12px", "margin": "0"}),
        html.H3(value, style={"color": color, "margin": "5px 0 0 0"}),
    ])
