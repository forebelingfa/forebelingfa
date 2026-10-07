use anyhow::Result;
use futures_util::{stream::{self, StreamExt}, SinkExt};
use reqwest::header::{HeaderMap, HeaderValue, USER_AGENT, CONTENT_TYPE};
use serde_json::{json, Value};
use std::collections::{BTreeMap, HashSet};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::fs::File;
use tokio::io::AsyncBufReadExt;
use tokio::sync::{Mutex, Semaphore};
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};
use uuid::Uuid;
use chrono::Local; // For pretty timestamps
// use std::io::Write; // For flushing stdout
use std::sync::atomic::{AtomicBool, Ordering};
use clap::Parser;
// use std::path::PathBuf;

// --- CONFIGURATION ---
const DAZZ_BASE: &str = "https://api.dazz2.com/api";
const WS_URL: &str = "ws://13.213.254.163:9001";
const ACCOUNT_FILE: &str = "selasa";
const MAX_WORKERS: usize = 20;
const WORKER_GROUP_SIZE: usize = 1;
const SCAN_WORKER: usize = 100;

const SECRET_KEY: &str = "5d206b343f87f2ca3a0aa05c58b9a64d";
const APP_VERSION: &str = "1.9.9"; // Update to 1.9.9
const WS_SALT: &str = "tyxaefcverr4662xse#bfh790jnfe@ss";
const TIME_OFFSET: u64 = 28445478; // The "Future Secret" offset

// Main User for scanning
const MAIN_USER_ID: u64 = 19595547;
const MAIN_JWT: &str = "eyJ0eXAiOiJKV1QiLCJhbGciOiJTSEEyNTYifQ";

// --- COLORS ---
const RESET: &str = "\x1b[0m";
const RED: &str = "\x1b[31m";
const GREEN: &str = "\x1b[32m";
const YELLOW: &str = "\x1b[33m";

// const BLUE: &str = "\x1b[34m";
const MAGENTA: &str = "\x1b[35m";
const CYAN: &str = "\x1b[36m";
const GRAY: &str = "\x1b[90m";
// const BOLD: &str = "\x1b[1m";

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    /// Path to the account file
    #[arg(short, long, default_value = ACCOUNT_FILE)]
    account_file: String,

    /// An optional flag for "pirate mode"
    #[arg(short, long)]
    pirate: bool,
}

#[derive(Clone, Debug)]
struct Account {
    user_id: String,
    _jwt: String,
    token: String,
}

#[derive(Clone)]
struct AppState {
    active_rooms: Arc<Mutex<HashSet<u64>>>,
    account_queue: Arc<Mutex<Vec<Account>>>,
}

// --- LOGGING HELPER ---
fn log(icon: &str, color: &str, msg: String) {
    let now = Local::now().format("%H:%M:%S");
    // \x1b[2K clears the current line (removing the status bar temporarily)
    println!("\x1b[2K{} {}[{}]{} {}{}", icon, GRAY, now, RESET, color, msg);
}

// --- UTILS ---

fn get_timestamp() -> String {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs().to_string()
}

fn generate_sign(payload: &serde_json::Map<String, Value>) -> String {
    let mut sorted_params: BTreeMap<String, String> = BTreeMap::new();
    for (k, v) in payload {
        if k == "sign" || k == "CREATOR" || k == "serialVersionUID" { continue; }
        let val_str = match v {
            Value::String(s) => s.clone(),
            Value::Number(n) => n.to_string(),
            Value::Bool(b) => b.to_string(),
            _ => v.to_string(),
        };
        sorted_params.insert(k.clone(), val_str);
    }
    let mut param_str = String::new();
    for (k, v) in sorted_params {
        if !param_str.is_empty() { param_str.push('&'); }
        param_str.push_str(&format!("{}={}", k, v));
    }
    param_str.push_str(&format!("&key={}", SECRET_KEY));
    format!("{:x}", md5::compute(param_str))
}

// --- API CLIENT ---

async fn fetch_single_page(client: &reqwest::Client, page_num: u64) -> Result<(Vec<u64>, u64)> {
    let url = format!("{}/home/hot_anchor", DAZZ_BASE);
    let mut payload = serde_json::Map::new();
    
    payload.insert("page".to_string(), json!(page_num));
    payload.insert("type".to_string(), json!(1));
    payload.insert("user_id".to_string(), json!(MAIN_USER_ID)); 
    payload.insert("classify_id".to_string(), json!(0));
    payload.insert("group_id".to_string(), json!(0));
    payload.insert("home_id".to_string(), json!(0));
    payload.insert("version".to_string(), json!(APP_VERSION));
    payload.insert("time".to_string(), json!(get_timestamp()));
    payload.insert("device_id".to_string(), json!(Uuid::new_v4().simple().to_string()));
    payload.insert("package_type".to_string(), json!("haigou-Android"));
    payload.insert("lang".to_string(), json!("id"));
    payload.insert("pkg".to_string(), json!("3"));

    let sign = generate_sign(&payload);
    payload.insert("sign".to_string(), json!(sign));

    let mut headers = HeaderMap::new();
    headers.insert(USER_AGENT, HeaderValue::from_str(APP_VERSION)?);
    headers.insert("Authorization-token", HeaderValue::from_str(MAIN_JWT)?);
    headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json; charset=UTF-8"));

    let resp = client.post(&url)
        .headers(headers)
        .json(&payload)
        .timeout(Duration::from_secs(10)) 
        .send()
        .await?;

    if !resp.status().is_success() {
        return Ok((Vec::new(), 1));
    }

    let body_text = resp.text().await?;
    let body: Value = serde_json::from_str(&body_text).unwrap_or(json!({}));
    
    let last_page = match body["data"]["last_page"] {
        Value::Number(ref n) => n.as_u64().unwrap_or(1),
        Value::String(ref s) => s.parse::<u64>().unwrap_or(1),
        _ => 1,
    };

    let mut rooms = Vec::new();
    if let Some(data_list) = body["data"]["data"].as_array() {
        for item in data_list {
            let room_id = match item["room_id"] {
                Value::String(ref s) => s.parse::<u64>().unwrap_or(0),
                Value::Number(ref n) => n.as_u64().unwrap_or(0),
                _ => 0,
            };
            let has_logo = match item["red_packet_logo"] {
                Value::Number(ref n) => n.as_i64().unwrap_or(0) == 1,
                Value::String(ref s) => s == "1",
                _ => false,
            };
            if room_id > 0 && has_logo {
                rooms.push(room_id);
            }
        }
    }
    Ok((rooms, last_page))
}

async fn fetch_hot_rooms(client: &reqwest::Client) -> Result<Vec<u64>> {
    let (mut all_rooms, last_page) = fetch_single_page(client, 1).await?;

    if last_page > 1 {
        let pages = stream::iter(2..=last_page);
        let mut stream = pages
            .map(|page| {
                let client = client.clone();
                async move { fetch_single_page(&client, page).await }
            })
            .buffer_unordered(SCAN_WORKER); 

        while let Some(result) = stream.next().await {
            if let Ok((rooms, _)) = result {
                all_rooms.extend(rooms);
            }
        }
    }

    // inject room id
    if !all_rooms.contains(&42449) {
        all_rooms.push(42449);
    }
    Ok(all_rooms)
}

async fn run_worker(room_id: u64, account: Account) {
    let url_parsed = url::Url::parse(WS_URL).unwrap();
    const WORKER_IDLE_TIMEOUT: u64 = 180; 
    const MAX_SHIFT_DURATION: u64 = 200;

    let mut last_activity = tokio::time::Instant::now();
    let mut shift_end = tokio::time::Instant::now() + Duration::from_secs(MAX_SHIFT_DURATION);
    let mut current_stop_signal: Option<Arc<AtomicBool>> = None;

    loop {
        let now = tokio::time::Instant::now();
        if now > shift_end || now.duration_since(last_activity).as_secs() > WORKER_IDLE_TIMEOUT { break; }

        match connect_async(url_parsed.clone()).await {
            Ok((ws_stream, _)) => {
                let (write, mut read) = ws_stream.split();
                let write = Arc::new(Mutex::new(write));

                // === 1.9.9 SECURE HANDSHAKE ===
                let now_seconds = SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap()
                    .as_secs();
                
                // Aligning with the Jan 2026 "Future Secret" range
                let time_mill = now_seconds + TIME_OFFSET;
                
                // FIXED ORDER: SALT + TimeMill + Token (Based on your working Frida log)
                let sign_data = format!("{}{}{}", WS_SALT, time_mill, account.token);
                let md5_str = format!("{:x}", md5::compute(sign_data));

                let join_msg = json!({
                    "body": {
                        "DeviceType": 1,
                        "EnterType": 0,
                        "FuncLevel": 1280,
                        "IsSmallDialog": 0,
                        "Lang": "id",
                        "Md5Str": md5_str,
                        "RoomId": room_id, // Ensure this is a number
                        "TimeMill": time_mill, // Ensure this is a number
                        "Token": account.token,
                        "UserId": account.user_id.parse::<u64>().unwrap_or(0),
                        "Version": APP_VERSION,
                        "package_type": "haigou-Android"
                    },
                    "op": 1001,
                    "ver": 1
                });

                if let Err(e) = write.lock().await.send(Message::Text(join_msg.to_string())).await {
                    log("❌", RED, format!("Handshake failed: {}", e));
                    continue; 
                }

                // Heartbeat task to prevent 1.9.9 disconnects
                let write_heart = write.clone();
                tokio::spawn(async move {
                    loop {
                        tokio::time::sleep(Duration::from_secs(30)).await;
                        if let Ok(mut w) = write_heart.try_lock() {
                            if let Err(_) = w.send(Message::Text("heart".to_string())).await { break; }
                        }
                    }
                });

                loop {
                    let now = tokio::time::Instant::now();
                    if now > shift_end || now.duration_since(last_activity).as_secs() > WORKER_IDLE_TIMEOUT { 
                        // Before leaving, ensure we stop any running attacks
                        if let Some(ref signal) = current_stop_signal { signal.store(true, Ordering::Relaxed); }
                        return; 
                    }

                    match tokio::time::timeout(Duration::from_secs(15), read.next()).await {
                        Ok(Some(Ok(message))) => {
                            if let Message::Text(text) = message {
                                 if let Ok(json_msg) = serde_json::from_str::<Value>(&text) {
                                    let op = json_msg["op"].as_i64().unwrap_or(0);
                                    let body = &json_msg["body"];
                                    
                                    if op == 2100 || op == 2101 { last_activity = now; }

                                    // EXTEND SHIFT
                                    if op == 2100 && body["LuckyBagData"].is_object() {
                                        if let Some(cd) = body["CountDown"].as_u64() {
                                             if cd > 0 { shift_end = now + Duration::from_secs(cd + 10); }
                                        }
                                    }

                                    let lb_exe = body["ID"].as_u64().unwrap_or(0);
                                    let status = body["Status"].as_i64().unwrap_or(0);
                                    let countdown = body["CountDown"].as_u64().unwrap_or(0);

                                    // === 🔫 START ATTACK (OP 2100) ===
                                    let should_attack = (lb_exe > 0 && status == 1) || (lb_exe > 0 && countdown > 0);

                                    if should_attack {
                                        let pay_aload = json!({ "body": {"ID": lb_exe}, "op": 2101, "ver": 1 }).to_string();
                                        // 1. Stop any previous attack just in case
                                        if let Some(ref signal) = current_stop_signal {
                                            signal.store(true, Ordering::Relaxed);
                                        }

                                        // 2. Create NEW Kill Switch for this bag
                                        let stop_signal = Arc::new(AtomicBool::new(false));
                                        current_stop_signal = Some(stop_signal.clone());

                                        let wait_time = if status == 1 { 0 } else { countdown };
                                        let write_clone = write.clone();
                                        // let acc_uid = account.user_id.clone();
                                        
                                        if wait_time > 0 {
                                            log("⏲️", YELLOW, format!("[Room {}] Ambush set: {}s for Bag {}", room_id, wait_time, lb_exe));
                                        } else {
                                            log("💰", GREEN, format!("[Room {}] OPEN FIRE on Bag {}", room_id, lb_exe));
                                        }

                                        // 3. SPAWN ENDLESS GUNNER
                                        tokio::spawn(async move {
                                            // A. Wait phase
                                            if wait_time > 0 {
                                                let sleep_dur = if wait_time > 1 { Duration::from_secs(wait_time) - Duration::from_millis(250) } else { Duration::from_millis(1) };
                                                tokio::time::sleep(sleep_dur).await;
                                            }

                                            // B. Payloads
                                            // let pay_b = json!({ "body": {"ID": lb_exe.to_string()}, "op": 2101, "ver": 1 }).to_string();
                                            // let pay_c = json!({ "body": {"ID": lb_exe, "UserId": acc_uid}, "op": 2101, "ver": 1 }).to_string();

                                            // C. FIRE UNTIL STOPPED
                                            // Safety: Stop after 15 seconds automatically to prevent zombies
                                            let start_attack = tokio::time::Instant::now();
                                            
                                            while !stop_signal.load(Ordering::Relaxed) {
                                                if start_attack.elapsed().as_secs() > 15 { break; }

                                                let mut w = write_clone.lock().await;
                                                // Fire burst
                                                let _ = w.send(Message::Text(pay_aload.clone())).await;
                                                // let _ = w.send(Message::Text(pay_b.clone())).await;
                                                // let _ = w.send(Message::Text(pay_c.clone())).await;
                                                drop(w); // Release lock fast

                                                // Aggressive Speed: 100ms delay
                                                tokio::time::sleep(Duration::from_millis(10)).await;
                                            }
                                            // log("🛑", GRAY, format!("Cease Fire on Bag {}", lb_exe)); 
                                        });
                                        last_activity = now;
                                    }

                                    // === 🛑 STOP ATTACK (OP 2101) ===
                                    if op == 2101 {
                                        let code = body["Code"].as_i64().unwrap_or(-999);
                                        match code {
                                            0 => {
                                                // WINNER -> STOP
                                                if let Some(ref signal) = current_stop_signal { signal.store(true, Ordering::Relaxed); }
                                                log("💎", GREEN, format!("[{}][Room {}] WINNER! Gold: {}", account.user_id, room_id, body["Gold"]));
                                            },
                                            1014 => {
                                                // EMPTY -> STOP
                                                if let Some(ref signal) = current_stop_signal { signal.store(true, Ordering::Relaxed); }
                                                log("💀", GRAY, format!("[{}][Room {}] Bag Empty. Stopping fire.", account.user_id, room_id));
                                            },
                                            -1 => {
                                                // BUSY -> IGNORE (Loop continues firing!)
                                                // log("⚠️", YELLOW, format!("[{}][Room {}] Server Busy. Keep firing!", account.user_id, room_id));
                                            },
                                            _ => {
                                                // UNKNOWN ERROR -> STOP (Safe bet)
                                                if let Some(ref signal) = current_stop_signal { signal.store(true, Ordering::Relaxed); }
                                                log("🧾", CYAN, format!("[{}][Room {}] Result: {}", account.user_id, room_id, body));
                                            }
                                        }
                                    }
                                 }
                            }
                        }
                        Ok(Some(Err(_))) => break, 
                        Ok(None) => break, 
                        Err(_) => continue, 
                    }
                }
                if let Some(ref signal) = current_stop_signal { signal.store(true, Ordering::Relaxed); }
                tokio::time::sleep(Duration::from_secs(1)).await;
            }
            Err(_) => { tokio::time::sleep(Duration::from_secs(1)).await; }
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    print!("\x1b[2J\x1b[1;1H");
    println!("{}╔══════════════════════════════════════════════╗{}", CYAN, RESET);
    println!("{}║          🏴‍☠️  THE FLYING DUTCHMAN 🏴‍☠️        ║{}", CYAN, RESET);
    println!("{}║                                              ║{}", CYAN, RESET);
    println!("{}╚══════════════════════════════════════════════╝{}", CYAN, RESET);

        
    let file = File::open(args.account_file).await;
    if file.is_err() {
        log("❌", RED, format!("File not found!"));
        return Ok(());
    }
    
    let mut lines = tokio::io::BufReader::new(file.unwrap()).lines();
    let mut accounts = Vec::new();
    while let Ok(Some(line)) = lines.next_line().await {
        if line.trim().is_empty() { continue; }
        let parts: Vec<&str> = line.split(',').collect();
        if parts.len() >= 3 {
            accounts.push(Account { user_id: parts[0].to_string(), _jwt: parts[1].to_string(), token: parts[2].to_string() });
        }
    }
    log("🦜", YELLOW, format!("Crew Assembled: {} accounts ready with {} accounts/room", accounts.len(), WORKER_GROUP_SIZE));

    let app_state = AppState {
        active_rooms: Arc::new(Mutex::new(HashSet::new())), // Keeps track of rooms being hunted
        account_queue: Arc::new(Mutex::new(accounts)),
    };

    let client = reqwest::Client::builder().timeout(Duration::from_secs(10)).build()?;
    // This semaphore limits TOTAL sharks globally (e.g. 24)
    let semaphore = Arc::new(Semaphore::new(MAX_WORKERS)); 

    // log("📡", MAGENTA, "Radar Activated. Hunting for Gold...".to_string());
    
    loop {
        // Update Status Bar
        // let active_count = app_state.active_rooms.lock().await.len();
        // let queue_count = app_state.account_queue.lock().await.len();
        // let hunting_sharks = MAX_WORKERS - semaphore.available_permits();

        // print!("\r{}⏳ STATUS: ActiveRooms=[{}] | HuntingSharks=[{}] | ReserveCrew=[{}] | Scanning...{}", 
        //     BOLD, active_count, hunting_sharks, queue_count, RESET);
        // std::io::stdout().flush().unwrap();

        match fetch_hot_rooms(&client).await {
            Ok(rooms) => {
                let mut active_guard = app_state.active_rooms.lock().await;
                
                for room_id in rooms {
                    // 🛑 CRITICAL CHECK: If room is already in active_guard, SKIP IT.
                    // This prevents sending a 2nd, 3rd, 4th crew to the same room.
                    if active_guard.contains(&room_id) {
                        continue;
                    }

                    // Check if we have enough reserve crew for a full group
                    // Optional: If you want to require at least 1 account to start
                    let queue_len = app_state.account_queue.lock().await.len();
                    if queue_len == 0 {
                        continue; 
                    }

                    log("🔭", MAGENTA, format!("🧧 {}", room_id));
                    
                    // Mark as Active IMMEDIATELY so next loop skips it
                    active_guard.insert(room_id);

                    let state_clone = app_state.clone();
                    let sem_clone = semaphore.clone();
                    
                    // Spawn the Room Manager
                    tokio::spawn(async move {
                        // 1. Recruit Crew (Max 3)
                        let mut workers = Vec::new();
                        let mut acc_lock = state_clone.account_queue.lock().await;
                        for _ in 0..WORKER_GROUP_SIZE {
                            if !acc_lock.is_empty() { workers.push(acc_lock.remove(0)); }
                        }
                        drop(acc_lock); 

                        // 2. If no crew, abort and release room
                        if workers.is_empty() {
                            let mut active = state_clone.active_rooms.lock().await;
                            active.remove(&room_id);
                            return; 
                        }

                        // log("🦈", CYAN, format!("Attacking Room {} with {} sharks...", room_id, workers.len()));

                        // 3. Launch Workers
                        let mut handles = Vec::new();
                        for acc in workers.clone() {
                            // Acquire global permit (waits if >24 total sharks are out)
                            let permit = sem_clone.clone().acquire_owned().await.unwrap();
                            let r_id = room_id;
                            handles.push(tokio::spawn(async move {
                                run_worker(r_id, acc).await;
                                drop(permit); // Release permit when done
                            }));
                        }

                        // 4. Wait for this room's crew to finish
                        futures_util::future::join_all(handles).await;

                        // 5. Recycle Crew
                        let mut acc_lock = state_clone.account_queue.lock().await;
                        for acc in workers { acc_lock.push(acc); }
                        
                        // 6. Release Room (Allow it to be targeted again)
                        let mut active = state_clone.active_rooms.lock().await;
                        active.remove(&room_id);
                        log("💀", GRAY, format!("Room {} depleted (Crew returning).", room_id));
                    });
                }
            }
            Err(_) => {}
        }

        // Scan Interval
        tokio::time::sleep(Duration::from_millis(1)).await;
    }
}