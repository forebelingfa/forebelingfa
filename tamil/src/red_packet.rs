use anyhow::{anyhow, Context, Result};
use clap::{Parser, ValueEnum};
use futures_util::{stream, SinkExt, StreamExt};
use reqwest::header::{HeaderMap, HeaderValue, ACCEPT_ENCODING, CONTENT_TYPE, USER_AGENT};
use serde_json::{json, Map, Value};
use std::cmp::min;
use std::collections::{BTreeMap, HashMap, HashSet, VecDeque};
use std::path::{Path, PathBuf};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::sync::{Mutex, Semaphore};
use tokio::task::JoinSet;
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};
use uuid::Uuid;

const API_BASE: &str = "https://api.taalmil.live/api";
const TOURIST_API_VERSION: &str = "1.2.0";
const TOURIST_USER_AGENT: &str = "2.1.1";
const WS_URL: &str = "ws://47.84.51.23:9001";
const API_SIGNING_SECRET: &str = "5d206b343f87f2ca3a0aa05c58b9a64d";
const WS_SIGNING_SECRET: &str = "uwkeovuoqnpn@13vxck9tjghazhhbrmy";
const APP_VERSION: &str = "2.1.5";
const SMART_DISPATCH_LEAD: Duration = Duration::from_secs(5);
const RED: &str = "\x1b[31m";
const GREEN: &str = "\x1b[32m";
const YELLOW: &str = "\x1b[33m";
const CYAN: &str = "\x1b[36m";
const GRAY: &str = "\x1b[90m";
const RESET: &str = "\x1b[0m";

// def log(logging: bool, category: str, message: str):
//     ...
fn log(logging: bool, category: &str, message: impl AsRef<str>) {
    if !logging {
        return;
    }
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or_default();
    let (icon, color) = match category {
        "error" => ("❌", RED),
        "warning" => ("⚠️", YELLOW),
        "win" => ("💎", GREEN),
        "bag" => ("💰", GREEN),
        "claim" => ("🎯", YELLOW),
        "shutdown" => ("🛑", RED),
        "dispatch" | "worker" => ("🦈", CYAN),
        "scan" | "api" => ("📡", CYAN),
        "websocket" | "join-debug" => ("⚓", CYAN),
        "local" => ("🦜", YELLOW),
        _ => ("🏴‍☠️", CYAN),
    };
    println!(
        "\x1b[2K{icon} {GRAY}[{timestamp}][{category}]{RESET} {color}{}{RESET}",
        message.as_ref()
    );
}

// def print_banner(logging: bool):
//     ...
fn print_banner(logging: bool) {
    if !logging {
        return;
    }
    print!("\x1b[2J\x1b[1;1H");
    println!("{CYAN}╔══════════════════════════════════════════════════════╗{RESET}");
    println!("{CYAN}║          🏴‍☠️  THE FLYING DUTCHMAN  🏴‍☠️              ║{RESET}");
    println!("{CYAN}║            ⚓  TAMIL LUCKYBAG CREW  ⚓                ║{RESET}");
    println!("{CYAN}╚══════════════════════════════════════════════════════╝{RESET}");
    println!("{GREEN}🦜 Tamil LuckyBag Rust worker v{APP_VERSION}{RESET}\n");
}

// class LoggingMode(Enum):
//     ON = ...
//     OFF = ...
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, ValueEnum)]
enum LoggingMode {
    #[default]
    On,
    Off,
}

// class Args:
//     ...
#[derive(Parser, Debug, Clone)]
#[command(about = "Scan Tamil hot rooms and dispatch bounded LuckyBag workers")]
struct Args {
    #[arg(long, default_value = "accounts.txt")]
    accounts: PathBuf,

    #[arg(long, value_enum, default_value_t = LoggingMode::On)]
    logging: LoggingMode,

    #[arg(
        long,
        default_value_t = 0,
        help = "Account index used for authenticated room scanning"
    )]
    scan_account_index: usize,

    #[arg(long, default_value_t = 24)]
    max_workers: usize,

    #[arg(
        long,
        default_value_t = 3,
        help = "Maximum accounts per room for normal and --local-luckybag modes; smart mode uses --max-workers"
    )]
    workers_per_room: usize,

    #[arg(long, default_value_t = 2_000)]
    scan_interval_ms: u64,

    #[arg(long, default_value_t = 10)]
    scan_concurrency: usize,

    #[arg(long, default_value_t = 100)]
    max_pages: u64,

    #[arg(long, default_value_t = 180)]
    idle_timeout_secs: u64,

    #[arg(long, default_value_t = 200)]
    max_shift_secs: u64,

    #[arg(long, default_value_t = 30)]
    room_cooldown_secs: u64,

    #[arg(long, default_value_t = 7)]
    claim_attempts: usize,

    #[arg(long, default_value_t = 100)]
    claim_delay_ms: u64,

    #[arg(long, action = clap::ArgAction::SetTrue)]
    scan_only: bool,

    #[arg(
        long,
        action = clap::ArgAction::SetTrue,
        help = "Assign accounts to hot-anchor rooms and refresh assignments periodically"
    )]
    local_luckybag: bool,

    #[arg(
        long,
        action = clap::ArgAction::SetTrue,
        help = "Use the tourist scout to queue workers for bags close to opening"
    )]
    smart_luckybag: bool,

    #[arg(long, default_value_t = 1_200)]
    local_refresh_secs: u64,

    #[arg(long, default_value_t = 7)]
    local_claim_attempts: usize,

    #[arg(long, default_value_t = 500)]
    local_claim_delay_ms: u64,

    #[arg(
        long,
        value_name = "LIVE_USER_ID",
        help = "Live user ID; resolve their active room and remain connected until Ctrl+C"
    )]
    join: Option<u64>,
}

// class Account:
//     ...
#[derive(Clone, Debug)]
struct Account {
    user_id: u64,
    ws_token: String,
    jwt: String,
}

// class BagRoom:
//     ...
#[derive(Clone, Debug)]
struct BagRoom {
    room_id: u64,
    anchor_id: u64,
    nickname: String,
}

// class WorkerConfig:
//     ...
#[derive(Clone)]
struct WorkerConfig {
    idle_timeout: Duration,
    max_shift: Duration,
    claim_attempts: usize,
    claim_delay: Duration,
    finish_after_claim: bool,
    logging: bool,
}

#[derive(Clone, Debug)]
struct TouristAccount {
    token: String,
    api_token: String,
    tourist_id: u64,
}

#[derive(Clone, Debug)]
struct PendingSmartBag {
    bag_id: u64,
    room: BagRoom,
    opens_at: tokio::time::Instant,
}

struct SmartWorkerPool {
    accounts: Arc<Mutex<VecDeque<Account>>>,
    active_rooms: Arc<Mutex<HashSet<u64>>>,
    worker_semaphore: Arc<Semaphore>,
    worker_config: WorkerConfig,
    workers_per_room: usize,
    stop: Arc<AtomicBool>,
}

// class ClaimBurstConfig:
//     ...
struct ClaimBurstConfig {
    bag_id: u64,
    room_id: u64,
    user_id: u64,
    attempts: usize,
    start_delay: Duration,
    attempt_delay: Duration,
    logging: bool,
}

// def resolve_account_path(requested: Path) -> Path:
//     ...
fn resolve_account_path(requested: &Path) -> PathBuf {
    if requested.is_absolute() || requested.is_file() {
        return requested.to_path_buf();
    }

    let workspace_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap_or_else(|| Path::new("."));
    let workspace_candidate = workspace_root.join(requested);
    if workspace_candidate.is_file() {
        return workspace_candidate;
    }
    requested.to_path_buf()
}

// def now_seconds() -> int:
//     ...
fn now_seconds() -> Result<u64> {
    Ok(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs())
}

// def generate_sign(payload: dict[str, Value]) -> str:
//     ...
fn generate_sign(payload: &Map<String, Value>) -> String {
    let mut sorted_params = BTreeMap::<String, String>::new();
    for (key, value) in payload {
        if matches!(key.as_str(), "sign" | "CREATOR" | "serialVersionUID") {
            continue;
        }
        let rendered = match value {
            Value::String(text) => text.clone(),
            Value::Number(number) => number.to_string(),
            Value::Bool(boolean) => boolean.to_string(),
            Value::Null => "null".to_string(),
            _ => value.to_string(),
        };
        sorted_params.insert(key.clone(), rendered);
    }

    let params = sorted_params
        .into_iter()
        .map(|(key, value)| format!("{key}={value}"))
        .collect::<Vec<_>>()
        .join("&");
    format!(
        "{:x}",
        md5::compute(format!("{params}&key={API_SIGNING_SECRET}"))
    )
}

// def build_hot_anchor_payload(user_id: int, page: int) -> dict[str, Value]:
//     ...
fn build_hot_anchor_payload(user_id: u64, page: u64) -> Result<Map<String, Value>> {
    let mut payload = Map::new();
    payload.insert("classify_id".to_string(), json!(0));
    payload.insert(
        "device_id".to_string(),
        json!(Uuid::new_v4().simple().to_string()),
    );
    payload.insert("group_id".to_string(), json!(0));
    payload.insert("home_id".to_string(), json!(0));
    payload.insert("lang".to_string(), json!("id"));
    payload.insert("package_type".to_string(), json!("haigou-Android"));
    payload.insert("page".to_string(), json!(page));
    payload.insert("pkg".to_string(), json!("3"));
    payload.insert("time".to_string(), json!(now_seconds()?.to_string()));
    payload.insert("type".to_string(), json!(1));
    payload.insert("user_id".to_string(), json!(user_id));
    payload.insert("version".to_string(), json!(APP_VERSION));
    let signature = generate_sign(&payload);
    payload.insert("sign".to_string(), json!(signature));
    Ok(payload)
}

// def parse_account_line(line: str, line_number: int) -> Account | None:
//     ...
fn build_tourist_token_payload() -> Result<Map<String, Value>> {
    let mut payload = Map::new();
    payload.insert("code_type".to_string(), json!(0));
    payload.insert("isVpn".to_string(), json!("0"));
    payload.insert("network".to_string(), json!("Organic"));
    payload.insert("type".to_string(), json!(0));
    payload.insert("userCountry".to_string(), json!(""));
    payload.insert("app_version".to_string(), json!(TOURIST_API_VERSION));
    payload.insert("channel_id".to_string(), json!("3"));
    payload.insert(
        "device_id".to_string(),
        json!(Uuid::new_v4().simple().to_string()),
    );
    payload.insert("facility".to_string(), json!("1"));
    payload.insert("lang".to_string(), json!("id"));
    payload.insert("package_type".to_string(), json!("Android-Google"));
    payload.insert("time".to_string(), json!(now_seconds()?.to_string()));
    payload.insert("tourist_uri".to_string(), json!(""));
    payload.insert("user_id".to_string(), json!("0"));
    let signature = generate_sign(&payload);
    payload.insert("sign".to_string(), json!(signature));
    Ok(payload)
}

fn parse_tourist_token_response(body: &Value) -> Result<TouristAccount> {
    if !is_success_code(body) {
        return Err(anyhow!(
            "tourist-token API code {}: {}",
            body["code"],
            body["msg"]
                .as_str()
                .or_else(|| body["message"].as_str())
                .unwrap_or("no message")
        ));
    }
    let data = body
        .get("data")
        .and_then(Value::as_object)
        .ok_or_else(|| anyhow!("tourist-token response did not contain an account object"))?;
    let token = ["token", "ws_token", "visitor_token"]
        .iter()
        .find_map(|key| data.get(*key).and_then(Value::as_str))
        .filter(|token| !token.trim().is_empty())
        .ok_or_else(|| anyhow!("tourist-token response did not contain a websocket token"))?;
    let tourist_id = data
        .get("tourist_id")
        .and_then(value_u64)
        .filter(|id| *id > 0)
        .ok_or_else(|| anyhow!("tourist-token response did not contain a positive tourist_id"))?;
    let api_token = [
        "jwt_token",
        "jwt_authorization_token",
        "jwt",
        "authorization_token",
    ]
    .iter()
    .find_map(|key| data.get(*key).and_then(Value::as_str))
    .filter(|token| !token.trim().is_empty())
    .ok_or_else(|| anyhow!("tourist-token response did not contain a JWT"))?;
    Ok(TouristAccount {
        token: token.to_string(),
        api_token: api_token.to_string(),
        tourist_id,
    })
}

async fn request_tourist_account(client: &reqwest::Client) -> Result<TouristAccount> {
    let payload = build_tourist_token_payload()?;
    let mut headers = HeaderMap::new();
    headers.insert(USER_AGENT, HeaderValue::from_static(TOURIST_USER_AGENT));
    headers.insert(ACCEPT_ENCODING, HeaderValue::from_static("gzip"));
    headers.insert(
        CONTENT_TYPE,
        HeaderValue::from_static("application/json; charset=UTF-8"),
    );
    headers.insert("encrypt-type", HeaderValue::from_static("1"));
    headers.insert("cache-control", HeaderValue::from_static("no-cache"));
    let response = client
        .post(format!("{API_BASE}/go_v3/limoo/tourist/token"))
        .headers(headers)
        .json(&payload)
        .send()
        .await
        .context("tourist-token request failed")?;
    if !response.status().is_success() {
        return Err(anyhow!("tourist-token HTTP status {}", response.status()));
    }
    let body: Value = response
        .json()
        .await
        .context("tourist-token endpoint returned invalid JSON")?;
    parse_tourist_token_response(&body)
}

fn parse_account_line(line: &str, line_number: usize) -> Result<Option<Account>> {
    let trimmed = line.trim();
    if trimmed.is_empty() || trimmed.starts_with('#') {
        return Ok(None);
    }

    let fields = trimmed.split(',').map(str::trim).collect::<Vec<_>>();
    if fields.len() != 3 {
        return Err(anyhow!(
            "accounts line {line_number}: expected userId,ws_token,jwt"
        ));
    }
    let user_id = fields[0]
        .parse::<u64>()
        .with_context(|| format!("accounts line {line_number}: invalid user ID"))?;
    if fields[1].is_empty() || fields[2].is_empty() {
        return Err(anyhow!(
            "accounts line {line_number}: websocket token and JWT are required"
        ));
    }

    Ok(Some(Account {
        user_id,
        ws_token: fields[1].to_string(),
        jwt: fields[2].to_string(),
    }))
}

// async def load_accounts(path: Path) -> list[Account]:
//     ...
async fn load_accounts(path: &PathBuf) -> Result<Vec<Account>> {
    let content = tokio::fs::read_to_string(path)
        .await
        .with_context(|| format!("could not read account file {}", path.display()))?;
    content
        .lines()
        .enumerate()
        .filter_map(|(index, line)| match parse_account_line(line, index + 1) {
            Ok(Some(account)) => Some(Ok(account)),
            Ok(None) => None,
            Err(error) => Some(Err(error)),
        })
        .collect()
}

fn value_u64(value: &Value) -> Option<u64> {
    value
        .as_u64()
        .or_else(|| value.as_str().and_then(|text| text.parse::<u64>().ok()))
}

fn has_lucky_bag_logo(value: &Value) -> bool {
    value.as_i64() == Some(1) || value.as_str() == Some("1")
}

// def parse_anchor_rooms(body: Value, lucky_bags_only: bool) -> list[BagRoom]:
//     ...
fn parse_anchor_rooms(body: &Value, lucky_bags_only: bool) -> Vec<BagRoom> {
    let Some(items) = body.get("data").and_then(Value::as_array) else {
        return Vec::new();
    };

    items
        .iter()
        .filter_map(|item| {
            if lucky_bags_only && !has_lucky_bag_logo(&item["red_packet_logo"]) {
                return None;
            }
            let room_id = value_u64(&item["room_id"])?;
            let anchor_id = value_u64(&item["user_id"])
                .or_else(|| value_u64(&item["anchor_id"]))
                .unwrap_or(0);
            if room_id == 0 {
                return None;
            }
            Some(BagRoom {
                room_id,
                anchor_id,
                nickname: item["nickname"].as_str().unwrap_or("unknown").to_string(),
            })
        })
        .collect()
}

fn parse_bag_rooms(body: &Value) -> Vec<BagRoom> {
    parse_anchor_rooms(body, true)
}

fn parse_last_page(body: &Value) -> u64 {
    value_u64(&body["last_page"]).unwrap_or(1).max(1)
}

fn build_user_info_payload(user_id: u64) -> Result<Map<String, Value>> {
    let mut payload = Map::new();
    payload.insert("id".to_string(), json!(user_id.to_string()));
    payload.insert("version".to_string(), json!("1.0"));
    payload.insert("app_version".to_string(), json!(APP_VERSION));
    payload.insert("channel_id".to_string(), json!("3"));
    payload.insert(
        "device_id".to_string(),
        json!(Uuid::new_v4().simple().to_string()),
    );
    payload.insert("facility".to_string(), json!("1"));
    payload.insert("lang".to_string(), json!("id"));
    payload.insert("package_type".to_string(), json!("Android-Google"));
    payload.insert("time".to_string(), json!(now_seconds()?.to_string()));
    payload.insert("user_id".to_string(), json!(user_id.to_string()));
    let signature = generate_sign(&payload);
    payload.insert("sign".to_string(), json!(signature));
    Ok(payload)
}

async fn resolve_live_room_id(
    client: &reqwest::Client,
    live_user_id: u64,
    jwt: &str,
    logging: bool,
) -> Result<u64> {
    let payload = build_user_info_payload(live_user_id)?;

    let mut headers = HeaderMap::new();
    headers.insert(USER_AGENT, HeaderValue::from_static(APP_VERSION));
    headers.insert(
        CONTENT_TYPE,
        HeaderValue::from_static("application/json; charset=UTF-8"),
    );
    headers.insert("encrypt-type", HeaderValue::from_static("1"));
    headers.insert(
        "authorization-token",
        HeaderValue::from_str(jwt).context("invalid JWT header value")?,
    );

    let response = client
        .post(format!("{API_BASE}/member/info"))
        .headers(headers)
        .json(&payload)
        .timeout(Duration::from_secs(10))
        .send()
        .await?;

    if !response.status().is_success() {
        log(
            logging,
            "error",
            format!(
                "member/info for live user {} returned HTTP {}",
                live_user_id,
                response.status()
            ),
        );
        return Err(anyhow!(
            "member/info HTTP status {} for live user {}",
            response.status(),
            live_user_id
        ));
    }

    let body: Value = response.json().await?;
    if !is_success_code(&body) {
        return Err(anyhow!(
            "member/info API code {} for live user {}: {}",
            body["code"],
            live_user_id,
            body["msg"]
                .as_str()
                .or_else(|| body["message"].as_str())
                .unwrap_or("no message")
        ));
    }

    let room_id = value_u64(&body["data"]["room_id"])
        .filter(|room_id| *room_id > 0)
        .ok_or_else(|| {
            anyhow!(
                "live user {} is not in an active room (member/info returned no room_id)",
                live_user_id
            )
        })?;

    log(
        logging,
        "join-debug",
        format!("resolved live user {} to room {}", live_user_id, room_id),
    );
    Ok(room_id)
}

fn is_success_code(body: &Value) -> bool {
    matches!(body["code"].as_i64(), Some(0 | 200))
        || matches!(body["code"].as_str(), Some("0" | "200"))
}

// async def fetch_hot_page(client: Client, account: Account, page: int, logging: bool) -> tuple[list[BagRoom], int]:
//     ...
async fn fetch_hot_page(
    client: &reqwest::Client,
    account: &Account,
    page: u64,
    logging: bool,
) -> Result<(Vec<BagRoom>, u64)> {
    let (data, last_page) = request_hot_page(client, account, page, logging).await?;
    let rooms = parse_bag_rooms(&data);
    log(
        logging,
        "api",
        format!(
            "page {page} returned {} LuckyBag-marked room(s); API last_page={last_page}",
            rooms.len()
        ),
    );
    Ok((rooms, last_page))
}

// async def request_hot_page(client: Client, account: Account, page: int, logging: bool) -> tuple[Value, int]:
//     ...
async fn request_hot_page(
    client: &reqwest::Client,
    account: &Account,
    page: u64,
    logging: bool,
) -> Result<(Value, u64)> {
    log(
        logging,
        "api",
        format!(
            "requesting hot-anchor page {page} as account {}",
            account.user_id
        ),
    );
    let payload = build_hot_anchor_payload(account.user_id, page)?;

    let mut headers = HeaderMap::new();
    headers.insert(USER_AGENT, HeaderValue::from_static(APP_VERSION));
    headers.insert(
        CONTENT_TYPE,
        HeaderValue::from_static("application/json; charset=UTF-8"),
    );
    headers.insert("encrypt-type", HeaderValue::from_static("1"));
    headers.insert(
        "authorization-token",
        HeaderValue::from_str(&account.jwt).context("invalid JWT header value")?,
    );

    let response = client
        .post(format!("{API_BASE}/home/hot_anchor"))
        .headers(headers)
        .json(&payload)
        .timeout(Duration::from_secs(10))
        .send()
        .await?;
    if !response.status().is_success() {
        log(
            logging,
            "error",
            format!("hot-anchor page {page} returned HTTP {}", response.status()),
        );
        return Err(anyhow!("home/hot_anchor HTTP status {}", response.status()));
    }
    let body: Value = response.json().await?;
    if !is_success_code(&body) {
        log(
            logging,
            "error",
            format!("hot-anchor page {page} API response: {}", body),
        );
        return Err(anyhow!(
            "home/hot_anchor API code {}: {}",
            body["code"],
            body["msg"]
                .as_str()
                .or_else(|| body["message"].as_str())
                .unwrap_or("no message")
        ));
    }

    let data = body["data"].clone();
    let last_page = parse_last_page(&data);
    Ok((data, last_page))
}

async fn request_hot_page_with_tourist(
    client: &reqwest::Client,
    account: &TouristAccount,
    page: u64,
    logging: bool,
) -> Result<(Value, u64)> {
    let payload = build_hot_anchor_payload(account.tourist_id, page)?;
    let mut headers = HeaderMap::new();
    headers.insert(USER_AGENT, HeaderValue::from_static(APP_VERSION));
    headers.insert(ACCEPT_ENCODING, HeaderValue::from_static("gzip"));
    headers.insert(
        CONTENT_TYPE,
        HeaderValue::from_static("application/json; charset=UTF-8"),
    );
    headers.insert("encrypt-type", HeaderValue::from_static("1"));
    headers.insert("cache-control", HeaderValue::from_static("no-cache"));
    headers.insert(
        "authorization-token",
        HeaderValue::from_str(&account.api_token)
            .context("invalid tourist API authorization token")?,
    );
    let response = client
        .post(format!("{API_BASE}/home/hot_anchor"))
        .headers(headers)
        .json(&payload)
        .timeout(Duration::from_secs(10))
        .send()
        .await
        .context("tourist hot-anchor request failed")?;
    if !response.status().is_success() {
        return Err(anyhow!(
            "tourist hot-anchor page {page} returned HTTP {}",
            response.status()
        ));
    }
    let body: Value = response
        .json()
        .await
        .context("tourist hot-anchor endpoint returned invalid JSON")?;
    if !is_success_code(&body) {
        let message = body["msg"]
            .as_str()
            .or_else(|| body["message"].as_str())
            .unwrap_or("no message");
        log(
            logging,
            "error",
            format!(
                "tourist hot-anchor page {page} API code {}: {message}",
                body["code"]
            ),
        );
        return Err(anyhow!(
            "tourist home/hot_anchor API code {}: {message}",
            body["code"],
        ));
    }
    let data = body["data"].clone();
    let last_page = parse_last_page(&data);
    Ok((data, last_page))
}

// async def scan_lucky_bag_rooms(client: Client, account: Account, max_pages: int, concurrency: int, logging: bool) -> list[BagRoom]:
//     ...
async fn scan_lucky_bag_rooms(
    client: &reqwest::Client,
    account: &Account,
    max_pages: u64,
    concurrency: usize,
    logging: bool,
) -> Result<Vec<BagRoom>> {
    log(
        logging,
        "scan",
        format!("starting room scan; max_pages={max_pages}, concurrency={concurrency}"),
    );
    let (mut rooms, last_page) = fetch_hot_page(client, account, 1, logging).await?;
    let final_page = min(last_page, max_pages.max(1));
    if last_page > final_page {
        log(
            logging,
            "warning",
            format!("API has {last_page} pages; configured cap limits this scan to {final_page}"),
        );
    }
    if final_page <= 1 {
        log(
            logging,
            "scan",
            format!(
                "scan complete: {} unique room(s) across 1 page",
                rooms.len()
            ),
        );
        return Ok(rooms);
    }

    let mut pages = stream::iter(2..=final_page)
        .map(|page| async move { fetch_hot_page(client, account, page, logging).await })
        .buffer_unordered(concurrency.max(1));
    while let Some(page_result) = pages.next().await {
        match page_result {
            Ok((page_rooms, _)) => rooms.extend(page_rooms),
            Err(error) => log(
                logging,
                "error",
                format!("room scan page failed: {error:#}"),
            ),
        }
    }

    let mut seen = HashSet::new();
    rooms.retain(|room| seen.insert(room.room_id));
    log(
        logging,
        "scan",
        format!(
            "scan complete: {} unique LuckyBag-marked room(s) across pages 1-{final_page}",
            rooms.len()
        ),
    );
    Ok(rooms)
}

// async def scan_hot_anchor_rooms(client: Client, account: Account, max_pages: int, concurrency: int, logging: bool) -> list[BagRoom]:
//     ...
async fn scan_hot_anchor_rooms(
    client: &reqwest::Client,
    account: &Account,
    max_pages: u64,
    concurrency: usize,
    logging: bool,
) -> Result<Vec<BagRoom>> {
    log(
        logging,
        "scan",
        format!("starting hot-anchor scan; max_pages={max_pages}, concurrency={concurrency}"),
    );
    let (first_page, last_page) = request_hot_page(client, account, 1, logging).await?;
    let mut rooms = parse_anchor_rooms(&first_page, false);
    let final_page = min(last_page, max_pages.max(1));
    if last_page > final_page {
        log(
            logging,
            "warning",
            format!("API has {last_page} pages; configured cap limits this scan to {final_page}"),
        );
    }

    let mut pages = stream::iter(2..=final_page)
        .map(|page| async move { request_hot_page(client, account, page, logging).await })
        .buffer_unordered(concurrency.max(1));
    while let Some(page_result) = pages.next().await {
        match page_result {
            Ok((data, _)) => rooms.extend(parse_anchor_rooms(&data, false)),
            Err(error) => log(
                logging,
                "error",
                format!("hot-anchor scan page failed: {error:#}"),
            ),
        }
    }

    let mut seen = HashSet::new();
    rooms.retain(|room| seen.insert(room.room_id));
    log(
        logging,
        "scan",
        format!(
            "scan complete: {} unique hot-anchor room(s) across pages 1-{final_page}",
            rooms.len()
        ),
    );
    Ok(rooms)
}

async fn scan_hot_anchor_rooms_with_tourist(
    client: &reqwest::Client,
    tourist: &TouristAccount,
    max_pages: u64,
    concurrency: usize,
    logging: bool,
) -> Result<Vec<BagRoom>> {
    log(
        logging,
        "scan",
        format!(
            "starting tourist hot-anchor scan; max_pages={max_pages}, concurrency={concurrency}"
        ),
    );
    let (first_page, last_page) =
        request_hot_page_with_tourist(client, tourist, 1, logging).await?;
    let mut rooms = parse_anchor_rooms(&first_page, false);
    let final_page = min(last_page, max_pages.max(1));
    if last_page > final_page {
        log(
            logging,
            "warning",
            format!("API has {last_page} pages; configured cap limits this scan to {final_page}"),
        );
    }
    let mut pages =
        stream::iter(2..=final_page)
            .map(|page| async move {
                request_hot_page_with_tourist(client, tourist, page, logging).await
            })
            .buffer_unordered(concurrency.max(1));
    while let Some(page_result) = pages.next().await {
        match page_result {
            Ok((data, _)) => rooms.extend(parse_anchor_rooms(&data, false)),
            Err(error) => log(
                logging,
                "error",
                format!("tourist hot-anchor scan page failed: {error:#}"),
            ),
        }
    }
    let mut seen = HashSet::new();
    rooms.retain(|room| seen.insert(room.room_id));
    log(
        logging,
        "scan",
        format!(
            "tourist scan complete: {} unique hot-anchor room(s) across pages 1-{final_page}",
            rooms.len()
        ),
    );
    Ok(rooms)
}

// def room_login_payload(account: Account, room_id: int) -> Value:
//     ...
fn room_login_payload(account: &Account, room_id: u64) -> Result<Value> {
    let time_mill = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as u64;
    let raw = format!("{WS_SIGNING_SECRET}{time_mill}{}", account.ws_token);
    let md5_str = format!("{:x}", md5::compute(raw));
    Ok(json!({
        "ver": 1,
        "op": 1001,
        "body": {
            "DeviceType": 1,
            "EnterType": 0,
            "FuncLevel": 1280,
            "IsSmallDialog": 0,
            "IsVoice": 0,
            "Lang": "id",
            "Md5Str": md5_str,
            "RoomId": room_id,
            "TimeMill": time_mill,
            "Token": account.ws_token,
            "Tourist": 0,
            "UserId": account.user_id,
            "Version": APP_VERSION,
            "Visitor": 0,
            "package_type": "haigou-Android"
        }
    }))
}

fn tourist_room_login_payload(account: &TouristAccount, room_id: u64) -> Result<Value> {
    let time = now_seconds()?;
    let raw = format!("{WS_SIGNING_SECRET}{time}{}", account.token);
    let md5_str = format!("{:x}", md5::compute(raw));
    Ok(json!({
        "ver": 1,
        "op": 1001,
        "body": {
            "DeviceType": 1,
            "EnterType": 0,
            "FuncLevel": 1280,
            "IsSmallDialog": 0,
            "IsVoice": 0,
            "Lang": "id",
            "Md5Str": md5_str,
            "RoomId": room_id,
            "TimeMill": time,
            "Token": account.token,
            "Tourist": 0,
            "UserId": 0,
            "Version": APP_VERSION,
            "Visitor": 1,
            "package_type": "haigou-Android"
        }
    }))
}

fn parse_scout_bag_list(body: &Value) -> Vec<(u64, u64)> {
    body["List"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|bag| {
            let bag_id = value_u64(&bag["ID"]).filter(|id| *id > 0)?;
            let countdown = value_u64(&bag["CountDown"])?;
            Some((bag_id, countdown))
        })
        .collect()
}

fn next_due_smart_bag(
    pending_bags: &HashMap<u64, PendingSmartBag>,
    now: tokio::time::Instant,
) -> Option<PendingSmartBag> {
    pending_bags
        .values()
        .filter(|bag| bag.opens_at <= now + SMART_DISPATCH_LEAD)
        .min_by_key(|bag| bag.opens_at)
        .cloned()
}

async fn scan_room_bag_list(
    room: &BagRoom,
    tourist: &TouristAccount,
    logging: bool,
) -> Result<Vec<(u64, u64)>> {
    let connected = tokio::time::timeout(Duration::from_secs(10), connect_async(WS_URL))
        .await
        .map_err(|_| anyhow!("tourist websocket connection timed out"))??;
    let (socket, _) = connected;
    let (mut writer, mut reader) = socket.split();
    let login = tourist_room_login_payload(tourist, room.room_id)?;
    writer
        .send(Message::Text(login.to_string()))
        .await
        .context("failed to send tourist room-login frame")?;

    let deadline = tokio::time::Instant::now() + Duration::from_secs(5);
    let mut joined = false;
    loop {
        let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
        if remaining.is_zero() {
            return Err(anyhow!(
                "{} timed out for room {}",
                if joined {
                    "LuckyBag list"
                } else {
                    "tourist room-login acknowledgment"
                },
                room.room_id
            ));
        }
        let incoming = tokio::time::timeout(remaining, reader.next())
            .await
            .map_err(|_| {
                anyhow!(
                    "{} timed out for room {}",
                    if joined {
                        "LuckyBag list"
                    } else {
                        "tourist room-login acknowledgment"
                    },
                    room.room_id
                )
            })?;
        match incoming {
            Some(Ok(Message::Text(text))) => {
                let message: Value = serde_json::from_str(&text)
                    .context("tourist scanner received a non-JSON text frame")?;
                match value_u64(&message["op"]) {
                    Some(1001) if !joined => {
                        let body = &message["body"];
                        let code = body["Code"].to_string();
                        let error = body["ErrStr"].as_str().unwrap_or("");
                        let rejected = body.get("Code").is_some()
                            && !matches!(body["Code"].as_i64(), Some(0 | 200))
                            && !matches!(body["Code"].as_str(), Some("0" | "200"));
                        if rejected || !error.is_empty() {
                            return Err(anyhow!(
                                "tourist join rejected for room {}: code={code}, error={error}",
                                room.room_id
                            ));
                        }
                        joined = true;
                        log(
                            logging,
                            "websocket",
                            format!(
                                "tourist joined room {} (server op=1001 code={code})",
                                room.room_id
                            ),
                        );
                        for frame in [
                            json!({"body":{},"op":2102,"ver":1}),
                            json!({"body":{"Type":1},"op":2004,"ver":1}),
                            json!({"body":{"YeMa":1,"YeNum":20},"op":1005,"ver":1}),
                            json!({"body":{},"op":1047,"ver":1}),
                        ] {
                            writer
                                .send(Message::Text(frame.to_string()))
                                .await
                                .context("failed to send tourist room initialization frame")?;
                        }
                    }
                    Some(2102) if joined => {
                        let bags = parse_scout_bag_list(&message["body"]);
                        log(
                            logging,
                            "scan",
                            format!(
                                "anak pramuka found {} bag(s) in room {}",
                                bags.len(),
                                room.room_id
                            ),
                        );
                        return Ok(bags);
                    }
                    _ => {}
                }
            }
            Some(Ok(Message::Ping(payload))) => {
                writer.send(Message::Pong(payload)).await?;
            }
            Some(Ok(Message::Close(frame))) => {
                return Err(anyhow!(
                    "tourist scanner socket closed before LuckyBag list: {frame:?}"
                ));
            }
            Some(Ok(_)) => {}
            Some(Err(error)) => return Err(anyhow!("tourist scanner receive failed: {error}")),
            None => return Err(anyhow!("tourist scanner socket ended before LuckyBag list")),
        }
    }
}

// def claim_plan(body: Value, op: int) -> tuple[int, Duration] | None:
//     ...
fn claim_plan(body: &Value, op: u64) -> Option<(u64, Duration)> {
    let bag_id = value_u64(&body["ID"]).filter(|bag_id| *bag_id > 0)?;
    if value_u64(&body["Status"]) == Some(1) {
        return Some((bag_id, Duration::ZERO));
    }
    if op == 2100 {
        let countdown = value_u64(&body["CountDown"])
            .or_else(|| value_u64(&body["LuckyBagData"]["CountDown"]))
            .unwrap_or(0);
        if countdown > 0 {
            return Some((bag_id, Duration::from_secs(countdown)));
        }
    }
    None
}

// async def claim_burst(writer: AsyncWriter, config: ClaimBurstConfig, cancelled: bool, shutdown: bool) -> None:
//     ...
async fn claim_burst<S>(
    writer: Arc<Mutex<S>>,
    config: ClaimBurstConfig,
    cancelled: Arc<AtomicBool>,
    shutdown: Arc<AtomicBool>,
) -> Result<()>
where
    S: futures_util::Sink<Message> + Unpin + Send + 'static,
    S::Error: std::fmt::Display + Send + Sync + 'static,
{
    let payload = Message::Text(json!({"body":{"ID":config.bag_id},"op":2101,"ver":1}).to_string());

    let start_at = tokio::time::Instant::now() + config.start_delay;
    log(
        config.logging,
        "claim",
        format!(
            "user {}, room {}, bag {}: waiting {:.1}s before burst",
            config.user_id,
            config.room_id,
            config.bag_id,
            config.start_delay.as_secs_f64()
        ),
    );
    while tokio::time::Instant::now() < start_at
        && !cancelled.load(Ordering::Relaxed)
        && !shutdown.load(Ordering::Relaxed)
    {
        tokio::time::sleep(Duration::from_millis(100).min(start_at - tokio::time::Instant::now()))
            .await;
    }

    for attempt in 0..config.attempts {
        if cancelled.load(Ordering::Relaxed) || shutdown.load(Ordering::Relaxed) {
            break;
        }
        writer
            .lock()
            .await
            .send(payload.clone())
            .await
            .map_err(|error| anyhow!("websocket claim send failed: {error}"))?;
        log(
            config.logging,
            "claim",
            format!(
                "user {}, room {}, bag {}: attempt {}/{} sent",
                config.user_id,
                config.room_id,
                config.bag_id,
                attempt + 1,
                config.attempts
            ),
        );
        if attempt + 1 < config.attempts && !config.attempt_delay.is_zero() {
            tokio::time::sleep(config.attempt_delay).await;
        }
    }
    Ok(())
}

// async def run_worker(room: BagRoom, account: Account, config: WorkerConfig, stop: bool):
//     ...
async fn run_worker(room: BagRoom, account: Account, config: WorkerConfig, stop: Arc<AtomicBool>) {
    let started = tokio::time::Instant::now();
    let mut last_activity = started;
    let mut shift_end = started + config.max_shift;
    let mut reconnect_delay = Duration::from_secs(1);
    let mut connect_attempt = 0_u64;
    let mut claim_completed = false;
    log(
        config.logging,
        "worker",
        format!(
            "user {} assigned room {} ({}, anchor {}), max-shift={}s idle-timeout={}s",
            account.user_id,
            room.room_id,
            room.nickname,
            room.anchor_id,
            config.max_shift.as_secs(),
            config.idle_timeout.as_secs()
        ),
    );
    while !stop.load(Ordering::Relaxed)
        && !claim_completed
        && tokio::time::Instant::now() < shift_end
        && last_activity.elapsed() < config.idle_timeout
    {
        connect_attempt += 1;
        log(
            config.logging,
            "websocket",
            format!(
                "user {} connecting to room {} (attempt {connect_attempt})",
                account.user_id, room.room_id
            ),
        );
        match connect_async(WS_URL).await {
            Ok((socket, _)) => {
                let (writer, mut reader) = socket.split();
                let writer = Arc::new(Mutex::new(writer));
                let mut claim_signals =
                    BTreeMap::<u64, (Arc<AtomicBool>, Option<tokio::time::Instant>)>::new();
                let join = match room_login_payload(&account, room.room_id) {
                    Ok(payload) => payload,
                    Err(error) => {
                        log(
                            config.logging,
                            "error",
                            format!(
                                "user {} could not create join payload: {error:#}",
                                account.user_id
                            ),
                        );
                        return;
                    }
                };
                if let Err(error) = writer
                    .lock()
                    .await
                    .send(Message::Text(join.to_string()))
                    .await
                {
                    log(
                        config.logging,
                        "error",
                        format!(
                            "user {} room {} join send failed: {error}",
                            account.user_id, room.room_id
                        ),
                    );
                    tokio::time::sleep(reconnect_delay).await;
                    reconnect_delay = (reconnect_delay * 2).min(Duration::from_secs(15));
                    continue;
                }
                reconnect_delay = Duration::from_secs(1);
                log(
                    config.logging,
                    "websocket",
                    format!(
                        "user {} joined room {} for {} (anchor {})",
                        account.user_id, room.room_id, room.nickname, room.anchor_id
                    ),
                );

                let mut heartbeat = tokio::time::interval(Duration::from_secs(30));
                loop {
                    if stop.load(Ordering::Relaxed)
                        || last_activity.elapsed() >= config.idle_timeout
                        || tokio::time::Instant::now() >= shift_end
                    {
                        break;
                    }

                    tokio::select! {
                        _ = heartbeat.tick() => {
                            if let Err(error) = writer.lock().await.send(Message::Ping(Vec::new())).await {
                                log(config.logging, "error", format!("user {} websocket ping failed in room {}: {error}", account.user_id, room.room_id));
                                break;
                            }
                            log(config.logging, "websocket", format!("user {} websocket ping sent to room {}", account.user_id, room.room_id));
                        }
                        incoming = reader.next() => {
                            match incoming {
                                Some(Ok(Message::Text(text))) => {
                                    let Ok(message) = serde_json::from_str::<Value>(&text) else {
                                        log(config.logging, "warning", format!("user {} received a non-JSON text frame", account.user_id));
                                        continue;
                                    };
                                    let op = value_u64(&message["op"]).unwrap_or(0);
                                    let body = &message["body"];
                                    log(config.logging, "event", format!("user {} room {} received op={op}", account.user_id, room.room_id));
                                    if op == 2100 || op == 2101 {
                                        last_activity = tokio::time::Instant::now();
                                    }
                                    if op == 2100 && body["LuckyBagData"].is_object() {
                                        let countdown = value_u64(&body["CountDown"])
                                            .or_else(|| value_u64(&body["LuckyBagData"]["CountDown"]))
                                            .unwrap_or(0);
                                        if countdown > 0 {
                                            shift_end = shift_end.max(tokio::time::Instant::now() + Duration::from_secs(countdown + 5));
                                            log(config.logging, "bag", format!("room {} bag event extends shift by countdown={}s", room.room_id, countdown));
                                        }
                                    }

                                    if op == 2101 {
                                        let code = body["Code"].to_string();
                                        let result_code = body["Code"].as_i64().or_else(|| body["Code"].as_str()?.parse::<i64>().ok());
                                        let result_category = match result_code {
                                            Some(0) => "win",
                                            Some(1014) => "warning",
                                            _ => "error",
                                        };
                                        log(config.logging, result_category, format!("user {} room {} result code={} gold={}", account.user_id, room.room_id, code, body["Gold"]));
                                        if matches!(result_code, Some(0 | 1014)) {
                                            if let Some(bag_id) = value_u64(&body["ID"]) {
                                                if let Some((signal, _)) = claim_signals.remove(&bag_id) {
                                                    signal.store(true, Ordering::Relaxed);
                                                }
                                            }
                                        }
                                        if config.finish_after_claim {
                                            claim_completed = true;
                                            break;
                                        }
                                        continue;
                                    }

                                    if let Some((bag_id, wait_time)) = claim_plan(body, op) {
                                        let is_open = wait_time.is_zero();
                                        let existing = claim_signals.remove(&bag_id);
                                        let should_start = match existing {
                                            Some((signal, Some(deadline))) if is_open && tokio::time::Instant::now() < deadline => {
                                                signal.store(true, Ordering::Relaxed);
                                                log(config.logging, "claim", format!("bag {bag_id} opened before countdown; cancelling scheduled burst and firing now"));
                                                true
                                            }
                                            Some((signal, deadline)) => {
                                                claim_signals.insert(bag_id, (signal, deadline));
                                                false
                                            }
                                            None => true,
                                        };

                                        if should_start {
                                            if is_open {
                                                log(config.logging, "bag", format!("user {} room {} bag {bag_id} opened; sending {} attempts", account.user_id, room.room_id, config.claim_attempts));
                                            } else {
                                                log(config.logging, "bag", format!("user {} room {} bag {bag_id} countdown={}s", account.user_id, room.room_id, wait_time.as_secs()));
                                            }
                                            let cancel_signal = Arc::new(AtomicBool::new(false));
                                            let deadline = if is_open {
                                                None
                                            } else {
                                                Some(tokio::time::Instant::now() + wait_time)
                                            };
                                            claim_signals.insert(bag_id, (cancel_signal.clone(), deadline));
                                            let writer = writer.clone();
                                            let stop_flag = stop.clone();
                                            let attempts = config.claim_attempts;
                                            let attempt_delay = config.claim_delay;
                                            let user_id = account.user_id;
                                            let room_id = room.room_id;
                                            let logging = config.logging;
                                            let burst_config = ClaimBurstConfig {
                                                bag_id,
                                                room_id,
                                                user_id,
                                                attempts,
                                                start_delay: wait_time,
                                                attempt_delay,
                                                logging,
                                            };
                                            tokio::spawn(async move {
                                                if let Err(error) = claim_burst(writer, burst_config, cancel_signal, stop_flag).await {
                                                    log(logging, "error", format!("user {user_id} room {room_id} bag {bag_id} claim failed: {error:#}"));
                                                }
                                            });
                                        }
                                    }
                                }
                                Some(Ok(Message::Ping(payload))) => {
                                    if let Err(error) = writer.lock().await.send(Message::Pong(payload)).await {
                                        log(config.logging, "error", format!("user {} pong failed: {error}", account.user_id));
                                        break;
                                    }
                                }
                                Some(Ok(Message::Close(_))) | None => break,
                                Some(Ok(_)) => {},
                                Some(Err(error)) => {
                                    log(config.logging, "error", format!("user {} room {} websocket receive failed: {error}", account.user_id, room.room_id));
                                    break;
                                }
                            }
                        }
                    }
                }
                for (signal, _) in claim_signals.values() {
                    signal.store(true, Ordering::Relaxed);
                }
            }
            Err(error) => {
                log(
                    config.logging,
                    "error",
                    format!(
                        "user {} connection to room {} failed: {error}",
                        account.user_id, room.room_id
                    ),
                );
            }
        }

        if claim_completed {
            log(
                config.logging,
                "worker",
                format!(
                    "user {} received a LuckyBag claim result in room {}; releasing account",
                    account.user_id, room.room_id
                ),
            );
            break;
        }

        if stop.load(Ordering::Relaxed)
            || tokio::time::Instant::now() >= shift_end
            || last_activity.elapsed() >= config.idle_timeout
        {
            let reason = if stop.load(Ordering::Relaxed) {
                "shutdown requested"
            } else if tokio::time::Instant::now() >= shift_end {
                "maximum shift elapsed"
            } else {
                "idle timeout elapsed"
            };
            log(
                config.logging,
                "worker",
                format!(
                    "user {} leaving room {}: {reason}",
                    account.user_id, room.room_id
                ),
            );
            break;
        }
        log(
            config.logging,
            "websocket",
            format!(
                "user {} reconnecting to room {} after {}s",
                account.user_id,
                room.room_id,
                reconnect_delay.as_secs()
            ),
        );
        tokio::time::sleep(reconnect_delay).await;
        reconnect_delay = (reconnect_delay * 2).min(Duration::from_secs(15));
    }
    log(
        config.logging,
        "worker",
        format!(
            "user {} worker ended for room {} after {}s",
            account.user_id,
            room.room_id,
            started.elapsed().as_secs()
        ),
    );
}

// async def run_room_group(room: BagRoom, accounts: deque[Account], active_rooms: set[int], worker_semaphore: Semaphore, config: WorkerConfig, workers_per_room: int, stop: bool):
//     ...
async fn run_room_group(
    room: BagRoom,
    accounts: Arc<Mutex<VecDeque<Account>>>,
    active_rooms: Arc<Mutex<HashSet<u64>>>,
    worker_semaphore: Arc<Semaphore>,
    config: WorkerConfig,
    workers_per_room: usize,
    stop: Arc<AtomicBool>,
) {
    let logging = config.logging;
    let group = {
        let mut queue = accounts.lock().await;
        let take = min(workers_per_room, queue.len());
        (0..take)
            .filter_map(|_| queue.pop_front())
            .collect::<Vec<_>>()
    };

    if group.is_empty() {
        log(
            logging,
            "dispatch",
            format!("room {} skipped: no accounts available", room.room_id),
        );
        active_rooms.lock().await.remove(&room.room_id);
        return;
    }

    log(
        logging,
        "dispatch",
        format!(
            "dispatching {} account(s) to room {}",
            group.len(),
            room.room_id
        ),
    );
    let mut workers = JoinSet::new();
    for account in group {
        let room = room.clone();
        let queue = accounts.clone();
        let semaphore = worker_semaphore.clone();
        let worker_config = config.clone();
        let stop_flag = stop.clone();
        workers.spawn(async move {
            if let Ok(permit) = semaphore.acquire_owned().await {
                run_worker(room, account.clone(), worker_config, stop_flag).await;
                queue.lock().await.push_back(account);
                drop(permit);
            } else {
                queue.lock().await.push_back(account);
            }
        });
    }

    while let Some(result) = workers.join_next().await {
        if let Err(error) = result {
            log(
                logging,
                "error",
                format!("worker task for room {} failed: {error}", room.room_id),
            );
        }
    }
    active_rooms.lock().await.remove(&room.room_id);
    log(
        logging,
        "dispatch",
        format!("room {} released for a later scan", room.room_id),
    );
}

// async def scan_only(client: Client, account: Account, args: Args, logging: bool) -> None:
//     ...
async fn scan_only(
    client: &reqwest::Client,
    account: &Account,
    args: &Args,
    logging: bool,
) -> Result<()> {
    let rooms = scan_lucky_bag_rooms(
        client,
        account,
        args.max_pages,
        args.scan_concurrency,
        logging,
    )
    .await?;
    log(
        logging,
        "scan",
        format!("found {} LuckyBag-marked room(s)", rooms.len()),
    );
    for room in rooms {
        log(
            logging,
            "room",
            format!(
                "room_id={} anchor_id={} nickname={}",
                room.room_id, room.anchor_id, room.nickname
            ),
        );
    }
    Ok(())
}

// def local_room_assignment_count(account_count: int, room_count: int, workers_per_room: int) -> int:
//     ...
fn local_room_assignment_count(
    account_count: usize,
    room_count: usize,
    workers_per_room: usize,
) -> usize {
    if account_count == 0 || room_count == 0 || workers_per_room == 0 {
        return 0;
    }
    account_count.div_ceil(workers_per_room).min(room_count)
}

// async def debug_join_room(room_id: int, account: Account, logging: bool) -> None:
//     ...
async fn debug_join_room(room_id: u64, account: &Account, logging: bool) -> Result<()> {
    log(
        logging,
        "join-debug",
        format!(
            "connecting user {} to room {room_id}; claims and chat are disabled",
            account.user_id
        ),
    );
    let connect_result = tokio::time::timeout(Duration::from_secs(10), connect_async(WS_URL))
        .await
        .map_err(|_| anyhow!("websocket connection timed out after 10 seconds"))??;
    let (socket, _) = connect_result;
    let (mut writer, mut reader) = socket.split();
    let payload = room_login_payload(account, room_id)?;
    writer
        .send(Message::Text(payload.to_string()))
        .await
        .context("failed to send room-login frame")?;
    log(
        logging,
        "join-debug",
        "room-login frame sent; waiting for server acceptance",
    );

    let mut joined = false;
    let mut shutdown_signal = Box::pin(tokio::signal::ctrl_c());
    let mut deadline = tokio::time::Instant::now() + Duration::from_secs(12);

    loop {
        tokio::select! {
            _ = shutdown_signal.as_mut() => {
                log(logging, "shutdown", "Ctrl+C received; closing join socket");
                let _ = writer.send(Message::Close(None)).await;
                return Ok(());
            }
            incoming = reader.next() => {
                let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
                if remaining.is_zero() && !joined {
                    log(logging, "join-debug", format!("no room-login response received for room {room_id} within 12s"));
                    return Err(anyhow!("no room-login response received within 12 seconds"));
                }

                match incoming {
                    Some(Ok(Message::Text(text))) => {
                        let message: Value = serde_json::from_str(&text)
                            .context("server sent a non-JSON text frame during join test")?;
                        let op = value_u64(&message["op"]).unwrap_or(0);
                        let body = &message["body"];
                        let code = body["Code"].to_string();
                        let error = body["ErrStr"].as_str().unwrap_or("");
                        log(
                            logging,
                            "join-debug",
                            format!("server frame op={op} code={code} error={error:?}"),
                        );

                        if op == 1001 {
                            let rejected = body.get("Code").is_some()
                                && !matches!(body["Code"].as_i64(), Some(0 | 200))
                                && !matches!(body["Code"].as_str(), Some("0" | "200"));
                            if rejected || !error.is_empty() {
                                return Err(anyhow!(
                                    "server returned a room-login rejection: code={code}, error={error}"
                                ));
                            }
                            joined = true;
                            deadline = tokio::time::Instant::now() + Duration::from_secs(30);
                            log(
                                logging,
                                "join-debug",
                                format!("server replied with op 1001 for room {room_id}; join accepted; staying connected until Ctrl+C"),
                            );
                        }
                    }
                    Some(Ok(Message::Ping(payload))) => {
                        writer.send(Message::Pong(payload)).await?;
                    }
                    Some(Ok(Message::Close(frame))) => {
                        log(logging, "join-debug", format!("server closed the socket while staying connected: {frame:?}"));
                        return Ok(());
                    }
                    Some(Ok(_)) => {}
                    Some(Err(error)) => return Err(anyhow!("websocket receive failed: {error}")),
                    None => return Err(anyhow!("websocket ended before join ACK")),
                }
                if joined {
                    tokio::time::sleep(Duration::from_millis(250)).await;
                }
            }
        }
    }
}

// async def run_local_luckybag(client: Client, accounts: list[Account], scan_account: Account, args: Args, logging: bool) -> None:
//     ...
async fn run_local_luckybag(
    client: &reqwest::Client,
    accounts: &[Account],
    scan_account: &Account,
    args: &Args,
    logging: bool,
) -> Result<()> {
    let shutdown = Arc::new(AtomicBool::new(false));
    let signal_shutdown = shutdown.clone();
    tokio::spawn(async move {
        if let Err(error) = tokio::signal::ctrl_c().await {
            log(
                true,
                "error",
                format!("failed to listen for Ctrl-C: {error}"),
            );
        } else {
            log(true, "shutdown", "shutdown requested");
            signal_shutdown.store(true, Ordering::Relaxed);
        }
    });

    let refresh = Duration::from_secs(args.local_refresh_secs);
    let worker_config = WorkerConfig {
        idle_timeout: refresh,
        max_shift: refresh,
        claim_attempts: args.local_claim_attempts,
        claim_delay: Duration::from_millis(args.local_claim_delay_ms),
        finish_after_claim: false,
        logging,
    };
    let mut cycle = 0_u64;

    while !shutdown.load(Ordering::Relaxed) {
        cycle += 1;
        log(
            logging,
            "local",
            format!("starting room assignment cycle {cycle}"),
        );
        let rooms = match scan_hot_anchor_rooms(
            client,
            scan_account,
            args.max_pages,
            args.scan_concurrency,
            logging,
        )
        .await
        {
            Ok(rooms) => rooms,
            Err(error) => {
                log(
                    logging,
                    "error",
                    format!("local hot-anchor scan failed: {error:#}"),
                );
                tokio::select! {
                    _ = tokio::time::sleep(refresh) => {},
                    _ = async {
                        while !shutdown.load(Ordering::Relaxed) {
                            tokio::time::sleep(Duration::from_millis(100)).await;
                        }
                    } => {},
                }
                continue;
            }
        };

        if rooms.is_empty() {
            log(logging, "warning", "hot-anchor scan returned no rooms");
        }
        let assigned_account_count = accounts.len().min(args.max_workers);
        let room_assignment_count =
            local_room_assignment_count(assigned_account_count, rooms.len(), args.workers_per_room);
        log(
            logging,
            "local",
            format!(
                "assigning up to {} account(s) across {} room(s), with up to {} worker(s) per room; {} account(s) and {} room(s) remain unused",
                assigned_account_count,
                room_assignment_count,
                args.workers_per_room,
                accounts.len().saturating_sub(assigned_account_count),
                rooms.len().saturating_sub(room_assignment_count)
            ),
        );

        if room_assignment_count == 0 {
            tokio::select! {
                _ = tokio::time::sleep(refresh) => {},
                _ = async {
                    while !shutdown.load(Ordering::Relaxed) {
                        tokio::time::sleep(Duration::from_millis(100)).await;
                    }
                } => {},
            }
            continue;
        }

        let cycle_stop = Arc::new(AtomicBool::new(false));
        let account_queue = Arc::new(Mutex::new(VecDeque::from(
            accounts
                .iter()
                .take(assigned_account_count)
                .cloned()
                .collect::<Vec<_>>(),
        )));
        let active_rooms = Arc::new(Mutex::new(HashSet::new()));
        let worker_semaphore = Arc::new(Semaphore::new(args.max_workers));
        let mut workers = JoinSet::new();
        for room in rooms.into_iter().take(room_assignment_count) {
            log(
                logging,
                "dispatch",
                format!(
                    "assigning room {} ({}) up to {} worker(s)",
                    room.room_id, room.nickname, args.workers_per_room
                ),
            );
            workers.spawn(run_room_group(
                room,
                account_queue.clone(),
                active_rooms.clone(),
                worker_semaphore.clone(),
                worker_config.clone(),
                args.workers_per_room,
                cycle_stop.clone(),
            ));
        }

        tokio::select! {
            _ = tokio::time::sleep(refresh) => {
                log(logging, "local", format!("cycle {cycle} refresh interval elapsed"));
            },
            _ = async {
                while !shutdown.load(Ordering::Relaxed) {
                    tokio::time::sleep(Duration::from_millis(100)).await;
                }
            } => {},
        }
        cycle_stop.store(true, Ordering::Relaxed);
        while let Some(result) = workers.join_next().await {
            if let Err(error) = result {
                log(
                    logging,
                    "error",
                    format!("local room worker failed: {error}"),
                );
            }
        }
    }
    Ok(())
}

async fn dispatch_due_smart_bag(
    pending_bags: &mut HashMap<u64, PendingSmartBag>,
    dispatched_bags: &mut HashMap<u64, tokio::time::Instant>,
    worker_pool: &SmartWorkerPool,
    active_group: &mut JoinSet<()>,
) {
    if !active_group.is_empty() || worker_pool.stop.load(Ordering::Relaxed) {
        return;
    }
    let Some(bag) = next_due_smart_bag(pending_bags, tokio::time::Instant::now()) else {
        return;
    };
    if worker_pool.accounts.lock().await.is_empty() {
        return;
    }

    pending_bags.remove(&bag.bag_id);
    dispatched_bags.insert(bag.bag_id, tokio::time::Instant::now());
    log(
        worker_pool.worker_config.logging,
        "dispatch",
        format!(
            "dispatching up to {} worker(s) to room {} for bag {} (opens in {}s)",
            worker_pool.workers_per_room,
            bag.room.room_id,
            bag.bag_id,
            bag.opens_at
                .saturating_duration_since(tokio::time::Instant::now())
                .as_secs()
        ),
    );
    active_group.spawn(run_room_group(
        bag.room,
        worker_pool.accounts.clone(),
        worker_pool.active_rooms.clone(),
        worker_pool.worker_semaphore.clone(),
        worker_pool.worker_config.clone(),
        worker_pool.workers_per_room,
        worker_pool.stop.clone(),
    ));
}

async fn run_smart_luckybag(
    client: &reqwest::Client,
    accounts: &[Account],
    tourist: &TouristAccount,
    args: &Args,
    logging: bool,
) -> Result<()> {
    let stop = Arc::new(AtomicBool::new(false));
    let signal_stop = stop.clone();
    tokio::spawn(async move {
        if let Err(error) = tokio::signal::ctrl_c().await {
            log(
                true,
                "error",
                format!("failed to listen for Ctrl-C: {error}"),
            );
        } else {
            log(true, "shutdown", "shutdown requested");
            signal_stop.store(true, Ordering::Relaxed);
        }
    });

    let assigned_accounts = accounts
        .iter()
        .take(args.max_workers)
        .cloned()
        .collect::<Vec<_>>();
    let account_queue = Arc::new(Mutex::new(VecDeque::from(assigned_accounts)));
    let worker_config = WorkerConfig {
        idle_timeout: Duration::from_secs(20),
        max_shift: Duration::from_secs(30),
        claim_attempts: args.claim_attempts,
        claim_delay: Duration::from_millis(args.claim_delay_ms),
        finish_after_claim: true,
        logging,
    };
    let worker_pool = SmartWorkerPool {
        accounts: account_queue.clone(),
        active_rooms: Arc::new(Mutex::new(HashSet::new())),
        worker_semaphore: Arc::new(Semaphore::new(args.max_workers)),
        worker_config,
        workers_per_room: args.max_workers,
        stop: stop.clone(),
    };
    let mut pending_bags = HashMap::<u64, PendingSmartBag>::new();
    let mut dispatched_bags = HashMap::<u64, tokio::time::Instant>::new();
    let mut active_group = JoinSet::new();
    log(
        logging,
        "local",
        format!(
            "smart LuckyBag scout started with an API-issued tourist token; {} worker account(s) available, dispatch lead=5s",
            account_queue.lock().await.len()
        ),
    );

    while !stop.load(Ordering::Relaxed) {
        while active_group.try_join_next().is_some() {}
        dispatched_bags
            .retain(|_, dispatched_at| dispatched_at.elapsed() < Duration::from_secs(600));
        pending_bags.retain(|bag_id, bag| {
            !dispatched_bags.contains_key(bag_id)
                && bag.opens_at + Duration::from_secs(20) > tokio::time::Instant::now()
        });

        match scan_hot_anchor_rooms_with_tourist(
            client,
            tourist,
            args.max_pages,
            args.scan_concurrency,
            logging,
        )
        .await
        {
            Ok(rooms) => {
                if rooms.is_empty() {
                    log(
                        logging,
                        "warning",
                        "hot-anchor scan returned no rooms for tourist scouting",
                    );
                }
                for room in rooms {
                    if stop.load(Ordering::Relaxed) {
                        break;
                    }
                    match scan_room_bag_list(&room, tourist, logging).await {
                        Ok(bags) => {
                            let observed_at = tokio::time::Instant::now();
                            for (bag_id, countdown) in bags {
                                if !dispatched_bags.contains_key(&bag_id) {
                                    pending_bags.insert(
                                        bag_id,
                                        PendingSmartBag {
                                            bag_id,
                                            room: room.clone(),
                                            opens_at: observed_at + Duration::from_secs(countdown),
                                        },
                                    );
                                }
                            }
                        }
                        Err(error) => log(
                            logging,
                            "warning",
                            format!("tourist scan failed for room {}: {error:#}", room.room_id),
                        ),
                    }

                    while active_group.try_join_next().is_some() {}
                    dispatch_due_smart_bag(
                        &mut pending_bags,
                        &mut dispatched_bags,
                        &worker_pool,
                        &mut active_group,
                    )
                    .await;
                }
            }
            Err(error) => log(
                logging,
                "error",
                format!("smart LuckyBag hot-anchor scan failed: {error:#}"),
            ),
        }

        while active_group.try_join_next().is_some() {}
        dispatch_due_smart_bag(
            &mut pending_bags,
            &mut dispatched_bags,
            &worker_pool,
            &mut active_group,
        )
        .await;

        tokio::select! {
            _ = tokio::time::sleep(Duration::from_millis(args.scan_interval_ms)) => {},
            _ = async {
                while !stop.load(Ordering::Relaxed) {
                    tokio::time::sleep(Duration::from_millis(100)).await;
                }
            } => {},
        }
    }

    stop.store(true, Ordering::Relaxed);
    while let Some(result) = active_group.join_next().await {
        if let Err(error) = result {
            log(
                logging,
                "error",
                format!("smart LuckyBag worker group failed: {error}"),
            );
        }
    }
    Ok(())
}

#[tokio::main]
// async def main() -> None:
//     ...
async fn main() -> Result<()> {
    let args = Args::parse();
    if args.smart_luckybag && (args.local_luckybag || args.scan_only || args.join.is_some()) {
        return Err(anyhow!(
            "--smart-luckybag cannot be combined with --local-luckybag, --scan-only, or --join"
        ));
    }
    if args.max_workers == 0 || args.workers_per_room == 0 {
        return Err(anyhow!("max-workers and workers-per-room must be positive"));
    }
    if args.scan_interval_ms == 0 || args.max_pages == 0 {
        return Err(anyhow!("scan interval and max-pages must be positive"));
    }
    if args.claim_attempts == 0 {
        return Err(anyhow!("claim-attempts must be positive"));
    }
    if args.local_refresh_secs == 0
        || args.local_claim_attempts == 0
        || args.local_claim_delay_ms == 0
    {
        return Err(anyhow!(
            "local refresh interval, claim attempts, and claim delay must be positive"
        ));
    }

    let logging = args.logging == LoggingMode::On;
    print_banner(logging);
    log(
        logging,
        "startup",
        format!(
            "mode={}, account argument={}, scan-only={}, join={:?}",
            if logging { "logging on" } else { "logging off" },
            args.accounts.display(),
            args.scan_only,
            args.join
        ),
    );

    let account_path = resolve_account_path(&args.accounts);
    log(
        logging,
        "startup",
        format!("loading accounts from {}", account_path.display()),
    );
    let loaded = load_accounts(&account_path)
        .await
        .with_context(|| format!("failed to load accounts from {}", account_path.display()))?;
    if loaded.is_empty() {
        return Err(anyhow!(
            "no valid accounts found in {}",
            account_path.display()
        ));
    }
    log(
        logging,
        "startup",
        format!("loaded {} account(s)", loaded.len()),
    );
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(10))
        .build()?;

    if args.smart_luckybag {
        let tourist = request_tourist_account(&client)
            .await
            .context("failed to obtain API-issued tourist token")?;
        log(logging, "local", "obtained API-issued tourist token");
        return run_smart_luckybag(&client, &loaded, &tourist, &args, logging).await;
    }

    if args.scan_account_index >= loaded.len() {
        return Err(anyhow!(
            "scan-account-index is outside the loaded account list"
        ));
    }
    let scan_account = loaded[args.scan_account_index].clone();
    log(
        logging,
        "startup",
        format!(
            "scanner uses account {} at index {}",
            scan_account.user_id, args.scan_account_index
        ),
    );

    if let Some(live_user_id) = args.join {
        let room_id =
            resolve_live_room_id(&client, live_user_id, &scan_account.jwt, logging).await?;
        return debug_join_room(room_id, &scan_account, logging).await;
    }

    if args.scan_only {
        return scan_only(&client, &scan_account, &args, logging).await;
    }

    if args.local_luckybag {
        return run_local_luckybag(&client, &loaded, &scan_account, &args, logging).await;
    }

    let accounts = Arc::new(Mutex::new(VecDeque::from(loaded)));
    let active_rooms = Arc::new(Mutex::new(HashSet::new()));
    let worker_semaphore = Arc::new(Semaphore::new(args.max_workers));
    let stop = Arc::new(AtomicBool::new(false));
    let stop_signal = stop.clone();
    let shutdown_logging = logging;
    tokio::spawn(async move {
        if tokio::signal::ctrl_c().await.is_ok() {
            stop_signal.store(true, Ordering::Relaxed);
            log(
                shutdown_logging,
                "shutdown",
                "shutdown requested; waiting for active workers to finish",
            );
        }
    });

    let worker_config = WorkerConfig {
        idle_timeout: Duration::from_secs(args.idle_timeout_secs),
        max_shift: Duration::from_secs(args.max_shift_secs),
        claim_attempts: args.claim_attempts,
        claim_delay: Duration::from_millis(args.claim_delay_ms),
        finish_after_claim: false,
        logging,
    };
    let room_capacity = (args.max_workers / args.workers_per_room).max(1);
    let mut room_tasks = JoinSet::new();
    let mut last_dispatched = BTreeMap::<u64, tokio::time::Instant>::new();

    log(
        logging,
        "startup",
        format!(
            "dispatcher ready: max_workers={}, workers_per_room={}, scan_interval={}ms, max_pages={}, room_cooldown={}s",
            args.max_workers,
            args.workers_per_room,
            args.scan_interval_ms,
            args.max_pages,
            args.room_cooldown_secs
        ),
    );

    let mut scan_round = 0_u64;
    while !stop.load(Ordering::Relaxed) {
        scan_round += 1;
        log(logging, "scan", format!("starting scan round {scan_round}"));
        while room_tasks.try_join_next().is_some() {}

        match scan_lucky_bag_rooms(
            &client,
            &scan_account,
            args.max_pages,
            args.scan_concurrency,
            logging,
        )
        .await
        {
            Ok(rooms) => {
                last_dispatched.retain(|_, last| {
                    last.elapsed() < Duration::from_secs(args.room_cooldown_secs)
                });
                for room in rooms {
                    if room_tasks.len() >= room_capacity {
                        break;
                    }
                    if last_dispatched.get(&room.room_id).is_some_and(|last| {
                        last.elapsed() < Duration::from_secs(args.room_cooldown_secs)
                    }) {
                        continue;
                    }
                    if accounts.lock().await.is_empty() {
                        break;
                    }

                    let newly_active = active_rooms.lock().await.insert(room.room_id);
                    if !newly_active {
                        continue;
                    }
                    last_dispatched.insert(room.room_id, tokio::time::Instant::now());
                    log(
                        logging,
                        "dispatch",
                        format!("scheduling room {} ({})", room.room_id, room.nickname),
                    );
                    room_tasks.spawn(run_room_group(
                        room,
                        accounts.clone(),
                        active_rooms.clone(),
                        worker_semaphore.clone(),
                        worker_config.clone(),
                        args.workers_per_room,
                        stop.clone(),
                    ));
                }
            }
            Err(error) => log(
                logging,
                "error",
                format!("Tamil room scan failed: {error:#}"),
            ),
        }

        tokio::select! {
            _ = tokio::time::sleep(Duration::from_millis(args.scan_interval_ms)) => {},
            _ = async {
                while !stop.load(Ordering::Relaxed) {
                    tokio::time::sleep(Duration::from_millis(100)).await;
                }
            } => {},
        }
    }

    while let Some(result) = room_tasks.join_next().await {
        if let Err(error) = result {
            log(
                logging,
                "error",
                format!("room scheduler task failed: {error}"),
            );
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn account_parser_uses_tamil_column_order() {
        let account = parse_account_line("123,ws-token,jwt-token", 1)
            .unwrap()
            .unwrap();
        assert_eq!(account.user_id, 123);
        assert_eq!(account.ws_token, "ws-token");
        assert_eq!(account.jwt, "jwt-token");
    }

    #[test]
    fn account_parser_skips_comments_and_blank_lines() {
        assert!(parse_account_line(" # comment ", 1).unwrap().is_none());
        assert!(parse_account_line("  ", 2).unwrap().is_none());
    }

    #[test]
    fn account_parser_rejects_wrong_column_order_shape() {
        assert!(parse_account_line("123,jwt-token", 4).is_err());
    }

    #[test]
    fn bag_parser_accepts_string_or_integer_logo_and_room_id() {
        let data = json!({"data":[
            {"room_id":"42","user_id":7,"nickname":"anchor","red_packet_logo":"1"},
            {"room_id":43,"user_id":8,"red_packet_logo":1},
            {"room_id":44,"red_packet_logo":0}
        ]});
        let rooms = parse_bag_rooms(&data);
        assert_eq!(rooms.len(), 2);
        assert_eq!(rooms[0].room_id, 42);
        assert_eq!(rooms[0].anchor_id, 7);
    }

    #[test]
    fn hot_anchor_parser_includes_rooms_without_lucky_bags() {
        let data = json!({"data":[
            {"room_id":"42","user_id":7,"nickname":"anchor","red_packet_logo":"1"},
            {"room_id":43,"user_id":8,"nickname":"live room","red_packet_logo":0}
        ]});
        let rooms = parse_anchor_rooms(&data, false);
        assert_eq!(rooms.len(), 2);
        assert_eq!(rooms[1].room_id, 43);
        assert!(parse_bag_rooms(&data).iter().all(|room| room.room_id == 42));
    }

    #[test]
    fn local_mode_groups_accounts_by_workers_per_room() {
        assert_eq!(local_room_assignment_count(24, 10, 3), 8);
        assert_eq!(local_room_assignment_count(4, 10, 3), 2);
        assert_eq!(local_room_assignment_count(4, 1, 3), 1);
        assert_eq!(local_room_assignment_count(0, 10, 3), 0);
    }

    #[test]
    fn claim_plan_handles_open_bags_and_countdowns() {
        assert_eq!(
            claim_plan(&json!({"ID":5,"Status":1}), 2101),
            Some((5, Duration::ZERO))
        );
        assert_eq!(claim_plan(&json!({"ID":5,"Status":0}), 2100), None);
        assert_eq!(claim_plan(&json!({"ID":0,"Status":1}), 2101), None);
        assert_eq!(
            claim_plan(&json!({"ID":6,"Status":0,"CountDown":4}), 2100),
            Some((6, Duration::from_secs(4)))
        );
    }

    #[test]
    fn api_signature_is_deterministic_and_ignores_sign_field() {
        let mut first = Map::new();
        first.insert("user_id".into(), json!(42));
        first.insert("lang".into(), json!("id"));
        let mut second = first.clone();
        second.insert("sign".into(), json!("not-included"));
        assert_eq!(generate_sign(&first), generate_sign(&second));
    }

    #[test]
    fn hot_anchor_payload_matches_tamil_request_shape() {
        let payload = build_hot_anchor_payload(123, 2).unwrap();
        assert_eq!(payload["page"], 2);
        assert_eq!(payload["user_id"], 123);
        assert!(payload["time"].is_string());
        assert_eq!(payload["package_type"], "haigou-Android");
        assert_eq!(
            payload["sign"].as_str(),
            Some(generate_sign(&payload).as_str())
        );
    }

    #[test]
    fn tamil_join_payload_uses_millisecond_signature() {
        let account = Account {
            user_id: 123,
            ws_token: "sample-token".to_string(),
            jwt: "sample-jwt".to_string(),
        };
        let payload = room_login_payload(&account, 456).unwrap();
        let time_mill = value_u64(&payload["body"]["TimeMill"]).unwrap();
        let raw = format!("{WS_SIGNING_SECRET}{time_mill}{}", account.ws_token);
        let expected = format!("{:x}", md5::compute(raw));
        assert_eq!(payload["op"], 1001);
        assert_eq!(payload["body"]["RoomId"], 456);
        assert_eq!(payload["body"]["Md5Str"], expected);
        assert!(time_mill > 1_000_000_000_000);
    }

    #[test]
    fn tourist_join_payload_matches_satgas_visitor_shape() {
        let account = TouristAccount {
            token: "tourist-token".to_string(),
            api_token: "api-token".to_string(),
            tourist_id: 77777,
        };
        let payload = tourist_room_login_payload(&account, 456).unwrap();
        let timestamp = value_u64(&payload["body"]["TimeMill"]).unwrap();
        let raw = format!("{WS_SIGNING_SECRET}{timestamp}{}", account.token);
        assert_eq!(payload["op"], 1001);
        assert_eq!(payload["body"]["RoomId"], 456);
        assert_eq!(payload["body"]["UserId"], 0);
        assert_eq!(payload["body"]["Visitor"], 1);
        assert_eq!(
            payload["body"]["Md5Str"],
            format!("{:x}", md5::compute(raw))
        );
        assert!(timestamp < 1_000_000_000_000);
    }

    #[test]
    fn tourist_bag_list_parser_reads_numeric_and_string_fields() {
        let bags = parse_scout_bag_list(&json!({
            "List": [
                {"ID": 12, "CountDown": 8},
                {"ID": "13", "CountDown": "3"},
                {"ID": 0, "CountDown": 1},
                {"ID": 14}
            ]
        }));
        assert_eq!(bags, vec![(12, 8), (13, 3)]);
    }

    #[test]
    fn tourist_token_parser_accepts_ws_and_api_tokens() {
        let account = parse_tourist_token_response(&json!({
            "code": 0,
            "data": {
                "token": "websocket-token",
                "jwt_token": "api-token",
                "tourist_id": "77777"
            }
        }))
        .unwrap();
        assert_eq!(account.token, "websocket-token");
        assert_eq!(account.api_token, "api-token");
        assert_eq!(account.tourist_id, 77777);
    }

    #[test]
    fn tourist_token_parser_requires_jwt_for_api_requests() {
        let account = parse_tourist_token_response(&json!({
            "code": "200",
            "data": {"token": "single-token", "tourist_id": 42}
        }));
        assert!(account.is_err());
    }

    #[test]
    fn tourist_token_payload_matches_turis_request() {
        let payload = build_tourist_token_payload().unwrap();
        assert_eq!(payload["type"], 0);
        assert_eq!(payload["app_version"], TOURIST_API_VERSION);
        assert_eq!(payload["user_id"], "0");
        assert_eq!(payload["package_type"], "Android-Google");
        assert_eq!(payload["sign"], generate_sign(&payload));
    }

    #[test]
    fn tourist_hot_anchor_payload_uses_returned_tourist_id() {
        let account = parse_tourist_token_response(&json!({
            "code": 0,
            "data": {
                "token": "websocket-token",
                "jwt_token": "api-token",
                "tourist_id": 77777
            }
        }))
        .unwrap();
        let payload = build_hot_anchor_payload(account.tourist_id, 1).unwrap();
        assert_eq!(payload["user_id"], 77777);
        assert_eq!(payload["page"], 1);
        assert_eq!(payload["sign"], generate_sign(&payload));
    }

    #[test]
    fn smart_queue_picks_earliest_bag_only_when_within_lead_window() {
        let now = tokio::time::Instant::now();
        let room = BagRoom {
            room_id: 1,
            anchor_id: 2,
            nickname: "anchor".to_string(),
        };
        let mut pending = HashMap::new();
        for (bag_id, seconds) in [(1, 12), (2, 4), (3, 2)] {
            pending.insert(
                bag_id,
                PendingSmartBag {
                    bag_id,
                    room: room.clone(),
                    opens_at: now + Duration::from_secs(seconds),
                },
            );
        }
        let selected = next_due_smart_bag(&pending, now).unwrap();
        assert_eq!(selected.bag_id, 3);
        assert_eq!(selected.room.room_id, 1);
    }

    #[test]
    fn successful_api_code_supports_numeric_and_string_forms() {
        assert!(is_success_code(&json!({"code":0})));
        assert!(is_success_code(&json!({"code":"0"})));
        assert!(!is_success_code(&json!({"code":1003})));
    }
}
