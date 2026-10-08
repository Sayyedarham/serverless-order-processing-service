use keyring::Entry;
use serde::Serialize;

const SERVICE: &str = "order-reliability-desktop";
const ACCOUNT: &str = "connection-token";

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Connection {
    api_url: String,
    token: String,
}

fn token_entry() -> Result<Entry, String> {
    Entry::new(SERVICE, ACCOUNT).map_err(|error| error.to_string())
}

#[tauri::command]
fn save_connection(api_url: String, token: String) -> Result<(), String> {
    let payload = serde_json::to_string(&Connection { api_url, token }).map_err(|error| error.to_string())?;
    token_entry()?.set_password(&payload).map_err(|error| error.to_string())
}

#[tauri::command]
fn load_connection() -> Result<Option<Connection>, String> {
    match token_entry()?.get_password() {
        Ok(payload) => serde_json::from_str(&payload).map(Some).map_err(|error| error.to_string()),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(error) => Err(error.to_string()),
    }
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![save_connection, load_connection])
        .run(tauri::generate_context!())
        .expect("error while running Order Reliability");
}
