use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use tokio::fs::File;
use tokio::io::AsyncBufReadExt;
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};
use url::Url;
use std::time::Duration;
use std::sync::Arc;
use tokio::sync::Mutex;

// --- CONFIGURATION ---
const TEST_ROOM_ID: u64 = 89699; // <--- MAKE SURE THIS IS A LIVE ROOM
const ACCOUNT_FILE: &str = "test";
const WS_URL: &str = "ws://13.213.254.163:9001";

#[tokio::main]
async fn main() {
    println!("🧪 TARGET PRACTICE MODE v2 (AUTO-TIMER) ...");
    println!("🎯 Target Room: {}", TEST_ROOM_ID);

    // 1. Load Account
    let file = File::open(ACCOUNT_FILE).await.expect("Failed to open file");
    let mut lines = tokio::io::BufReader::new(file).lines();
    
    let line = lines.next_line().await.expect("File empty").expect("Read error");
    let parts: Vec<&str> = line.split(',').collect();
    let user_id = parts[0].to_string();
    let token = parts[2].to_string();

    println!("👤 Using Account: {}", user_id);

    // 2. Connect
    let url = Url::parse(WS_URL).unwrap();
    match connect_async(url).await {
        Ok((ws_stream, _)) => {
            println!("✅ WebSocket Connected!");
            let (write, mut read) = ws_stream.split();
            
            // Shared Write Socket (So the timer can use it)
            let write = Arc::new(Mutex::new(write));

            // 3. Send Join Packet
            let join_msg = json!({
                "body": { "RoomId": TEST_ROOM_ID, "Token": token, "UserId": user_id.parse::<u64>().unwrap_or(0), "Lang": "id" },
                "op": 1001, "ver": 1
            });
            write.lock().await.send(Message::Text(join_msg.to_string())).await.unwrap();

            println!("👂 Listening... (I will now auto-fire if a countdown appears)");

            while let Some(msg) = read.next().await {
                if let Ok(Message::Text(text)) = msg {
                    if let Ok(json_msg) = serde_json::from_str::<Value>(&text) {
                        let op = json_msg["op"].as_i64().unwrap_or(0);
                        let body = &json_msg["body"];

                        if op == 2100 {
                            println!("\n🎁 RED PACKET DETECTED!");
                            // println!("📄 Raw: {}", body); // Uncomment to debug raw JSON

                            let lb_exe = body["ID"].as_u64().unwrap_or(0);
                            let status = body["Status"].as_i64().unwrap_or(0);
                            let countdown = body["CountDown"].as_u64().unwrap_or(0);

                            // SCENARIO 1: Open immediately
                            if status == 1 {
                                println!("⚔️  Status is 1. ATTACKING NOW!");
                                let claim_msg = json!({ "body": {"ID": lb_exe}, "op": 2101, "ver": 1 });
                                let mut w = write.lock().await;
                                for _ in 0..3 { w.send(Message::Text(claim_msg.to_string())).await.unwrap(); }
                            } 
                            // SCENARIO 2: Countdown (The Fix)
                            else if countdown > 0 {
                                println!("⏲️  Countdown detected: {}s. Preparing ambush...", countdown);
                                
                                let write_clone = write.clone();
                                let wait_time = countdown;
                                let bag_id = lb_exe;

                                // Spawn a background task to wait and fire
                                tokio::spawn(async move {
                                    println!("⏳ Timer started for Bag {} ({}s)", bag_id, wait_time);
                                    
                                    // Wait for countdown + small buffer (0.1s)
                                    tokio::time::sleep(Duration::from_secs(wait_time) + Duration::from_millis(100)).await;
                                    
                                    println!("🔥 TIMER DONE! FIRING ON BAG {}!", bag_id);
                                    let claim_msg = json!({ "body": {"ID": bag_id}, "op": 2101, "ver": 1 });
                                    
                                    let mut w = write_clone.lock().await;
                                    for i in 1..=3 {
                                        if let Err(e) = w.send(Message::Text(claim_msg.to_string())).await {
                                            println!("❌ Fire failed: {}", e);
                                        } else {
                                            println!("   🚀 Shot {}", i);
                                        }
                                    }
                                });
                            } else {
                                println!("⚠️  Status {} / Countdown 0. Ignored.", body);

                            }
                        }
                        
                        if op == 2101 {
                            println!("💰 CLAIM RESULT: {}", body);
                        }
                    }
                }
            }
        },
        Err(e) => println!("❌ Failed to connect: {}", e)
    }
}