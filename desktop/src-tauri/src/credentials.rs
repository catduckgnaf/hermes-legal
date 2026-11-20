//! Token storage for the thin client.
//!
//! The frontend never keeps the API token in `localStorage` once these
//! commands exist. `token_get` and `token_set` are the only two shell
//! commands. On Windows they use Credential Manager (generic credential,
//! current user). On Linux they use a mode-0600 file under the user
//! config directory: Secret Service needs a session bus that CI and
//! some desktops do not have, and a 0600 file is the same user-account
//! trust boundary Credential Manager uses.

use std::fs;
use std::path::PathBuf;

pub trait TokenStore {
    fn get_token(&self) -> Result<Option<String>, String>;
    fn set_token(&self, token: &str) -> Result<(), String>;
}

pub struct MemoryTokenStore {
    inner: std::sync::Mutex<Option<String>>,
}

impl MemoryTokenStore {
    pub fn new() -> Self {
        Self {
            inner: std::sync::Mutex::new(None),
        }
    }
}

impl TokenStore for MemoryTokenStore {
    fn get_token(&self) -> Result<Option<String>, String> {
        Ok(self.inner.lock().map_err(|err| err.to_string())?.clone())
    }

    fn set_token(&self, token: &str) -> Result<(), String> {
        let mut guard = self.inner.lock().map_err(|err| err.to_string())?;
        if token.is_empty() {
            *guard = None;
        } else {
            *guard = Some(token.to_string());
        }
        Ok(())
    }
}

/// The two commands, against any store, so unit tests do not touch the OS.
pub fn token_get_from(store: &impl TokenStore) -> Result<String, String> {
    Ok(store.get_token()?.unwrap_or_default())
}

pub fn token_set_on(store: &impl TokenStore, token: &str) -> Result<(), String> {
    store.set_token(token)
}

pub struct FileTokenStore {
    path: PathBuf,
}

impl FileTokenStore {
    pub fn new(path: PathBuf) -> Self {
        Self { path }
    }

    pub fn default_path() -> PathBuf {
        let base = std::env::var_os("XDG_CONFIG_HOME")
            .map(PathBuf::from)
            .or_else(|| {
                std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".config"))
            })
            .unwrap_or_else(|| PathBuf::from("."));
        base.join("hermes-legal").join("api-server-token")
    }
}

impl TokenStore for FileTokenStore {
    fn get_token(&self) -> Result<Option<String>, String> {
        match fs::read_to_string(&self.path) {
            Ok(text) => {
                let trimmed = text.trim().to_string();
                if trimmed.is_empty() {
                    Ok(None)
                } else {
                    Ok(Some(trimmed))
                }
            }
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(None),
            Err(err) => Err(err.to_string()),
        }
    }

    fn set_token(&self, token: &str) -> Result<(), String> {
        if token.is_empty() {
            return match fs::remove_file(&self.path) {
                Ok(()) => Ok(()),
                Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(()),
                Err(err) => Err(err.to_string()),
            };
        }
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent).map_err(|err| err.to_string())?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let _ = fs::set_permissions(parent, fs::Permissions::from_mode(0o700));
            }
        }
        fs::write(&self.path, token.as_bytes()).map_err(|err| err.to_string())?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&self.path, fs::Permissions::from_mode(0o600))
                .map_err(|err| err.to_string())?;
        }
        Ok(())
    }
}

#[cfg(windows)]
mod windows_store {
    use super::TokenStore;
    use std::ffi::c_void;
    use windows_sys::Win32::Foundation::{GetLastError, ERROR_NOT_FOUND};
    use windows_sys::Win32::Security::Credentials::{
        CredDeleteW, CredFree, CredReadW, CredWriteW, CREDENTIALW, CRED_PERSIST_LOCAL_MACHINE,
        CRED_TYPE_GENERIC,
    };

    const TARGET: &str = "com.catduckgnaf.hermes-legal/api-server-token";

    fn wide(value: &str) -> Vec<u16> {
        value.encode_utf16().chain(std::iter::once(0)).collect()
    }

    pub struct WindowsCredentialStore;

    impl TokenStore for WindowsCredentialStore {
        fn get_token(&self) -> Result<Option<String>, String> {
            let target = wide(TARGET);
            let mut cred = std::ptr::null_mut();
            let ok = unsafe { CredReadW(target.as_ptr(), CRED_TYPE_GENERIC, 0, &mut cred) };
            if ok == 0 {
                let err = unsafe { GetLastError() };
                if err == ERROR_NOT_FOUND {
                    return Ok(None);
                }
                return Err(format!("CredReadW failed: {err}"));
            }
            let text = unsafe {
                let blob = std::slice::from_raw_parts(
                    (*cred).CredentialBlob,
                    (*cred).CredentialBlobSize as usize,
                );
                let owned = String::from_utf8(blob.to_vec());
                CredFree(cred as *const c_void);
                owned
            };
            text.map(|value| if value.is_empty() { None } else { Some(value) })
                .map_err(|err| err.to_string())
        }

        fn set_token(&self, token: &str) -> Result<(), String> {
            let target = wide(TARGET);
            if token.is_empty() {
                let ok = unsafe { CredDeleteW(target.as_ptr(), CRED_TYPE_GENERIC, 0) };
                if ok == 0 {
                    let err = unsafe { GetLastError() };
                    if err != ERROR_NOT_FOUND {
                        return Err(format!("CredDeleteW failed: {err}"));
                    }
                }
                return Ok(());
            }
            let mut blob = token.as_bytes().to_vec();
            let user = wide("hermes-legal");
            let cred = CREDENTIALW {
                Flags: 0,
                Type: CRED_TYPE_GENERIC,
                TargetName: target.as_ptr() as *mut _,
                Comment: std::ptr::null_mut(),
                LastWritten: unsafe { std::mem::zeroed() },
                CredentialBlobSize: blob.len() as u32,
                CredentialBlob: blob.as_mut_ptr(),
                Persist: CRED_PERSIST_LOCAL_MACHINE,
                AttributeCount: 0,
                Attributes: std::ptr::null_mut(),
                TargetAlias: std::ptr::null_mut(),
                UserName: user.as_ptr() as *mut _,
            };
            let ok = unsafe { CredWriteW(&cred, 0) };
            if ok == 0 {
                let err = unsafe { GetLastError() };
                return Err(format!("CredWriteW failed: {err}"));
            }
            Ok(())
        }
    }
}

pub fn platform_store() -> Box<dyn TokenStore> {
    #[cfg(windows)]
    {
        Box::new(windows_store::WindowsCredentialStore)
    }
    #[cfg(not(windows))]
    {
        Box::new(FileTokenStore::new(FileTokenStore::default_path()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn memory_round_trip_and_clear() {
        let store = MemoryTokenStore::new();
        assert_eq!(token_get_from(&store).unwrap(), "");
        token_set_on(&store, "secret").unwrap();
        assert_eq!(token_get_from(&store).unwrap(), "secret");
        token_set_on(&store, "").unwrap();
        assert_eq!(token_get_from(&store).unwrap(), "");
    }

    #[test]
    fn file_store_is_owner_readable_only() {
        let dir = std::env::temp_dir().join(format!(
            "hermes-legal-token-test-{}",
            std::process::id()
        ));
        let path = dir.join("api-server-token");
        let store = FileTokenStore::new(path.clone());
        token_set_on(&store, "local-secret").unwrap();
        assert_eq!(token_get_from(&store).unwrap(), "local-secret");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = fs::metadata(&path).unwrap().permissions().mode();
            assert_eq!(mode & 0o777, 0o600);
        }
        token_set_on(&store, "").unwrap();
        assert!(!path.exists());
        let _ = fs::remove_dir_all(dir);
    }
}
