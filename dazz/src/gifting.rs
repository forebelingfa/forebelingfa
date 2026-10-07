use anyhow::Result;
use colored::*;
use futures_util::{SinkExt, StreamExt};
use rand::seq::SliceRandom;
use reqwest::header::{HeaderMap, HeaderValue, CONTENT_TYPE, USER_AGENT};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::sync::{atomic::{AtomicBool, Ordering}, Arc};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::fs::File;
use tokio::io::AsyncBufReadExt;
use tokio::sync::{Mutex, Semaphore};
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};
use uuid::Uuid;

// --- ⚙️ CONFIGURATION DECK ⚙️ ---
const ROOM_ID: u64 = 86372;
const RECEIVER_ID: u64 = 19761489;     // Who gets the gifts
const ACCOUNT_FILE: &str = "black";    // File with accounts
const BATCH_SIZE: usize = 1;           // How many accounts run at once
const MAX_RUNTIME: u64 = 300;          // Max seconds before giving up
const APP_VERSION: &str = "1.9.5";
const WS_URL: &str = "ws://13.213.254.163:9001";
const DAZZ_BASE: &str = "https://api.dazz2.com/api";
const SECRET_KEY: &str = "5d206b343f87f2ca3a0aa05c58b9a64d";

// --- UTILS ---

fn get_timestamp() -> String {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs().to_string()
}

fn md5_hash(input: String) -> String {
    format!("{:x}", md5::compute(input))
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
    md5_hash(param_str)
}

// --- API: CHECK BALANCE ---

async fn check_user_balance(client: &reqwest::Client, user_id: &str, jwt: &str) -> Result<(u64, String)> {
    let url = format!("{}/member/info", DAZZ_BASE);
    let mut payload = serde_json::Map::new();
    
    // Payload Construction
    payload.insert("id".to_string(), json!(user_id));
    payload.insert("user_id".to_string(), json!(user_id));
    payload.insert("version".to_string(), json!(APP_VERSION));
    payload.insert("app_version".to_string(), json!(APP_VERSION));
    payload.insert("channel_id".to_string(), json!("3"));
    payload.insert("device_id".to_string(), json!(Uuid::new_v4().simple().to_string()));
    payload.insert("facility".to_string(), json!("1"));
    payload.insert("lang".to_string(), json!("id"));
    payload.insert("package_type".to_string(), json!("Android-Google"));
    payload.insert("time".to_string(), json!(get_timestamp()));

    let sign = generate_sign(&payload);
    payload.insert("sign".to_string(), json!(sign));

    let mut headers = HeaderMap::new();
    headers.insert(USER_AGENT, HeaderValue::from_str(APP_VERSION)?);
    headers.insert("Authorization-token", HeaderValue::from_str(jwt)?);
    headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json; charset=UTF-8"));
    headers.insert("encrypt-type", HeaderValue::from_static("1"));
    headers.insert("cache-control", HeaderValue::from_static("no-cache"));

    let resp = client.post(&url)
        .headers(headers)
        .json(&payload)
        .timeout(Duration::from_secs(10))
        .send()
        .await?;

    let text = resp.text().await?;
    let json: Value = serde_json::from_str(&text).unwrap_or(json!({}));
    
    let gold = json["data"]["gold"].as_u64().unwrap_or(0);
    let nick = json["data"]["nickname"].as_str().unwrap_or("Unknown").to_string();

    Ok((gold, nick))
}

// --- WORKER LOGIC ---

// --- WORKER LOGIC (RETRY CAPABLE) ---

async fn run_room(user_id: String, token: String, initial_balance: u64) {
    let url_parsed = url::Url::parse(WS_URL).unwrap();
    let start_time = tokio::time::Instant::now(); // Global timer

    // OUTER RETRY LOOP
    loop {
        // 1. Check Runtime
        if start_time.elapsed().as_secs() > MAX_RUNTIME {
            println!("{}", format!("[{}] 🛑 Max Runtime Exceeded. Stopping.", user_id).yellow());
            break;
        }

        match connect_async(url_parsed.clone()).await {
            Ok((ws_stream, _)) => {
                // println!("{}", format!("[{}] 🔌 Connected.", user_id).dimmed()); // Optional debug
                
                let (write, mut read) = ws_stream.split();
                let write = Arc::new(Mutex::new(write));
                let running = Arc::new(AtomicBool::new(true));

                // A. SEND JOIN
                let join_payload = json!({
                    "ver": 1,
                    "op": 1001,
                    "body": {
                        "RoomId": ROOM_ID,
                        "Token": token,
                        "UserId": user_id.parse::<u64>().unwrap_or(0),
                    }
                });
                if write.lock().await.send(Message::Text(join_payload.to_string())).await.is_err() {
                    // Send failed immediately? Retry loop.
                    continue;
                }

                // B. SPAWN HEARTBEAT
                let w_hb = write.clone();
                let r_hb = running.clone();
                tokio::spawn(async move {
                    while r_hb.load(Ordering::Relaxed) {
                        let ping = json!({"op": 9999, "ver": 1});
                        if w_hb.lock().await.send(Message::Text(ping.to_string())).await.is_err() { break; }
                        tokio::time::sleep(Duration::from_secs(1)).await;
                    }
                });

                // C. SPAWN GIFTER
                let w_gift = write.clone();
                let r_gift = running.clone();
                tokio::spawn(async move {
                    let jamet = vec![174, 135, 135, 135];
                    let pelit = vec![11, 0, 0, 2, 1, 0, 1, 99999999];
                    while r_gift.load(Ordering::Relaxed) {
                        // Local RNG (Thread-Safe)
                        let gift_id = *jamet.choose(&mut rand::thread_rng()).unwrap_or(&174);
                        let gift_count = *pelit.choose(&mut rand::thread_rng()).unwrap_or(&174);
                        
                        let gift_payload = json!({
                            "ver": 2,
                            "op": 1069,
                            "body": {
                                "Code": 0, 
                                "InRoomId": ROOM_ID, 
                                "GiftVipId": 1, 
                                "DUserId": [RECEIVER_ID], 
                                "GiftId": gift_id,
                                "GiftCount": gift_count
                            }
                        });

                        if w_gift.lock().await.send(Message::Text(gift_payload.to_string())).await.is_err() { break; }
                        tokio::time::sleep(Duration::from_millis(10)).await;
                    }
                });

                // D. INNER LISTENER LOOP
                let mut stop_outer_loop = false;

                loop {
                    // Check Global Runtime inside the loop too
                    if start_time.elapsed().as_secs() > MAX_RUNTIME {
                        stop_outer_loop = true;
                        break;
                    }

                    match tokio::time::timeout(Duration::from_secs(30), read.next()).await {
                        Ok(Some(Ok(msg))) => {
                            if let Message::Text(text) = msg {
                                if let Ok(data) = serde_json::from_str::<Value>(&text) {
                                    let body = &data["body"];
                                    
                                    // PROFIT CHECK
                                    if let Some(current_saldo) = body["SGold"].as_u64() {
                                        if current_saldo > initial_balance {
                                            println!("{}", format!("[{}] 🤑 PROFIT! Balance: {} -> {}. STOPPING.", user_id, initial_balance, current_saldo).green().bold());
                                            stop_outer_loop = true; // VICTORY -> Stop Retrying
                                            break;
                                        }
                                    }

                                    // SERVER KICK
                                    if body["Code"].as_i64().unwrap_or(0) == 1021 {
                                        println!("{}", format!("[{}] 💀 Kicked by Server (1021).", user_id).red());
                                        stop_outer_loop = true; // KICKED -> Stop Retrying
                                        break;
                                    }

                                    // AUTO CLAIM (Optional)
                                    let op = data["op"].as_i64().unwrap_or(0);
                                    if op > 2000 {
                                        if let Some(lb_id) = body["ID"].as_u64() {
                                            let claim = json!({"body": {"ID": lb_id}, "op": 2101, "ver": 1});
                                            write.lock().await.send(Message::Text(claim.to_string())).await.ok();
                                        }
                                    }
                                }
                            }
                        },
                        Ok(Some(Err(_))) => break, // Stream Error -> Break Inner -> Trigger Retry
                        Ok(None) => break, // Stream Closed -> Break Inner -> Trigger Retry
                        Err(_) => continue, // Timeout -> Continue Inner
                    }
                }

                // Cleanup Threads
                running.store(false, Ordering::Relaxed);

                // Decide: Retry or Quit?
                if stop_outer_loop {
                    break; // Exit Function
                } else {
                    println!("{}", format!("[{}] ⚠️ Connection Lost. Retrying in 2s...", user_id).yellow());
                    tokio::time::sleep(Duration::from_secs(2)).await;
                }
            }
            Err(e) => {
                println!("{}", format!("[{}] ❌ Connection Failed: {}. Retrying in 3s...", user_id, e).red());
                tokio::time::sleep(Duration::from_secs(3)).await;
            }
        }
    }
}
// --- MAIN ENGINE ---

#[tokio::main]
async fn main() -> Result<()> {
    // Banner
    println!("{}", "╔══════════════════════════════════════════════╗".cyan());
    println!("{}", "║        🎁  DAZZ RUST GIFTER v1.1  🎁         ║".cyan());
    println!("{}", "║      Fast, Threaded, Profit-Stopping         ║".cyan());
    println!("{}", "╚══════════════════════════════════════════════╝".cyan());

    let client = reqwest::Client::new();
    
    // Load Accounts
    let file = File::open(ACCOUNT_FILE).await;
    if file.is_err() {
        println!("{}", format!("❌ File '{}' not found!", ACCOUNT_FILE).red());
        return Ok(());
    }
    
    let mut lines = tokio::io::BufReader::new(file.unwrap()).lines();
    let mut accounts = Vec::new();
    
    while let Ok(Some(line)) = lines.next_line().await {
        if line.trim().is_empty() { continue; }
        let parts: Vec<&str> = line.split(',').collect();
        if parts.len() >= 3 {
            accounts.push((parts[0].to_string(), parts[1].to_string(), parts[2].to_string()));
        }
    }

    println!("{}", format!("🦜 Loaded {} accounts.", accounts.len()).yellow());
    
    // Semaphore allows `BATCH_SIZE` concurrent workers (Like the python c%d logic)
    let semaphore = Arc::new(Semaphore::new(BATCH_SIZE));
    let mut handles = Vec::new();

    for (uid, jwt, token) in accounts {
        let sem_clone = semaphore.clone();
        let client_clone = client.clone();
        
        // Spawn Task
        let handle = tokio::spawn(async move {
            let _permit = sem_clone.acquire().await.unwrap(); // Wait for slot
            
            // 1. Check Balance
            print!("{}", format!("[{}] 🔍 Checking Balance...", uid).dimmed());
            use std::io::Write;
            std::io::stdout().flush().unwrap();

            match check_user_balance(&client_clone, &uid, &jwt).await {
                Ok((gold, nick)) => {
                    println!("\r{}", format!("[{}] ✅ {} | Gold: {}", uid, nick, gold).green());
                    
                    // 2. Start Gifting Loop
                    run_room(uid, token, gold).await;
                },
                Err(e) => {
                    println!("\r{}", format!("[{}] ❌ Check Failed: {}", uid, e).red());
                }
            }
        });
        handles.push(handle);
    }

    // Wait for all
    futures_util::future::join_all(handles).await;
    println!("\n{}", "🏁 All tasks finished.".magenta().bold());

    Ok(())
}