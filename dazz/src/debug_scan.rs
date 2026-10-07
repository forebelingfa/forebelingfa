use reqwest::header::{HeaderMap, HeaderValue, USER_AGENT, CONTENT_TYPE};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::time::{SystemTime, UNIX_EPOCH};
use uuid::Uuid;
use md5;

// --- CONFIGURATION ---
const APP_VERSION: &str = "1.9.5";
const DAZZ_BASE: &str = "https://api.dazz2.com/api";
const SECRET_KEY: &str = "5d206b343f87f2ca3a0aa05c58b9a64d";
const MAIN_USER_ID: u64 = 19595547;
const MAIN_JWT: &str = "eyJ0eXAiOiJKV1QiLCJhbGciOiJTSEEyNTYifQ";

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

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("🕵️ SPYGLASS DEBUGGER STARTED...");
    
    let client = reqwest::Client::new();
    let url = format!("{}/home/hot_anchor", DAZZ_BASE);
    
    // Build Payload
    let mut payload = serde_json::Map::new();
    payload.insert("page".to_string(), json!(1)); // Try page 1
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

    // Sign
    let sign = generate_sign(&payload);
    payload.insert("sign".to_string(), json!(sign));

    // Headers
    let mut headers = HeaderMap::new();
    headers.insert(USER_AGENT, HeaderValue::from_str(APP_VERSION)?);
    headers.insert("Authorization-token", HeaderValue::from_str(MAIN_JWT)?);
    headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json; charset=UTF-8"));

    println!("🚀 Sending Request to {}...", url);

    let resp = client.post(&url).headers(headers).json(&payload).send().await?;

    println!("📡 Status Code: {}", resp.status());

    let body_text = resp.text().await?;
    
    // 1. PRINT RAW JSON (Truncated to first 500 chars so it doesn't flood screen)
    println!("\n📦 RAW RESPONSE (Snippet):");
    println!("{:.500}...", body_text);

    let body: Value = serde_json::from_str(&body_text)?;

    // 2. CHECK API MESSAGE
    if let Some(msg) = body.get("msg") {
        println!("\n💬 Server Message: {}", msg);
    }

    // 3. COUNT ROOMS (IGNORING FILTER)
    if let Some(data_list) = body["data"]["data"].as_array() {
        println!("\n✅ Connection Successful! Found {} total rooms on Page 1.", data_list.len());
        
        println!("\n📝 First 5 Rooms found:");
        for (i, item) in data_list.iter().take(5).enumerate() {
            let rid = item["room_id"].as_u64().unwrap_or(0);
            let nick = item["nickname"].as_str().unwrap_or("Unknown");
            let has_red = item["red_packet_logo"].as_i64().unwrap_or(0); // Might be string or int
            
            let red_status = if has_red == 1 { "💰 YES" } else { "❌ NO" };
            
            println!("   [{}] Room: {} | Nick: {} | RedPacket: {}", i+1, rid, nick, red_status);
        }
    } else {
        println!("\n⚠️ No 'data' array found. The list is empty or structure changed.");
    }

    Ok(())
}