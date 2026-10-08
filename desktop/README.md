# Desktop BYOK client

This Tauri application bundles the shared `docs/index.html` UI. It connects only to a user-owned deployment: enter its API URL and application token. The native app saves that pair in the OS credential vault through the Rust `keyring` crate; the browser version does not persist it.

Prerequisites are Node.js, Rust, platform dependencies required by Tauri, and Python 3 for the local static development server. From this directory, run `npm install`, then `npm run dev`; use `npm run build` to package the application. No AWS credential is requested by, stored in, or sent through the client.
