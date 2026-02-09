import asyncio
from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual import events
from textual.containers import Container, VerticalScroll
from textual.widgets import Button, Footer, Header, SelectionList, Static, TabbedContent, TabPane

from lynx_tui.services.logs import LogTailer
from lynx_tui.services.pricing import PricingClient
from lynx_tui.services.rpc import RpcClient
from lynx_tui.services.system import SystemClient


class StatusBar(Static):
    def __init__(self) -> None:
        super().__init__()
        self.node_status = "unknown"
        self.block_height = "-"
        self.peers = "-"
        self.staking = "unknown"
        self.price_usd = "-"
        self.sync_monitor = "unknown"
        self.last_update = "-"

    def render(self) -> str:
        return (
            f"Node: {self.node_status} | Height: {self.block_height} | "
            f"Peers: {self.peers} | Staking: {self.staking} | "
            f"SyncMon: {self.sync_monitor} | "
            f"Price: {self.price_usd} | Updated: {self.last_update}"
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
    def __init__(self, title: str, accent_class: str) -> None:
        super().__init__()
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
        return f"[{self.title}]\n{content}"


class HeaderlessCardPanel(CardPanel):
    def render(self) -> str:
        return "\n".join(self.lines) if self.lines else "... loading"


class PeerListPanel(VerticalScroll):
    def __init__(self, title: str, accent_class: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.title = title
        self.accent_class = accent_class
        self.border_title = title
        self.border_title_align = ("left", "top")
        self.add_class("card")
        self.add_class(accent_class)
        self._content = Static("... loading")

    def compose(self) -> ComposeResult:
        yield self._content

    def update_lines(self, lines: list[str], peer_count: int | None = None) -> None:
        content = "\n".join(lines) if lines else "... loading"
        self._content.update(content)
        if peer_count is not None:
            self.border_subtitle = str(peer_count)
            self.border_subtitle_align = ("right", "top")


class AddressListPanel(VerticalScroll):
    def __init__(self, title: str, accent_class: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.title = title
        self.accent_class = accent_class
        self.border_title = title
        self.border_title_align = ("left", "top")
        self.add_class("card")
        self.add_class(accent_class)
        self._content = Static("... loading")

    def compose(self) -> ComposeResult:
        yield self._content

    def update_lines(self, lines: list[str], address_count: int | None = None) -> None:
        content = "\n".join(lines) if lines else "... loading"
        self._content.update(content)
        if address_count is not None:
            self.border_subtitle = str(address_count)
            self.border_subtitle_align = ("right", "top")


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

    def update_entries(self, entries: list[tuple[int, str]], count: int | None = None) -> None:
        self._heights = [height for height, _ in entries]
        if count is not None:
            self.border_subtitle = str(count)
            self.border_subtitle_align = ("right", "top")
        if not entries:
            self._content.update("... loading")
            return
        lines = [f"{height:>7}   {line_display}" for height, line_display in entries]
        self._content.update("\n".join(lines))


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


class LynxTuiApp(App):
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh_all", "Refresh"),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }
    #body {
        height: 1fr;
    }
    #overview-body {
        layout: horizontal;
        height: 1fr;
    }
    #overview-right {
        layout: vertical;
        width: 1fr;
        height: 1fr;
    }
    #overview-peers {
        width: 1fr;
        min-width: 30;
        min-height: 19;
        height: 19;
    }
    #overview-addresses {
        width: 1fr;
        min-width: 30;
        min-height: 19;
        height: 19;
    }
    #status-bar {
        height: 1;
    }
    #overview-grid {
        layout: grid;
        grid-size: 3;
        grid-gutter: 1 1;
        height: 1fr;
        width: 2fr;
    }
    .card {
        padding: 1 1;
        border: round #666;
        height: auto;
        min-height: 6;
    }
    .card.wide {
        column-span: 2;
    }
    .card.tall {
        row-span: 2;
        min-height: 12;
    }
    .card.compact {
        min-height: 4;
    }
    .card.node {
        color: #e6f4ff;
    }
    .card.wallet {
        color: #e9ffe9;
    }
    .card.staking {
        color: #fff3d6;
    }
    .card.network {
        color: #f1e6ff;
    }
    .card.pricing {
        color: #e6ffff;
    }
    .card.sync {
        color: #ffe6e6;
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
        self.title = "Console for the Lynx Data Storage Network"

        self.overview_chain = CardPanel("Chain", "node")
        self.overview_sync = CardPanel("Sync", "sync")
        self.overview_network = NetworkActivityPanel("📡 Network Activity", "network")
        self.overview_network.border_subtitle = "15"
        self.overview_network.border_subtitle_align = ("right", "top")
        self.overview_network.add_class("wide")
        self.overview_peers = PeerListPanel("🌐 Peers", "network", id="overview-peers")
        self.overview_addresses = AddressListPanel(
            "💼 Addresses", "wallet", id="overview-addresses"
        )
        self.overview_mempool = CardPanel("Mempool", "sync")
        self.overview_mining = CardPanel("Mining", "staking")
        self.overview_wallet = CardPanel("Wallet", "wallet")
        self.overview_system = CardPanel("System", "node")
        self.overview_pricing = CardPanel("Pricing", "pricing")

        self.wallet_panel = KeyValuePanel("Wallet")
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

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="body"):
            with TabbedContent():
                with TabPane("Overview"):
                    with Container(id="overview-body"):
                        with Container(id="overview-grid"):
                            yield self.overview_chain
                            yield self.overview_network
                            yield self.overview_mempool
                            yield self.overview_wallet
                            yield self.overview_system
                            yield self.overview_sync
                            yield self.overview_mining
                            yield self.overview_pricing
                        with Container(id="overview-right"):
                            yield self.overview_peers
                            yield self.overview_addresses
                with TabPane("Wallet"):
                    yield self.wallet_panel
                with TabPane("Logs"):
                    yield self.logs_panel
                with TabPane("Settings"):
                    with Container(id="settings"):
                        yield self.timezone_card
        yield self.status_bar
        yield Footer()

    async def on_mount(self) -> None:
        self.set_timer(0.6, self.refresh_node_version)
        self.set_timer(0.1, self.refresh_data)
        self.set_timer(0.2, self.refresh_logs)
        self.set_timer(0.4, self.refresh_timezone_list)
        self.set_timer(0.5, self.refresh_timezone)
        self.set_timer(0.8, lambda: self.set_interval(3600, self.refresh_node_version))
        self.set_timer(1.0, lambda: self.set_interval(5, self.refresh_data))
        self.set_timer(1.2, lambda: self.set_interval(4, self.refresh_logs))

    def _loading_message(self) -> str:
        name = self._node_name or "Blockchain"
        return f"...please wait while loading the {name} Console"

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
            self.title = f"{self._node_name} Console for the Lynx Data Storage Network"

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

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "timezone-apply":
            return
        selected = self.timezone_select.selected
        if not selected:
            self.timezone_status.update("Error: select a timezone.")
            return
        timezone = str(selected[0]).strip()
        self.timezone_status.update("Updating timezone...")
        success, message = await asyncio.get_event_loop().run_in_executor(
            None, self.system.set_timezone, timezone
        )
        status = "OK" if success else "Error"
        self.timezone_status.update(f"{status}: {message}")
        if success:
            await self.refresh_timezone()


    async def action_refresh_all(self) -> None:
        self.timezone_status.update("Refreshing...")
        await asyncio.gather(
            self.refresh_node_version(),
            self.refresh_data(),
            self.refresh_logs(),
            self.refresh_timezone_list(),
            self.refresh_timezone(),
        )
        self.timezone_status.update("Refresh complete.")

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

        chain_lines = [
            f"Network: {self._format_optional(blockchain_info.get('chain'))}",
            f"Height: {self._format_optional(data.get('block_height'))}",
            f"Headers: {self._format_optional(blockchain_info.get('headers'))}",
            f"Best: {self._short_hash(data.get('best_block_hash'))}",
            f"PoS Difficulty: {self._format_optional(pos_difficulty)}",
            f"PoW Difficulty: {self._format_optional(pow_difficulty)}",
            f"Total Disk Used: {self._format_bytes(blockchain_info.get('size_on_disk'))}",
        ]
        sync_lines = [
            f"IBD: {self._format_bool(blockchain_info.get('initialblockdownload'))}",
            f"Verify: {self._format_optional(blockchain_info.get('verificationprogress'))}",
            f"Median: {self._format_timestamp(blockchain_info.get('mediantime'))}",
            f"Tips: {tips_summary}",
            f"Monitor: {self._format_optional(data.get('sync_monitor'))}",
        ]
        network_entries = self.logs.get_update_tip_entries(15)
        def fit_column(value: str, width: int) -> str:
            if len(value) <= width:
                return value.ljust(width)
            if width <= 1:
                return value[:width]
            return f"{value[: width - 1]}…"

        peer_rows: list[tuple[int, str]] = []
        addr_width = 22
        subver_width = 15
        synced_width = 20
        ping_width = 14
        for peer in peer_info:
            if not isinstance(peer, dict):
                continue
            addr = self._format_optional(peer.get("addr"))
            if ":" in addr:
                host, port = addr.rsplit(":", 1)
                if port.isdigit():
                    addr = host
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
            line = f"{addr_col} {subver_col} {synced_col} {ping_col}"
            peer_rows.append((synced_value, line))
        peer_rows.sort(key=lambda row: row[0], reverse=True)
        peer_lines = [line for _, line in peer_rows]
        if not peer_lines:
            peer_lines = ["No peers connected."]
        peer_count = len(peer_info)
        address_groups = data.get("address_groups")
        address_groups = address_groups if isinstance(address_groups, list) else []
        address_lines: list[str] = []
        addr_width = 34
        bal_width = 14
        address_count = 0
        for group in address_groups:
            if not isinstance(group, list):
                continue
            for entry in group:
                if not isinstance(entry, list) or len(entry) < 2:
                    continue
                addr = self._format_optional(entry[0])
                balance = entry[1]
                if isinstance(balance, (int, float)):
                    bal_display = f"{balance:.8f}"
                else:
                    bal_display = self._format_optional(balance)
                line = f"{addr:<{addr_width}} {bal_display:>{bal_width}}"
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
        mining_lines = [
            f"Blocks: {self._format_optional(mining_info.get('blocks'))}",
            f"Difficulty: {self._format_optional(difficulty)}",
            f"Hashrate: {self._format_hashrate(network_hashps)}",
            f"Stake: {self._format_optional(data.get('staking_status'))}",
        ]
        wallet_overview_lines = [
            f"Trusted: {self._format_optional(wallet_mine.get('trusted', data.get('wallet_balance')))}",
            f"Pending: {self._format_optional(wallet_mine.get('untrusted_pending'))}",
            f"Immature: {self._format_optional(wallet_mine.get('immature'))}",
            f"Unconf: {self._format_optional(data.get('unconfirmed_balance'))}",
            f"Tx count: {self._format_optional(wallet_info.get('txcount'))}",
            f"Keypool: {self._format_optional(wallet_info.get('keypoolsize'))}",
        ]
        system_overview_lines = [
            f"Uptime: {self._format_seconds(data.get('uptime'))}",
            f"Mem used: {self._format_bytes(memory_locked.get('used'))}",
            f"Mem total: {self._format_bytes(memory_locked.get('total'))}",
            f"RPC cmds: {self._format_optional(len(active_commands))}",
            f"RPC log: {log_name}",
            f"Working dir: {self._format_optional(data.get('working_dir'))}",
        ]
        pricing_lines = [
            f"Price: {price if price else '-'}",
            "Grid: 1 / 10 / 1,000 / 100k / 1M",
        ]

        self._schedule_update(0.1, lambda: self.overview_chain.update_lines(chain_lines))
        self._schedule_update(0.2, lambda: self.overview_sync.update_lines(sync_lines))
        self._schedule_update(0.2, lambda: self.overview_network.update_entries(network_entries, count=15))
        self._schedule_update(0.2, lambda: self.overview_peers.update_lines(peer_lines, peer_count=peer_count))
        self._schedule_update(
            0.3,
            lambda: self.overview_addresses.update_lines(
                address_lines, address_count=address_count
            ),
        )
        self._schedule_update(0.3, lambda: self.overview_mempool.update_lines(mempool_lines))
        self._schedule_update(0.3, lambda: self.overview_mining.update_lines(mining_lines))
        self._schedule_update(0.4, lambda: self.overview_wallet.update_lines(wallet_overview_lines))
        self._schedule_update(0.4, lambda: self.overview_system.update_lines(system_overview_lines))
        self._schedule_update(0.5, lambda: self.overview_pricing.update_lines(pricing_lines))

        wallet_lines = [
            f"Addresses: {data['address_groups']}",
            "Send: use lynx-cli or future TUI form",
            "Sweep: use lynx-cli or future TUI form",
            "Backups: /var/lib/lynx-backup",
        ]
        self.wallet_panel.update_lines(wallet_lines)

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
            self.status_bar.peers = data["peer_count"]
            self.status_bar.staking = data["staking_status"]
            self.status_bar.sync_monitor = data["sync_monitor"]
            self.status_bar.price_usd = price if price else "-"
            self.status_bar.last_update = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            self.status_bar.refresh()

        self._schedule_update(0.5, update_status)

    async def refresh_logs(self) -> None:
        lines = await asyncio.get_event_loop().run_in_executor(None, self.logs.tail_lines)
        self.logs_panel.update_lines(lines)


def run() -> None:
    LynxTuiApp().run()
