use anyhow::Result;
use futures_util::{SinkExt, StreamExt};
// REMOVED: No longer need a `use` statement for md5
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::HashMap,
    env,
    fs::File,
    io::{self, BufRead},
    sync::Arc,
    time::Duration,
};
use tokio::sync::Mutex;
use tokio_tungstenite::{
    connect_async, tungstenite::protocol::Message,
};

// --- Configuration ---
const APP_VERSION: &str = "1.9.2";
const WS_URL: &str = "ws://13.213.254.163:9001";

const MAX_RETRIES: u32 = 70;
const INITIAL_RETRY_DELAY_MS: u64 = 500;

// --- Utility Functions ---

/// Reads a token file with format: userid,jwt,token per line.
/// Returns a Vec of (user_id, jwt, token) tuples.
fn load_token_file(file_path: &str) -> Result<Vec<(i64, String, String)>> {
    let file = match File::open(file_path) {
        Ok(file) => file,
        Err(_) => {
            println!("[!] Token file '{}' not found.", file_path);
            return Ok(Vec::new());
        }
    };

    let reader = io::BufReader::new(file);
    let mut tokens = Vec::new();

    for (line_num, line) in reader.lines().enumerate() {
        if let Ok(line) = line {
            let parts: Vec<&str> = line.split(',').collect();
            if parts.len() == 3 {
                match (parts[0].parse::<i64>(), parts[1].to_string(), parts[2].to_string()) {
                    (Ok(user_id), jwt, token) => {
                        tokens.push((user_id, jwt, token));
                    }
                    _ => {
                        println!("[!] Line {}: Failed to parse user_id as i64", line_num + 1);
                    }
                }
            } else {
                println!("[!] Line {}: Expected 3 fields (userid,jwt,token), got {}", line_num + 1, parts.len());
            }
        }
    }

    println!("[✓] Loaded {} accounts from '{}'", tokens.len(), file_path);
    Ok(tokens)
}

#[derive(Serialize, Deserialize)]
struct JoinPayloadBody {
    #[serde(rename = "DeviceType")]
    device_type: u8,
    #[serde(rename = "EnterType")]
    enter_type: u8,
    #[serde(rename = "FuncLevel")]
    func_level: u16,
    #[serde(rename = "Lang")]
    lang: String,
    #[serde(rename = "Md5Str")]
    md5_str: String,
    #[serde(rename = "RoomId")]
    room_id: i64,
    #[serde(rename = "TimeMill")]
    time_mill: u64,
    #[serde(rename = "Token")]
    token: String,
    #[serde(rename = "Tourist")]
    tourist: u8,
    #[serde(rename = "UserId")]
    user_id: i64,
    #[serde(rename = "Version")]
    version: String,
    package_type: String,
}

#[derive(Serialize, Deserialize)]
struct WsPayload<T> {
    body: T,
    op: u16,
    ver: u8,
}

/// Main async function for a single WebSocket connection with retry logic.
async fn dazz_websocket(room_id: i64, user_id: i64, token_id: String) {
    let mut attempt = 1;
    let mut delay = INITIAL_RETRY_DELAY_MS;
    
    loop {
        match run_websocket_logic(room_id, user_id, token_id.clone()).await {
            Ok(_) => {
                println!("[{}] WebSocket session completed successfully.", user_id);
                break;
            }
            Err(e) => {
                if attempt >= MAX_RETRIES {
                    println!("[!] User {} failed after {} attempts: {}", user_id, MAX_RETRIES, e);
                    break;
                }
                
                println!("[⚠️] User {} - Attempt {}/{} failed: {}. Retrying in {}ms...", 
                    user_id, attempt, MAX_RETRIES, e, delay);
                
                tokio::time::sleep(Duration::from_millis(delay)).await;
                
                // Exponential backoff: double the delay, cap at 30 seconds
                delay = (delay * 2).min(30000);
                attempt += 1;
            }
        }
    }
    
    println!("[{}] Disconnected.", user_id);
}

/// Contains the actual logic for the WebSocket connection to allow for easy error handling.
async fn run_websocket_logic(room_id: i64, user_id: i64, token_id: String) -> Result<()> {
    let (ws_stream, _) = connect_async(WS_URL).await?;
    let (write, mut read) = ws_stream.split();

    let writer = Arc::new(Mutex::new(write));
    let claim_status: Arc<Mutex<HashMap<i64, i64>>> = Arc::new(Mutex::new(HashMap::new()));
    let active_loops: Arc<Mutex<Vec<i64>>> = Arc::new(Mutex::new(Vec::new()));

    let mili_time = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_millis() as u64;
    let md5str = {
        let salt = "5d206b343f87f2ca3a0aa05c58b9a64d";
        let raw = format!("{}{}{}", mili_time, token_id, salt);
        // CORRECTED: Use `md5::compute` here as well
        let digest = md5::compute(raw.as_bytes());
        format!("{:x}", digest)
    };

    let join_payload = WsPayload {
        body: JoinPayloadBody {
            device_type: 1,
            enter_type: 0,
            func_level: 256,
            lang: "id".to_string(),
            md5_str: md5str, 
            room_id,
            time_mill: mili_time,
            token: token_id.clone(),
            tourist: 0,
            user_id,
            version: APP_VERSION.to_string(),
            package_type: "haigou-Android".to_string(),
        },
        op: 1001,
        ver: 1,
    };
    let join_payload_str = serde_json::to_string(&join_payload)?;
    writer.lock().await.send(Message::Text(join_payload_str)).await?;
    println!("[{}] → Connected and joining room {}", user_id, room_id);

    loop {
        match read.next().await {
            Some(Ok(msg)) => {
                if let Message::Text(text) = msg {
                    if let Ok(msg_data) = serde_json::from_str::<Value>(&text) {
                        if let (Some(op_type), Some(body)) = (msg_data.get("op"), msg_data.get("body")) {
                            if op_type.as_u64().unwrap_or(0) > 2000 && body.get("ID").is_some() {
                                let lb_id = body["ID"].as_i64().unwrap_or(0);
                                if body.get("Status").is_some() {
                                    let status = body["Status"].as_i64().unwrap_or(0);
                                    let mut claim_status_lock = claim_status.lock().await;
                                    claim_status_lock.insert(lb_id, status);
                                } else {
                                    let mut active_loops_lock = active_loops.lock().await;
                                    if lb_id != 0 && !active_loops_lock.contains(&lb_id) {
                                        active_loops_lock.push(lb_id);
                                        let writer_clone = Arc::clone(&writer);
                                        tokio::spawn(async move {
                                            println!("[{}] 💥 Starting persistent claim loop for LB_EXE={}", user_id, lb_id);
                                            loop {
                                                let payload = serde_json::json!({ "body": {"ID": lb_id}, "op": 2101, "ver": 1 });
                                                let mut writer_guard = writer_clone.lock().await;
                                                if writer_guard.send(Message::Text(payload.to_string())).await.is_err() {
                                                    break;
                                                }
                                                tokio::time::sleep(Duration::from_millis(100)).await;
                                            }
                                        });
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Some(Err(e)) => {
                println!("[!] WebSocket error for user {}: {}", user_id, e);
                break;
            }
            None => break,
        }
    }
    Ok(())
}


#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    
    // Parse command-line arguments
    let mut token_file = String::from("tokens.txt");
    let mut line_start: usize = 0;
    let mut line_end: Option<usize> = None;
    let mut target_room_id: i64 = 86791;
    
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--token" | "-t" => {
                if i + 1 < args.len() {
                    token_file = args[i + 1].clone();
                    i += 2;
                } else {
                    eprintln!("[!] Error: --token requires a file path");
                    return Ok(());
                }
            }
            "--linestart" | "-s" => {
                if i + 1 < args.len() {
                    match args[i + 1].parse::<usize>() {
                        Ok(n) => {
                            line_start = n.saturating_sub(1); // Convert 1-indexed to 0-indexed
                            i += 2;
                        }
                        Err(_) => {
                            eprintln!("[!] Error: --linestart requires a number");
                            return Ok(());
                        }
                    }
                } else {
                    eprintln!("[!] Error: --linestart requires a number");
                    return Ok(());
                }
            }
            "--lineend" | "-e" => {
                if i + 1 < args.len() {
                    match args[i + 1].parse::<usize>() {
                        Ok(n) => {
                            line_end = Some(n); // Keep 1-indexed for range end
                            i += 2;
                        }
                        Err(_) => {
                            eprintln!("[!] Error: --lineend requires a number");
                            return Ok(());
                        }
                    }
                } else {
                    eprintln!("[!] Error: --lineend requires a number");
                    return Ok(());
                }
            }
            "--room" | "-r" => {
                if i + 1 < args.len() {
                    match args[i + 1].parse::<i64>() {
                        Ok(n) => {
                            target_room_id = n;
                            i += 2;
                        }
                        Err(_) => {
                            eprintln!("[!] Error: --room requires a number");
                            return Ok(());
                        }
                    }
                } else {
                    eprintln!("[!] Error: --room requires a number");
                    return Ok(());
                }
            }
            _ => {
                eprintln!("[!] Unknown argument: {}", args[i]);
                eprintln!("Usage: {} [--token <file>] [--linestart <num>] [--lineend <num>] [--room <id>]", args[0]);
                return Ok(());
            }
        }
    }

    println!("[⚙️] Preparing accounts...");
    let token_list = load_token_file(&token_file)?;

    if token_list.is_empty() {
        println!("[!] No accounts found in the token file.");
        return Ok(());
    }

    // Calculate the range of accounts to use
    let end_idx = line_end.unwrap_or(token_list.len()).min(token_list.len());
    
    if line_start >= token_list.len() {
        println!("[!] linestart {} is out of range. Token list has {} accounts.", line_start + 1, token_list.len());
        return Ok(());
    }
    
    let accounts_to_join = &token_list[line_start..end_idx];
    println!("\n[🚀] Dispatching {} accounts to room {}...", accounts_to_join.len(), target_room_id);

    let mut handles = vec![];
    for (user_id, _jwt, token) in accounts_to_join {
        let handle = tokio::spawn(dazz_websocket(target_room_id, *user_id, token.clone()));
        handles.push(handle);
        tokio::time::sleep(Duration::from_millis(200)).await;
    }

    println!("\n[✓] All {} tasks started. Press CTRL+C to stop.", handles.len());

    tokio::signal::ctrl_c().await?;
    println!("\n[!] CTRL+C detected. Shutting down.");
    println!("[✓] Exiting.");
    Ok(())
}