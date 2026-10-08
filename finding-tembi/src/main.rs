use check_if_email_exists::{check_email, CheckEmailInput};
use serde_json::Value;
use std::sync::Arc;
use tokio::fs;
use tokio::io::AsyncWriteExt;

const DOMAINS: &[&str] = &[
    "gosmail.xyz"
];

#[tokio::main]
async fn main() {
    // CLI args: optional `max_workers` (default 10)
    let mut args = std::env::args().skip(1);
    let max_workers: usize = args.next().and_then(|s| s.parse().ok()).unwrap_or(10);

    

    let sem = Arc::new(tokio::sync::Semaphore::new(max_workers));
    // mutex to serialize appends to found.txt
    let out_lock = Arc::new(tokio::sync::Mutex::new(()));
    let mut handles = Vec::new();

    for &domain in DOMAINS.iter() {
        println!("Bruteforce pattern: <aaa..zzz>1@<{}>  workers={}", domain, max_workers);
        for c1 in b'a'..=b'z' {
            for c2 in b'a'..=b'z' {
                for c3 in b'a'..=b'z' {
                    let prefix = format!("{}{}{}1", c1 as char, c2 as char, c3 as char);
                    let email = format!("{}@{}", prefix, domain);

                    // println!("checking email: {}", email);
            let sem = sem.clone();
            let out_lock = out_lock.clone();

            let handle = tokio::spawn(async move {
                // limit concurrency
                let _permit = sem.acquire_owned().await.expect("semaphore closed");

                let input = CheckEmailInput::new(email.clone());
                let result = check_email(&input).await;

                // inspect smtp.is_deliverable
                if let Ok(val) = serde_json::to_value(&result) {
                    let is_deliverable = val
                        .get("smtp")
                        .and_then(Value::as_object)
                        .and_then(|m| m.get("is_deliverable"))
                        .and_then(Value::as_bool)
                        .unwrap_or(false);

                        if is_deliverable {
                            println!("FOUND ON: {}", email);
                            // append prefix to single found.txt, one per line
                            let guard = out_lock.lock().await;
                            let mut f = match fs::OpenOptions::new().create(true).append(true).open("found.txt").await {
                                Ok(f) => f,
                                Err(e) => {
                                    eprintln!("Failed to open found.txt: {}", e);
                                    return;
                                }
                            };
                            if let Err(e) = f.write_all(format!("{}\n", email).as_bytes()).await {
                                eprintln!("Failed to write to found.txt: {}", e);
                            }
                            // drop guard to release mutex
                            drop(guard);
                        } else {
                            // skipped
                        }
                } else {
                    eprintln!("Failed to serialize result for {}", email);
                }
            });

                    handles.push(handle);
                }
            }
        }
    }

    // await all tasks
    for h in handles {
        let _ = h.await;
    }

    println!("Done.");
}

