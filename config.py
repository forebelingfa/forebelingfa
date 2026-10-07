from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeConfig:
    ws_url: str = "ws://47.84.51.23:9001"
    secret: str = "uwkeovuoqnpn@13vxck9tjghazhhbrmy"
    room_id: int = 123
    bag_id: int = 999
    account_file: str = "accounts.txt"
    account_index: int = 0
    log_level: str = "INFO"
    poll_url: str = "https://api.taalmil.live/api/go_v3/hot_anchor"
    poll_urls: tuple[str, ...] = (
        "https://api.taalmil.live/api/go_v3/hot_anchor",
        "https://api.taalmil.live/api/v3/hot_anchor",
        "https://api.taalmil.live/api/v2/hot_anchor",
        "https://api.taalmil.live/api/go_v3/hotroom",
        "https://api.taalmil.live/api/go_v3/room_list",
        "https://api.taalmil.live/api/go_v3/rooms",
    )
    poll_interval_seconds: float = 5.0

    @property
    def account_path(self) -> Path:
        return Path(__file__).resolve().parent / self.account_file


DEFAULT_CONFIG = RuntimeConfig()
