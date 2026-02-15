import asyncio
import os
import time
from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual import events
from textual.containers import Container, VerticalScroll
from textual.theme import Theme, BUILTIN_THEMES
from textual.reactive import reactive
from textual.widgets import Button, Footer, Input, SelectionList, Static, TabbedContent, TabPane
from rich.console import Group
from rich.text import Text

from beacon.services.logs import LogTailer
from beacon.services.pricing import PricingClient
from beacon.services.rpc import RpcClient
from beacon.services.system import SystemClient

# High-contrast and vivid themes
THEME_HIGH_CONTRAST_DARK = Theme(
    name="beacon-high-contrast-dark",
    primary="#00d4ff",
    secondary="#00ff88",
    accent="#ff6b00",
    foreground="#e0e0e0",
    background="#0d0d0d",
    surface="#1a1a1a",
    panel="#252525",
    success="#00ff00",
    warning="#ffaa00",
    error="#ff4444",
    dark=True,
)

THEME_HIGH_CONTRAST_LIGHT = Theme(
    name="beacon-high-contrast-light",
    primary="#0066cc",
    secondary="#008844",
    accent="#cc4400",
    foreground="#1a1a1a",
    background="#f5f5f5",
    surface="#ffffff",
    panel="#e8e8e8",
    success="#008800",
    warning="#aa6600",
    error="#cc0000",
    dark=False,
)

THEME_VIVID = Theme(
    name="beacon-vivid",
    primary="#00bfff",
    secondary="#7b68ee",
    accent="#ff1493",
    foreground="#f0f0f0",
    background="#1c1c2e",
    surface="#2d2d44",
    panel="#363656",
    success="#32cd32",
    warning="#ffd700",
    error="#ff4500",
    dark=True,
)


class CustomHeader(Static):
    """Custom header with title and local time display."""
    
    DEFAULT_CSS = """
    CustomHeader {
        dock: top;
        width: 100%;
        background: $boost;
        color: $text;
        height: 1;
    }
    """
    
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.indicator_state = "green"  # green, yellow, blue
        self._reset_timer = None
    
    def on_mount(self) -> None:
        """Set up clock update interval."""
        self.update_clock()
        self.set_interval(1.0, self.update_clock)
    
    def set_indicator(self, state: str) -> None:
        """Set the indicator state and auto-reset after 1 second."""
        self.indicator_state = state
        if self._reset_timer:
            self._reset_timer.stop()
        if state != "green":
            self._reset_timer = self.set_timer(1.0, self.reset_indicator)
    
    def reset_indicator(self) -> None:
        """Reset indicator to green."""
        self.indicator_state = "green"
    
    def update_clock(self) -> None:
        """Update the clock display."""
        now = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y  %I:%M:%S %p")
        title = self.app.title if hasattr(self.app, 'title') else "Beacon"
        
        # Select emoji based on state
        indicator_emoji = {
            "green": "🟢",
            "yellow": "🟡",
            "blue": "🔵"
        }.get(self.indicator_state, "🟢")
        
        # Center title and right-align time with indicator
        try:
            width = self.size.width
            time_with_indicator = f"{time_str} {indicator_emoji}"
            time_len = len(time_with_indicator)
            title_len = len(title)
            
            # Calculate centered position for title
            title_start = (width - title_len) // 2
            
            # Build the display string
            line = [' '] * width
            
            # Place centered title
            for i, char in enumerate(title):
                pos = title_start + i
                if 0 <= pos < width:
                    line[pos] = char
            
            # Place right-aligned time with indicator
            time_start = width - time_len - 1
            for i, char in enumerate(time_with_indicator):
                pos = time_start + i
                if 0 <= pos < width:
                    line[pos] = char
            
            self.update(''.join(line))
        except:
            self.update(f" {title}  {time_str} {indicator_emoji}")


class StatusBar(Static):
    def __init__(self) -> None:
        super().__init__()
        self.node_status = "unknown"
        self.block_height = "-"
        self.staking = "unknown"
        self.sync_monitor = "unknown"
        self.theme_name = "beacon-high-contrast-dark"

    def render(self) -> str:
        return (
            f"Node: {self.node_status} | Height: {self.block_height} | "
            f"Staking: {self.staking} | SyncMon: {self.sync_monitor} | Theme: {self.theme_name}"
        )


class KeyValuePanel(Static):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title
        self.lines: list[str] = []

    def update_lines(self, lines: list[str]) -> None:
        self.lines = lines
        self.update(self.render())

    def render(self) -> str:
        content = "\n".join(self.lines) if self.lines else "... loading"
        return f"[{self.title}]\n{content}"


class CardPanel(Static):
    def __init__(self, title: str, accent_class: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.title = title
        self.accent_class = accent_class
        self.border_title = title
        self.lines: list[str] = []
        self.add_class("card")
        self.add_class(accent_class)

    def update_lines(self, lines: list[str]) -> None:
        self.lines = lines
        self.update(self.render())

    def render(self) -> str:
        content = "\n".join(self.lines) if self.lines else "... loading"
        return content


class HeaderlessCardPanel(CardPanel):
    def render(self) -> str:
        return "\n".join(self.lines) if self.lines else "... loading"


class StorageCapabilityPanel(VerticalScroll):
    """Storage card with column layout and alternating row colors."""

    LABEL_WIDTH = 10

    def __init__(self, title: str, accent_class: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.border_title = title
        self.border_title_align = ("left", "top")
        self.add_class("card")
        self.add_class(accent_class)
        self._content = Static("... loading", classes="network-row-text")

    def compose(self) -> ComposeResult:
        yield self._content

    def update_lines(self, lines: list[str]) -> None:
        if not lines:
            self._content.update("... loading")
            return
        formatted: list[str] = []
        for line in lines:
            if ": " in line:
                label, value = line.split(": ", 1)
                formatted.append(
                    f"{label.strip():<{self.LABEL_WIDTH}} {value.strip()}"
                )
            else:
                formatted.append(line)
        texts = [
            Text(ln, style="dim" if i % 2 == 1 else "")
            for i, ln in enumerate(formatted)
        ]
        self._content.update(Group(*texts))


class BlockStatsPanel(VerticalScroll):
    """Block Statistics card with alternating row colors."""

    def __init__(self, title: str, accent_class: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.border_title = title
        self.border_title_align = ("left", "top")
        self.border_subtitle = "5 minute block target"
        self.border_subtitle_align = ("right", "bottom")
        self.add_class("card")
        self.add_class(accent_class)
        self._content = Static("... loading", classes="network-row-text")

    def compose(self) -> ComposeResult:
        yield self._content

    def update_lines(self, lines: list[str]) -> None:
        if not lines:
            self._content.update("... loading")
            return
        texts = [
            Text(line, style="dim" if i % 2 == 1 else "")
            for i, line in enumerate(lines)
        ]
        self._content.update(Group(*texts))


class StakingPanel(VerticalScroll):
    """Staking card with alternating row colors like Peers."""

    def __init__(self, title: str, accent_class: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.title = title
        self.accent_class = accent_class
        self.border_title = title
        self.border_title_align = ("left", "top")
        self.add_class("card")
        self.add_class(accent_class)
        self._content = Static("... loading", classes="network-row-text")

    def compose(self) -> ComposeResult:
        yield self._content

    def update_lines(self, lines: list[str]) -> None:
        if not lines:
            self._content.update("... loading")
            return
        texts = [
            Text(line, style="dim" if i % 2 == 1 else "")
            for i, line in enumerate(lines)
        ]
        self._content.update(Group(*texts))


class PeerListPanel(VerticalScroll):
    def __init__(self, title: str, accent_class: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.title = title
        self.accent_class = accent_class
        self.border_title = title
        self.border_title_align = ("left", "top")
        self.add_class("card")
        self.add_class(accent_class)
        self._content = Static("... loading", classes="network-row-text")

    def compose(self) -> ComposeResult:
        yield self._content

    def update_lines(self, lines: list[str], peer_count: int | None = None) -> None:
        if peer_count is not None:
            self.border_title = f"{self.title} ({peer_count})"
        else:
            self.border_title = self.title
        if not lines:
            self._content.update("... loading")
            return
        texts = [
            Text(line, style="dim" if i % 2 == 1 else "")
            for i, line in enumerate(lines)
        ]
        self._content.update(Group(*texts))


class AddressListPanel(VerticalScroll):
    """Addresses card with colored row layout."""

    def __init__(self, title: str, accent_class: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.title = title
        self.accent_class = accent_class
        self.border_title = title
        self.border_title_align = ("left", "top")
        self.add_class("card")
        self.add_class(accent_class)
        self._content = Static("... loading", classes="network-row-text")

    def compose(self) -> ComposeResult:
        yield self._content

    def update_lines(
        self,
        addr_list: list[dict],
        address_count: int | None = None,
        wallet_balance: object = None,
    ) -> None:
        if address_count is not None:
            self.border_title = f"💼 Addresses ({address_count})"
        else:
            self.border_title = self.title
        if isinstance(wallet_balance, (int, float)):
            self.border_subtitle = f"Wallet Balance: {wallet_balance:.8f}"
        else:
            self.border_subtitle = "Wallet Balance: -"
        self.border_subtitle_align = ("left", "bottom")
        if not addr_list:
            self._content.update("No addresses found")
            return
        lines: list[str] = []
        for e in addr_list:
            addr = str(e.get("address", ""))
            amount = e.get("amount", 0)
            txids = e.get("txids", [])
            confirmations = e.get("confirmations", 0)
            bal = f"{amount:.8f}" if isinstance(amount, (int, float)) else "0.00000000"
            tx_count = len(txids) if isinstance(txids, list) else 0
            status = "-" if tx_count == 0 else ("Pending" if confirmations == 0 else ("Immature" if 0 < confirmations < 31 else "Trusted"))
            lines.append(f"{addr[:50]:<36} {bal:>12} {str(tx_count) if tx_count else '-':>4} {status}")
        texts = [
            Text(line, style="dim" if i % 2 == 1 else "")
            for i, line in enumerate(lines)
        ]
        self._content.update(Group(*texts))


class NetworkActivityPanel(VerticalScroll):
    def __init__(self, title: str, accent_class: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.title = title
        self.accent_class = accent_class
        self.border_title = title
        self.add_class("card")
        self.add_class(accent_class)
        self._content = Static("... loading", classes="network-row-text")
        self._heights: list[int] = []

    def compose(self) -> ComposeResult:
        yield self._content

    def update_entries(
        self,
        entries: list[tuple[int, str]],
        count: int | None = None,
        time_since_latest: str | None = None,
    ) -> None:
        self._heights = [height for height, _ in entries]
        if count is not None:
            self.border_title = f"{self.title} ({count})"
        else:
            self.border_title = self.title
        if time_since_latest:
            self.border_subtitle = time_since_latest
            self.border_subtitle_align = ("right", "bottom")
        else:
            self.border_subtitle = ""
        if not entries:
            self._content.update("... loading")
            return
        lines = [f"{height:>7}  {line_display}" for height, line_display in entries]
        texts = [
            Text(line, style="dim" if i % 2 == 1 else "")
            for i, line in enumerate(lines)
        ]
        self._content.update(Group(*texts))


class SendCard(VerticalScroll):
    """Card for pasting address and entering amount to send LYNX."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.border_title = "📤 Send LYNX"
        self.border_title_align = ("left", "top")
        self.add_class("card")
        self.add_class("wallet")
        self._address_input = Input(
            placeholder="Paste destination address",
            id="send-address",
        )
        self._amount_input = Input(
            placeholder="Amount in LYNX",
            id="send-amount",
            type="number",
        )
        self._status = Static("", id="send-status")

    def compose(self) -> ComposeResult:
        yield Static("Address:", classes="send-label")
        yield self._address_input
        yield Static("Amount:", classes="send-label")
        yield self._amount_input
        yield self._status
        yield Button("Send", id="send-button", variant="primary")

    def get_address(self) -> str:
        return self._address_input.value

    def get_amount(self) -> str:
        return self._amount_input.value

    def set_status(self, text: str) -> None:
        self._status.update(text)

    def clear_form(self) -> None:
        self._address_input.value = ""
        self._amount_input.value = ""
        self._status.update("")


class TimezoneCard(VerticalScroll):
    def __init__(
        self,
        title: str,
        timezone_select: SelectionList,
        timezone_apply: Button,
        timezone_status: Static,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.border_title = title
        self.add_class("card")
        self._timezone_select = timezone_select
        self._timezone_apply = timezone_apply
        self._timezone_status = timezone_status

    def compose(self) -> ComposeResult:
        yield self._timezone_status
        yield Static("", id="timezone-status-spacer")
        yield self._timezone_select
        yield Static("", id="timezone-spacer")
        with Container(id="timezone-actions"):
            yield self._timezone_apply


class LogsPanel(Static):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title
        self.lines: list[str] = []

    def update_lines(self, lines: list[str]) -> None:
        self.lines = lines[-200:]
        self.update(self.render())

    def render(self) -> str:
        content = "\n".join(self.lines) if self.lines else "No log output yet."
        return f"[{self.title}]\n{content}"


# All built-in themes + custom themes for cycle
THEME_ORDER = list(BUILTIN_THEMES.keys()) + [
    "beacon-high-contrast-dark",
    "beacon-high-contrast-light",
    "beacon-vivid",
]


class LynxTuiApp(App):
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh_all", "Refresh"),
        ("s", "toggle_staking", "Toggle Staking"),
        ("t", "cycle_theme", "Theme"),
        ("c", "create_new_address", "New Address"),
        ("x", "toggle_send_card", "Send Card"),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }
    #body {
        height: 1fr;
    }
    #overview-body {
        layout: vertical;
        height: 1fr;
    }
    #overview-grid {
        layout: grid;
        grid-size: 6;
        grid-gutter: 1 1;
        height: 1fr;
        width: 1fr;
    }
    #overview-grid > * {
        column-span: 2;
    }
    #overview-pricing-column {
        layout: horizontal;
    }
    #overview-pricing-column > * {
        width: 1fr;
    }
    #overview-system-storage-column {
        layout: horizontal;
    }
    #overview-system-storage-column > * {
        width: 1fr;
    }
    #overview-network,
    #overview-peers {
        min-height: 22;
        height: 1fr;
        scrollbar-visibility: visible;
        scrollbar-gutter: stable;
        overflow-y: scroll;
    }
    #overview-node-status {
        min-height: 6;
        height: auto;
    }
    #overview-addresses {
        min-height: 10;
        height: 1fr;
        scrollbar-visibility: visible;
        scrollbar-gutter: stable;
    }
    #send-card {
        min-height: 14;
        height: auto;
    }
    #send-card .send-label {
        height: 1;
        margin-top: 1;
    }
    #send-card Input {
        margin-bottom: 0;
    }
    #send-card #send-address {
        width: 35;
        max-width: 35;
    }
    #send-card #send-amount {
        width: 15;
        max-width: 15;
        margin-bottom: 1;
    }
    #send-card #send-status {
        height: auto;
        min-height: 1;
        margin-bottom: 1;
    }
    #status-bar {
        height: 1;
    }
    .card {
        padding: 1 1;
        border: round $primary-darken-2;
        height: auto;
        min-height: 6;
    }
    .card.tall {
        row-span: 2;
        min-height: 12;
    }
    .card.compact {
        min-height: 4;
    }
    .card.node {
        color: $primary-lighten-2;
    }
    .card.wallet {
        color: $success-lighten-2;
    }
    .card.staking {
        color: $warning-lighten-2;
    }
    .card.network {
        color: $secondary-lighten-2;
    }
    .card.activity {
        color: $accent-lighten-2;
    }
    .card.pricing {
        color: $accent-lighten-2;
    }
    .card.sync {
        color: $error-lighten-2;
    }
    .card.node .row-alt {
        color: $primary-darken-2;
    }
    .card.wallet .row-alt {
        color: $success-darken-2;
    }
    .card.staking .row-alt {
        color: $warning-darken-2;
    }
    .card.network .row-alt {
        color: $secondary-darken-2;
    }
    .card.activity .row-alt {
        color: $accent-darken-2;
    }
    .card.pricing .row-alt {
        color: $accent-darken-2;
    }
    .card.sync .row-alt {
        color: $error-darken-2;
    }
    #overview-block-stats {
        min-height: 6;
        border: solid $primary-darken-2;
    }
    #settings {
        layout: vertical;
        padding: 1 2;
    }
    #timezone-card {
        width: 50;
        height: 22;
    }
    #timezone-select {
        width: 1fr;
        height: 12;
    }
    #timezone-actions {
        layout: horizontal;
        height: auto;
        align-horizontal: right;
        padding-right: 1;
    }
    #timezone-spacer {
        height: 1;
    }
    #timezone-status-spacer {
        height: 1;
    }
    #timezone-status {
        padding-left: 1;
        height: auto;
    }
    #network-rows {
        layout: vertical;
    }
    .network-row {
        layout: horizontal;
        height: auto;
    }
    .network-height {
        width: 7;
        text-align: right;
    }
    .network-spacer {
        width: 3;
    }
    .network-row-text {
        width: 1fr;
        text-wrap: nowrap;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.rpc = RpcClient()
        self.pricing = PricingClient()
        self.logs = LogTailer()
        self.system = SystemClient()
        self._node_name: str | None = None
        self._node_version_line: str | None = None
        self.title = "...loading Beacon for the Lynx Data Storage Network"

        self.node_status_card = StakingPanel("🏆 Staking", "staking", id="overview-node-status")
        self.overview_network = NetworkActivityPanel(
            "📡 Network Activity", "activity", id="overview-network"
        )
        self.overview_network.add_class("wide")
        self.overview_peers = PeerListPanel("🌐 Peers", "network", id="overview-peers")
        self.overview_addresses = AddressListPanel(
            "💼 Addresses", "wallet", id="overview-addresses"
        )
        self.send_card = SendCard(id="send-card")
        self.overview_mempool = CardPanel("Mempool", "sync")
        self.overview_system = CardPanel("💻 System Utilization", "node")
        self.overview_pricing = CardPanel("💰 Pricing", "pricing")
        self.overview_value = CardPanel("💵 Value", "pricing")
        self.overview_storage = StorageCapabilityPanel(
            "💾 Storage Capability", "node"
        )

        self.block_stats_card = BlockStatsPanel(
            "🧱 Block Statistics", "sync", id="overview-block-stats"
        )
        self.logs_panel = LogsPanel("Debug Log")
        self.status_bar = StatusBar()
        self.timezone_select = SelectionList(id="timezone-select")
        self.timezone_apply = Button("Apply", id="timezone-apply")
        self.timezone_status = Static("", id="timezone-status")
        self.timezone_card = TimezoneCard(
            "Timezone",
            self.timezone_select,
            self.timezone_apply,
            self.timezone_status,
            id="timezone-card",
        )
        self.header = CustomHeader()
        self._staking_enabled = None  # None = unknown, True = enabled, False = disabled

    @staticmethod
    def _format_optional(value: object, empty: str = "-") -> str:
        if value is None:
            return empty
        if isinstance(value, str) and not value.strip():
            return empty
        return str(value)

    @staticmethod
    def _format_bool(value: object) -> str:
        if value is None:
            return "-"
        return "yes" if bool(value) else "no"

    @staticmethod
    def _format_units(value: object, units: list[str]) -> str:
        try:
            size = float(value)
        except (TypeError, ValueError):
            return "-"
        unit_index = 0
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1
        if size >= 100:
            formatted = f"{size:.0f}"
        elif size >= 10:
            formatted = f"{size:.1f}"
        else:
            formatted = f"{size:.2f}"
        return f"{formatted} {units[unit_index]}"

    @classmethod
    def _format_bytes(cls, value: object) -> str:
        return cls._format_units(value, ["B", "KB", "MB", "GB", "TB", "PB"])

    @classmethod
    def _format_hashrate(cls, value: object) -> str:
        return cls._format_units(value, ["H/s", "KH/s", "MH/s", "GH/s", "TH/s", "PH/s", "EH/s"])

    @staticmethod
    def _format_seconds(value: object) -> str:
        try:
            total = int(float(value))
        except (TypeError, ValueError):
            return "-"
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"

    @staticmethod
    def _format_timestamp(value: object) -> str:
        try:
            ts = int(float(value))
        except (TypeError, ValueError):
            return "-"
        if ts <= 0:
            return "-"
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    @staticmethod
    def _short_hash(value: object, length: int = 12) -> str:
        if not isinstance(value, str) or not value:
            return "-"
        return value[:length]

    @staticmethod
    def _format_capacity_kb(value: object) -> str:
        """Format a value in KB; if > 1024, display in MB."""
        try:
            kb = float(value)
        except (TypeError, ValueError):
            return "-"
        if kb > 1024:
            mb = kb / 1024
            return f"{mb:.1f} MB"
        return f"{kb:.0f} KB"

    @staticmethod
    def _format_bytes(value: object) -> str:
        """Format bytes; use GB/MB as appropriate."""
        try:
            n = float(value)
        except (TypeError, ValueError):
            return "-"
        if n >= 1024**3:
            return f"{n / 1024**3:.1f} GB"
        if n >= 1024**2:
            return f"{n / 1024**2:.1f} MB"
        return f"{n / 1024:.0f} KB"

    @staticmethod
    def _parse_capacity_to_lines(capacity_data: object) -> list[str]:
        """Extract numeric values (KB) from capacity JSON; handle flat or nested structures."""

        def extract_pairs(obj: object, prefix: str = "") -> list[tuple[str, float]]:
            pairs: list[tuple[str, float]] = []
            if isinstance(obj, dict):
                for key, val in obj.items():
                    label = key.replace("_", " ").replace("-", " ").title()
                    full_label = f"{prefix} {label}".strip() if prefix else label
                    if isinstance(val, (int, float)):
                        pairs.append((full_label, float(val)))
                    elif isinstance(val, dict):
                        pairs.extend(extract_pairs(val, full_label))
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    sub_prefix = f"{prefix} #{i + 1}" if prefix else ("" if len(obj) == 1 else f"#{i + 1}")
                    pairs.extend(extract_pairs(item, sub_prefix))
            elif isinstance(obj, (int, float)):
                pairs.append((prefix or "Capacity", float(obj)))
            return pairs

        if capacity_data is None:
            return ["Unavailable"]

        pairs = extract_pairs(capacity_data)
        if not pairs:
            return ["Unavailable"]
        def clean_label(lbl: str) -> str:
            return lbl.replace(" (Kb)", "").replace(" (kb)", "").replace(" (KB)", "")
        return [f"{clean_label(label)}: {LynxTuiApp._format_capacity_kb(val)}" for label, val in pairs]

    def compose(self) -> ComposeResult:
        yield self.header
        with Container(id="body"):
            with TabbedContent():
                with TabPane("Overview"):
                    with Container(id="overview-body"):
                        with Container(id="overview-grid"):
                            yield self.overview_network
                            yield self.overview_peers
                            yield self.overview_addresses
                            yield self.send_card
                            yield self.node_status_card
                            yield self.block_stats_card
                            yield self.overview_mempool
                            with Container(id="overview-system-storage-column"):
                                yield self.overview_system
                                yield self.overview_storage
                            with Container(id="overview-pricing-column"):
                                yield self.overview_pricing
                                yield self.overview_value
                with TabPane("Logs"):
                    yield self.logs_panel
                with TabPane("Settings"):
                    with Container(id="settings"):
                        yield self.timezone_card
        yield self.status_bar
        yield Footer()

    async def on_mount(self) -> None:
        # Register high-contrast themes
        self.register_theme(THEME_HIGH_CONTRAST_DARK)
        self.register_theme(THEME_HIGH_CONTRAST_LIGHT)
        self.register_theme(THEME_VIVID)

        # Set default theme and sync status bar
        self.theme = "beacon-high-contrast-dark"
        self.status_bar.theme_name = "beacon-high-contrast-dark"
        self.status_bar.refresh()
        self.status_bar.refresh()

        # Initialize staking state from config file
        staking_from_config = await asyncio.get_event_loop().run_in_executor(
            None, self.rpc.get_staking_enabled_from_config
        )
        if staking_from_config is not None:
            self._staking_enabled = staking_from_config
        
        self.set_timer(0.6, self.refresh_node_version)
        self.set_timer(0.1, self.refresh_data)
        self.set_timer(0.2, self.refresh_logs)
        self.set_timer(0.3, self.refresh_block_stats)
        self.set_timer(0.4, self.refresh_timezone_list)
        self.set_timer(0.5, self.refresh_timezone)
        self.set_timer(0.8, lambda: self.set_interval(3600, self.refresh_node_version))
        self.set_timer(1.0, lambda: self.set_interval(5, self.auto_refresh_data))
        self.set_timer(1.2, lambda: self.set_interval(4, self.refresh_logs))
        self.set_timer(1.5, lambda: self.set_interval(60, self.refresh_block_stats))
        self.set_timer(2.0, self.refresh_storage_capacity)
        self.set_timer(2.0, lambda: self.set_interval(900, self.refresh_storage_capacity))

    def _loading_message(self) -> str:
        name = self._node_name or "Blockchain"
        return f"...please wait while loading the {name} Beacon"

    async def refresh_node_version(self) -> None:
        node_version = await asyncio.get_event_loop().run_in_executor(None, self.rpc.fetch_node_version)
        if isinstance(node_version, dict):
            name = node_version.get("name")
            version_line = node_version.get("version_line")
            if isinstance(name, str) and name.strip():
                self._node_name = name.strip()
            if isinstance(version_line, str) and version_line.strip():
                self._node_version_line = version_line.strip()
        if self._node_name:
            self.title = f"{self._node_name} Beacon for the Lynx Data Storage Network"

    async def refresh_timezone(self) -> None:
        current = await asyncio.get_event_loop().run_in_executor(None, self.system.get_timezone)
        if current and current != "unknown":
            self.timezone_status.update(f"Current timezone: {current}")
        else:
            self.timezone_status.update("Current timezone: unknown")

    async def refresh_timezone_list(self) -> None:
        timezones = await asyncio.get_event_loop().run_in_executor(None, self.system.list_timezones)
        if not timezones:
            self.timezone_status.update("Unable to load timezone list.")
            return
        current = await asyncio.get_event_loop().run_in_executor(None, self.system.get_timezone)
        self.timezone_select.clear_options()
        options = [(tz, tz, tz == current) for tz in timezones]
        self.timezone_select.add_options(options)

    def action_toggle_send_card(self) -> None:
        """Toggle Send card visibility (bound to x key)."""
        self.send_card.display = not self.send_card.display

    async def action_create_new_address(self) -> None:
        """Create a new receiving address (bound to c key)."""
        try:
            address = await asyncio.get_event_loop().run_in_executor(
                None, self.rpc.getnewaddress
            )
            if address:
                await self.refresh_data()
        except Exception:
            pass

    async def _handle_send(self) -> None:
        """Handle Send button press: validate, call RPC, notify, refresh."""
        try:
            send_card = self.query_one("#send-card", SendCard)
        except Exception:
            return
        address = send_card.get_address()
        amount_str = send_card.get_amount()
        if not address.strip():
            send_card.set_status("Enter an address")
            self.notify("Enter a destination address", title="Send", severity="warning")
            return
        if not amount_str.strip():
            send_card.set_status("Enter an amount")
            self.notify("Enter an amount", title="Send", severity="warning")
            return
        try:
            amount = float(amount_str)
        except ValueError:
            send_card.set_status("Invalid amount")
            self.notify("Invalid amount", title="Send", severity="error")
            return
        if amount <= 0:
            send_card.set_status("Amount must be positive")
            self.notify("Amount must be positive", title="Send", severity="error")
            return
        send_card.set_status("Sending...")
        success, msg = await asyncio.get_event_loop().run_in_executor(
            None, self.rpc.sendtoaddress, address, amount
        )
        if success:
            send_card.clear_form()
            send_card.set_status("")
            self.notify(msg if len(msg) <= 24 else f"{msg[:21]}...", title="Sent")
            await self.refresh_data()
        else:
            send_card.set_status(msg[:40] + "..." if len(msg) > 40 else msg)
            self.notify(msg, title="Send failed", severity="error")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-button":
            await self._handle_send()
            return
        if event.button.id != "timezone-apply":
            return
        selected = self.timezone_select.selected
        if not selected:
            self.timezone_status.update("Error: select a timezone.")
            return
        timezone_name = str(selected[0]).strip()
        self.timezone_status.update("Updating timezone...")
        success, message = await asyncio.get_event_loop().run_in_executor(
            None, self.system.set_timezone, timezone_name
        )
        status = "OK" if success else "Error"
        self.timezone_status.update(f"{status}: {message}")
        if success:
            # Reload timezone in the Python process
            os.environ['TZ'] = timezone_name
            time.tzset()
            # Refresh displays to show new timezone
            await self.refresh_timezone()
            await self.refresh_logs()

    async def action_refresh_all(self) -> None:
        self.header.set_indicator("blue")
        self.timezone_status.update("Refreshing...")
        await asyncio.gather(
            self.refresh_node_version(),
            self.refresh_data(),
            self.refresh_logs(),
            self.refresh_timezone_list(),
            self.refresh_timezone(),
            self.refresh_storage_capacity(),
        )
        self.timezone_status.update("Refresh complete.")

    def action_cycle_theme(self) -> None:
        """Cycle through available themes (t key)."""
        current = getattr(self, "theme", "beacon-high-contrast-dark") or "beacon-high-contrast-dark"
        try:
            idx = THEME_ORDER.index(current)
        except ValueError:
            idx = 0
        next_idx = (idx + 1) % len(THEME_ORDER)
        next_theme = THEME_ORDER[next_idx]
        try:
            self.theme = next_theme
            self.status_bar.theme_name = next_theme
            self.status_bar.refresh()
        except Exception:
            pass

    async def action_toggle_staking(self) -> None:
        """Toggle staking on/off using setstaking RPC command."""
        try:
            # Determine new state
            if self._staking_enabled is None or not self._staking_enabled:
                new_state = True
                command = "true"
            else:
                new_state = False
                command = "false"
            
            # Call setstaking via RPC
            result = await asyncio.get_event_loop().run_in_executor(
                None, self.rpc._safe_call, "setstaking", [command]
            )
            
            # Update local state
            if result == "true" or result is True:
                self._staking_enabled = True
                self.status_bar.staking = "enabled"
            elif result == "false" or result is False:
                self._staking_enabled = False
                self.status_bar.staking = "disabled"
            
            self.status_bar.refresh()
        except Exception as e:
            self.status_bar.staking = f"error: {str(e)[:20]}"
            self.status_bar.refresh()

    def on_selection_list_selection_toggled(self, event: SelectionList.SelectionToggled) -> None:
        if event.selection_list.id != "timezone-select":
            return
        if len(event.selection_list.selected) <= 1:
            return
        selected_value = event.selection.value
        event.selection_list.deselect_all()
        event.selection_list.select(selected_value)

    def _schedule_update(self, delay: float, callback: callable) -> None:
        self.set_timer(delay, callback)
    
    async def auto_refresh_data(self) -> None:
        """Automatic refresh with yellow indicator."""
        self.header.set_indicator("yellow")
        await self.refresh_data()

    async def refresh_data(self) -> None:
        data = await asyncio.get_event_loop().run_in_executor(None, self.rpc.fetch_snapshot)
        price = await asyncio.get_event_loop().run_in_executor(None, self.pricing.fetch_price_usd)
        block_height_cli = await asyncio.get_event_loop().run_in_executor(
            None, self.rpc.fetch_block_count_cli
        )

        blockchain_info = data.get("blockchain_info")
        blockchain_info = blockchain_info if isinstance(blockchain_info, dict) else {}
        mempool_info = data.get("mempool_info")
        mempool_info = mempool_info if isinstance(mempool_info, dict) else {}
        mining_info = data.get("mining_info")
        mining_info = mining_info if isinstance(mining_info, dict) else {}
        network_info = data.get("network_info")
        network_info = network_info if isinstance(network_info, dict) else {}
        net_totals = data.get("net_totals")
        net_totals = net_totals if isinstance(net_totals, dict) else {}
        peer_info = data.get("peer_info")
        peer_info = peer_info if isinstance(peer_info, list) else []
        memory_info = data.get("memory_info")
        memory_info = memory_info if isinstance(memory_info, dict) else {}
        rpc_info = data.get("rpc_info")
        rpc_info = rpc_info if isinstance(rpc_info, dict) else {}
        wallet_info = data.get("wallet_info")
        wallet_info = wallet_info if isinstance(wallet_info, dict) else {}
        balances = data.get("balances")
        balances = balances if isinstance(balances, dict) else {}
        chain_tips = data.get("chain_tips")
        chain_tips = chain_tips if isinstance(chain_tips, list) else []

        difficulty = data.get("difficulty")
        if difficulty is None:
            difficulty = blockchain_info.get("difficulty") or mining_info.get("difficulty")
        pos_difficulty = None
        pow_difficulty = None
        if isinstance(difficulty, dict):
            pos_difficulty = (
                difficulty.get("proof-of-stake")
                or difficulty.get("pos")
                or difficulty.get("stake")
                or difficulty.get("pos_difficulty")
            )
            pow_difficulty = (
                difficulty.get("proof-of-work")
                or difficulty.get("pow")
                or difficulty.get("work")
                or difficulty.get("pow_difficulty")
            )
        else:
            pow_difficulty = difficulty
        network_hashps = data.get("network_hashps") or mining_info.get("networkhashps")
        connection_count = data.get("connection_count")
        if connection_count is None:
            connection_count = network_info.get("connections")

        tips_by_status: dict[str, int] = {}
        for tip in chain_tips:
            if not isinstance(tip, dict):
                continue
            status = tip.get("status", "unknown")
            tips_by_status[status] = tips_by_status.get(status, 0) + 1
        tips_summary = ", ".join(f"{key}:{value}" for key, value in tips_by_status.items())
        tips_summary = tips_summary if tips_summary else "-"

        inbound = 0
        outbound = 0
        ping_times: list[float] = []
        synced_blocks: list[int] = []
        synced_headers: list[int] = []
        for peer in peer_info:
            if not isinstance(peer, dict):
                continue
            if peer.get("inbound"):
                inbound += 1
            else:
                outbound += 1
            ping = peer.get("pingtime")
            if isinstance(ping, (int, float)):
                ping_times.append(float(ping))
            blocks = peer.get("synced_blocks")
            headers = peer.get("synced_headers")
            if isinstance(blocks, int):
                synced_blocks.append(blocks)
            if isinstance(headers, int):
                synced_headers.append(headers)
        ping_avg = sum(ping_times) / len(ping_times) if ping_times else None
        max_blocks = max(synced_blocks) if synced_blocks else None
        max_headers = max(synced_headers) if synced_headers else None

        memory_locked = memory_info.get("locked")
        memory_locked = memory_locked if isinstance(memory_locked, dict) else {}
        active_commands = rpc_info.get("active_commands")
        active_commands = active_commands if isinstance(active_commands, list) else []
        log_path = rpc_info.get("logpath")
        log_name = log_path.split("/")[-1] if isinstance(log_path, str) else "-"

        wallet_mine = balances.get("mine")
        wallet_mine = wallet_mine if isinstance(wallet_mine, dict) else {}

        network_entries, latest_block_time = self.logs.get_update_tip_entries(50)
        def fit_column(value: str, width: int) -> str:
            if len(value) <= width:
                return value.ljust(width)
            if width <= 1:
                return value[:width]
            return f"{value[: width - 1]}…"

        peer_rows: list[tuple[int, str]] = []
        addr_width = 22
        subver_width = 16
        synced_width = 19
        ping_width = 12
        for peer in peer_info:
            if not isinstance(peer, dict):
                continue
            addr = self._format_optional(peer.get("addr"))
            if ":" in addr:
                host, port = addr.rsplit(":", 1)
                if port.isdigit():
                    addr = host
            addr = addr.replace("[", "").replace("]", "")
            if addr.count(":") >= 2:
                addr = addr[:18] if len(addr) > 18 else addr
            subver = self._format_optional(peer.get("subver")).replace("/", "")
            synced_blocks = peer.get("synced_blocks")
            synced_value = synced_blocks if isinstance(synced_blocks, int) else -1
            synced = self._format_optional(synced_blocks)
            ping = peer.get("pingtime")
            ping_display = "-"
            if isinstance(ping, (int, float)):
                ping_display = f"{ping:.3f}s"
            addr_col = fit_column(addr, addr_width)
            subver_col = fit_column(subver, subver_width)
            synced_col = fit_column(f"synced: {synced}", synced_width)
            ping_col = fit_column(f"ping: {ping_display}", ping_width)
            line = f"{addr_col}{subver_col}{synced_col}{ping_col}"
            peer_rows.append((synced_value, line))
        peer_rows.sort(key=lambda row: row[0], reverse=True)
        peer_lines = [line for _, line in peer_rows]
        if not peer_lines:
            peer_lines = ["No peers connected."]
        peer_count = len(peer_info)
        
        # Get all addresses - merge data from both sources
        all_addresses = data.get("all_addresses", [])
        address_groups = data.get("address_groups", [])
        
        # Create a lookup for received address data (for TX count and confirmations)
        received_lookup = {}
        if isinstance(all_addresses, list):
            for addr_entry in all_addresses:
                if isinstance(addr_entry, dict):
                    addr = addr_entry.get("address")
                    if addr:
                        received_lookup[addr] = addr_entry
        
        address_lines: list[str] = []
        addr_list: list[dict] = []
        addr_width = 34
        bal_width = 16
        tx_width = 6
        status_width = 9
        address_count = 0
        
        # Use address_groups for current balances, merge with received data
        if isinstance(address_groups, list) and address_groups:
            # Convert to list with merged data
            for group in address_groups:
                if not isinstance(group, list):
                    continue
                for entry in group:
                    if not isinstance(entry, list) or len(entry) < 2:
                        continue
                    addr = str(entry[0])
                    current_balance = entry[1] if isinstance(entry[1], (int, float)) else 0
                    
                    # Look up TX data from received addresses
                    received_data = received_lookup.get(addr, {})
                    txids = received_data.get("txids", [])
                    confirmations = received_data.get("confirmations", 0)
                    
                    addr_list.append({
                        "address": addr,
                        "amount": current_balance,
                        "txids": txids,
                        "confirmations": confirmations
                    })
        
        # Include addresses from all_addresses (listreceivedbyaddress include_empty=true)
        # that aren't in address_groups - e.g. newly created empty addresses
        seen_addrs = {a["address"] for a in addr_list}
        if isinstance(all_addresses, list):
            for addr_entry in all_addresses:
                if not isinstance(addr_entry, dict):
                    continue
                addr = addr_entry.get("address")
                if not addr or addr in seen_addrs:
                    continue
                seen_addrs.add(addr)
                txids = addr_entry.get("txids", [])
                confirmations = addr_entry.get("confirmations", 0)
                addr_list.append({
                    "address": addr,
                    "amount": 0,
                    "txids": txids,
                    "confirmations": confirmations
                })
        
        # Sort by balance descending
        addr_list = sorted(addr_list, key=lambda x: x.get("amount", 0), reverse=True)
        
        for addr_entry in addr_list:
            addr = addr_entry["address"]
            addr_display = addr[:34] if len(addr) > 34 else addr
            amount = addr_entry["amount"]
            txids = addr_entry.get("txids", [])
            confirmations = addr_entry.get("confirmations", 0)
            
            tx_count = len(txids) if isinstance(txids, list) else 0
            
            # Determine status based on confirmations
            if tx_count == 0:
                status = "-"
            elif confirmations == 0:
                status = "Pending"
            elif 0 < confirmations < 31:
                status = "Immature"
            else:
                status = "Trusted"
            
            if isinstance(amount, (int, float)):
                bal_display = f"{amount:.8f}"
            else:
                bal_display = "0.00000000"
            
            tx_display = str(tx_count) if tx_count > 0 else "-"
            
            line = f"{addr_display:<{addr_width}} {bal_display:>{bal_width}}   {tx_display:>{tx_width}}  {status:<{status_width}}"
            address_lines.append(line)
            address_count += 1
        
        if not address_lines:
            address_lines = ["No addresses found in wallet."]
            
        mempool_lines = [
            f"Txs: {self._format_optional(mempool_info.get('size'))}",
            f"Bytes: {self._format_bytes(mempool_info.get('bytes'))}",
            f"Usage: {self._format_bytes(mempool_info.get('usage'))}",
            f"Max: {self._format_bytes(mempool_info.get('maxmempool'))}",
            f"Min fee: {self._format_optional(mempool_info.get('mempoolminfee'))}",
        ]
        stakes_24h = data.get("stakes_24h") or 0
        stakes_7d = data.get("stakes_7d") or 0
        yield_24h = data.get("yield_24h") or 0
        yield_7d = data.get("yield_7d") or 0
        immature_utxos = data.get("immature_utxos") or 0
        node_status_lines = [
            f"Stakes won in last 24 hours: {stakes_24h}",
            f"24-hour yield rate (stakes/blocks): {yield_24h}%",
            f"Stakes won in last 7 days: {stakes_7d}",
            f"7-day yield rate (stakes/blocks): {yield_7d}%",
            f"Immature transactions (< 31 confirmations): {immature_utxos}",
        ]
        wallet_overview_lines = [
            f"Trusted: {self._format_optional(wallet_mine.get('trusted', data.get('wallet_balance')))}",
            f"Pending: {self._format_optional(wallet_mine.get('untrusted_pending'))}",
            f"Immature: {self._format_optional(wallet_mine.get('immature'))}",
            f"Unconf: {self._format_optional(data.get('unconfirmed_balance'))}",
            f"Tx count: {self._format_optional(wallet_info.get('txcount'))}",
            f"Keypool: {self._format_optional(wallet_info.get('keypoolsize'))}",
        ]
        
        # Get system utilization stats
        sys_stats = self.system.get_system_stats()
        cpu_pct = sys_stats.get('cpu_percent', 0)
        cpu_cores = sys_stats.get('cpu_cores', 0)
        load_avg = sys_stats.get('load_avg', [0, 0, 0])
        mem_pct = sys_stats.get('memory_percent', 0)
        mem_used = sys_stats.get('memory_used_gb', 0)
        mem_total = sys_stats.get('memory_total_gb', 0)
        swap_used = sys_stats.get('swap_used_gb', 0)
        swap_total = sys_stats.get('swap_total_gb', 0)
        
        system_overview_lines = [
            f"Uptime      {sys_stats.get('uptime', '-')}",
            f"CPU         {cpu_pct:.1f}% cores {cpu_cores}",
            f"Load        {load_avg[0]:.2f} {load_avg[1]:.2f} {load_avg[2]:.2f}",
            f"Memory      {mem_pct:.2f}%",
            f"            {mem_used:.2f}GB/{mem_total:.0f}GB",
            f"Swap        {swap_used:.2f}GB/{swap_total:.0f}GB",
            f"Network     Dn {sys_stats.get('network_down_kb', 0):.2f}KB",
            f"            Up {sys_stats.get('network_up_kb', 0):.2f}KB",
        ]
        
        # Get wallet balance for pricing calculations
        wallet_balance = data.get("wallet_balance", 0)
        balance_value = 0.0
        
        # Extract numeric price from string (e.g., "$0.00000123" -> 0.00000123)
        price_numeric = None
        if isinstance(price, str) and price.startswith("$"):
            try:
                price_numeric = float(price[1:])
            except (ValueError, IndexError):
                pass
        elif isinstance(price, (int, float)):
            price_numeric = float(price)
        
        if isinstance(wallet_balance, (int, float)) and price_numeric is not None:
            balance_value = wallet_balance * price_numeric
        
        pricing_lines = [
            f"Price per Coin: {price if price else '-'}",
            f"Balance:        {wallet_balance if isinstance(wallet_balance, (int, float)) else '-'}",
            f"Value:          ${balance_value:.2f}" if balance_value > 0 else "Value:          -",
        ]
        
        # Calculate value grid for different denominations
        value_lines = []
        if price_numeric is not None and price_numeric > 0:
            denominations = [(1, "1"), (10, "10"), (100, "100"), (1000, "1K"), (10000, "10K"), (100000, "100K"), (1000000, "1M")]
            for amount, label in denominations:
                value = amount * price_numeric
                if value >= 1000:
                    value_lines.append(f"{label:>6} coins  ${value:>10,.2f}")
                else:
                    value_lines.append(f"{label:>6} coins  ${value:>10.2f}")
        else:
            value_lines = ["Price data unavailable"]

        # Storage capability refreshed separately on 15-min interval

        # Time since latest block for Network Activity card
        time_since = "-"
        if latest_block_time:
            elapsed = datetime.now(timezone.utc).astimezone() - latest_block_time
            total_secs = max(0, int(elapsed.total_seconds()))
            mins, secs = divmod(total_secs, 60)
            time_since = f"{mins} min {secs} sec since latest block"
        self._schedule_update(
            0.1,
            lambda: self.overview_network.update_entries(
                network_entries, count=50, time_since_latest=time_since
            ),
        )
        self._schedule_update(0.2, lambda: self.overview_peers.update_lines(peer_lines, peer_count=peer_count))
        self._schedule_update(
            0.3,
            lambda: self.overview_addresses.update_lines(
                addr_list,
                address_count=address_count,
                wallet_balance=data.get("wallet_balance"),
            ),
        )
        self._schedule_update(0.3, lambda: self.overview_mempool.update_lines(mempool_lines))
        self._schedule_update(0.3, lambda: self.node_status_card.update_lines(node_status_lines))
        self._schedule_update(0.4, lambda: self.overview_system.update_lines(system_overview_lines))
        self._schedule_update(0.5, lambda: self.overview_pricing.update_lines(pricing_lines))
        self._schedule_update(0.5, lambda: self.overview_value.update_lines(value_lines))
        self._schedule_update(0.6, self.refresh_storage_capacity)

        system_lines = [
            f"RPC port: {data['rpc_port']}",
            f"RPC security: {data['rpc_security']}",
            f"Working dir: {data['working_dir']}",
            f"Sync monitor: {data['sync_monitor']}",
            "Daemon control: systemctl start|stop lynx",
        ]

        def update_status() -> None:
            self.status_bar.node_status = data["daemon_status"]
            self.status_bar.block_height = block_height_cli
            
            # Update staking status: use tracked state if available, otherwise show sync state
            if self._staking_enabled is True:
                self.status_bar.staking = "enabled"
            elif self._staking_enabled is False:
                self.status_bar.staking = "disabled"
            elif isinstance(blockchain_info, dict) and blockchain_info.get("initialblockdownload"):
                self.status_bar.staking = "syncing"
            else:
                self.status_bar.staking = "unknown"
            
            self.status_bar.sync_monitor = data["sync_monitor"]
            self.status_bar.refresh()

        self._schedule_update(0.5, update_status)

    async def refresh_logs(self) -> None:
        lines = await asyncio.get_event_loop().run_in_executor(None, self.logs.tail_lines)
        self.logs_panel.update_lines(lines)
    
    @staticmethod
    def _strip_crlf(s: str) -> str:
        """Remove carriage return and line feed characters."""
        return s.replace("\r", "").replace("\n", "")

    async def refresh_block_stats(self) -> None:
        """Refresh the block statistics display."""
        stats = await asyncio.get_event_loop().run_in_executor(None, self.logs.get_latest_block_statistics)
        stats = self._strip_crlf(stats)
        # Remove the "Block Statistics - " prefix since it's in the card title
        if stats.startswith("Block Statistics - "):
            stats = stats.replace("Block Statistics - ", "")
        # Split by comma to create separate lines for each time period
        lines = []
        for line in stats.split(","):
            line = self._strip_crlf(line.strip())
            if not line:
                continue
            # Parse the three parts: period, time, and block count
            # Expected format: "last hour: 233s (16 blocks)"
            import re
            # Extract time period (before the seconds)
            period_match = re.match(r'([^:]+):\s*(\d+)s\s*(.+)', line)
            if period_match:
                period = self._strip_crlf(period_match.group(1).strip())
                total_seconds = int(period_match.group(2))
                block_info = self._strip_crlf(period_match.group(3).strip())
                
                # Convert seconds to "X min Y sec" format
                minutes, seconds = divmod(total_seconds, 60)
                if minutes > 0 and seconds > 0:
                    formatted_time = f"{minutes} min {seconds} sec"
                elif minutes > 0:
                    formatted_time = f"{minutes} min"
                else:
                    formatted_time = f"{seconds} sec"
                
                # Format in columns: fixed widths for consistent alignment
                period_width = 16  # e.g. "last hour:", "fortnight:"
                time_width = 20    # e.g. "9 min 27 sec", "59 min 59 sec"
                block_width = 18   # e.g. "(7 blocks)", "(284 blocks)"
                formatted_line = self._strip_crlf(
                    f"{period + ':':<{period_width}} "
                    f"{formatted_time:<{time_width}} "
                    f"{block_info:<{block_width}}"
                )
                lines.append(formatted_line)
            else:
                lines.append(self._strip_crlf(line))
        self.block_stats_card.update_lines(lines)

    async def refresh_storage_capacity(self) -> None:
        """Refresh the Storage Capability card (runs every 15 minutes)."""
        loop = asyncio.get_event_loop()

        def _fetch() -> tuple[object, list[str]]:
            capacity_data = self.rpc.fetch_capacity()
            disk_stats = self.system.get_disk_and_lynx_stats(
                self.rpc.get_datadir()
            )
            size_on_disk = self.rpc.get_size_on_disk()
            disk_lines: list[str] = []
            if disk_stats["disk_total_bytes"] > 0:
                disk_lines.append(
                    f"Drive: {self._format_bytes(disk_stats['disk_total_bytes'])} "
                    f"({disk_stats['disk_percent']:.0f}% used)"
                )
            if size_on_disk is not None and size_on_disk > 0:
                disk_total = disk_stats["disk_total_bytes"]
                lynx_pct = (
                    100.0 * size_on_disk / disk_total if disk_total > 0 else 0.0
                )
                disk_lines.append(
                    f"Lynx: {self._format_bytes(size_on_disk)} "
                    f"({lynx_pct:.1f}% of drive)"
                )
            return capacity_data, disk_lines

        capacity_data, disk_lines = await loop.run_in_executor(
            None, _fetch
        )
        storage_lines = self._parse_capacity_to_lines(capacity_data)
        if disk_lines:
            storage_lines = disk_lines + storage_lines
        self.overview_storage.update_lines(storage_lines)


def run() -> None:
    LynxTuiApp().run()
