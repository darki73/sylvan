//! ONNX Runtime native-library download + cache.
//!
//! sylvan ships a platform-agnostic Python wheel, but the ORT native
//! library is inherently OS+arch specific. Rather than bundle a
//! ~90 MB binary into every wheel (5 platforms × ~90 MB = ~450 MB on
//! PyPI), we download the right archive from Microsoft's GitHub
//! releases on first use and cache it under `~/.sylvan/runtime/`.
//!
//! Honours `ORT_DLL_PATH` when set — callers with a local ORT install
//! or custom build bypass the download entirely.

use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use super::ProviderError;

const ORT_VERSION: &str = "1.24.4";

fn sylvan_runtime_dir() -> Result<PathBuf, ProviderError> {
    let home = if let Ok(h) = std::env::var("SYLVAN_HOME") {
        PathBuf::from(h)
    } else {
        home_dir()
            .ok_or_else(|| {
                ProviderError::Tokenizer("could not resolve user home directory".into())
            })?
            .join(".sylvan")
    };
    Ok(home.join("runtime"))
}

fn home_dir() -> Option<PathBuf> {
    #[cfg(windows)]
    {
        std::env::var_os("USERPROFILE").map(PathBuf::from)
    }
    #[cfg(not(windows))]
    {
        std::env::var_os("HOME").map(PathBuf::from)
    }
}

/// Platform identifier used for archive selection.
///
/// Variants are `#[allow(dead_code)]` because only the current-host
/// variant is ever constructed (the others live behind `#[cfg]` in
/// [`Platform::current`]); every variant is still reachable at
/// compile time on *some* platform the workspace targets.
#[allow(dead_code)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Platform {
    /// Windows x86_64 (zip archive).
    WinX64,
    /// Linux x86_64 (tar.gz archive).
    LinuxX64,
    /// Linux aarch64 (tar.gz archive).
    LinuxAarch64,
    /// macOS x86_64 (tar.gz archive).
    MacX64,
    /// macOS arm64 / Apple Silicon (tar.gz archive).
    MacArm64,
}

impl Platform {
    /// Detect the current host platform.
    pub fn current() -> Result<Self, ProviderError> {
        #[cfg(all(target_os = "windows", target_arch = "x86_64"))]
        {
            Ok(Platform::WinX64)
        }
        #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
        {
            Ok(Platform::LinuxX64)
        }
        #[cfg(all(target_os = "linux", target_arch = "aarch64"))]
        {
            Ok(Platform::LinuxAarch64)
        }
        #[cfg(all(target_os = "macos", target_arch = "x86_64"))]
        {
            Ok(Platform::MacX64)
        }
        #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
        {
            Ok(Platform::MacArm64)
        }
        #[cfg(not(any(
            all(target_os = "windows", target_arch = "x86_64"),
            all(target_os = "linux", target_arch = "x86_64"),
            all(target_os = "linux", target_arch = "aarch64"),
            all(target_os = "macos", target_arch = "x86_64"),
            all(target_os = "macos", target_arch = "aarch64"),
        )))]
        {
            Err(ProviderError::Tokenizer(
                "unsupported platform for automatic ORT download; set ORT_DLL_PATH to an existing library".into(),
            ))
        }
    }

    fn archive_slug(self) -> &'static str {
        match self {
            Platform::WinX64 => "win-x64",
            Platform::LinuxX64 => "linux-x64",
            Platform::LinuxAarch64 => "linux-aarch64",
            Platform::MacX64 => "osx-x86_64",
            Platform::MacArm64 => "osx-arm64",
        }
    }

    fn archive_extension(self) -> &'static str {
        match self {
            Platform::WinX64 => "zip",
            Platform::LinuxX64 | Platform::LinuxAarch64 | Platform::MacX64 | Platform::MacArm64 => {
                "tgz"
            }
        }
    }

    fn library_filename(self) -> &'static str {
        match self {
            Platform::WinX64 => "onnxruntime.dll",
            Platform::LinuxX64 | Platform::LinuxAarch64 => "libonnxruntime.so",
            Platform::MacX64 | Platform::MacArm64 => "libonnxruntime.dylib",
        }
    }
}

fn archive_url(platform: Platform) -> String {
    format!(
        "https://github.com/microsoft/onnxruntime/releases/download/v{version}/onnxruntime-{slug}-{version}.{ext}",
        version = ORT_VERSION,
        slug = platform.archive_slug(),
        ext = platform.archive_extension(),
    )
}

fn cache_root() -> Result<PathBuf, ProviderError> {
    Ok(sylvan_runtime_dir()?.join(format!("onnxruntime-{ORT_VERSION}")))
}

fn extracted_root(platform: Platform) -> Result<PathBuf, ProviderError> {
    Ok(cache_root()?.join(format!(
        "onnxruntime-{slug}-{version}",
        slug = platform.archive_slug(),
        version = ORT_VERSION,
    )))
}

/// Return the filesystem path to an ONNX Runtime shared library for the
/// current platform, downloading and extracting into the sylvan cache
/// if not already present. Honours `ORT_DLL_PATH` to bypass the cache
/// entirely.
pub fn ensure_runtime() -> Result<PathBuf, ProviderError> {
    if let Ok(p) = std::env::var("ORT_DLL_PATH") {
        return Ok(PathBuf::from(p));
    }
    let platform = Platform::current()?;
    let expected = extracted_root(platform)?
        .join("lib")
        .join(platform.library_filename());
    if expected.exists() {
        return Ok(expected);
    }
    download_and_extract(platform)?;
    if expected.exists() {
        return Ok(expected);
    }
    // Fallback: probe for the versioned Linux name (libonnxruntime.so.1.20.0).
    let lib_dir = extracted_root(platform)?.join("lib");
    if let Some(found) = first_library_match(&lib_dir, platform.library_filename()) {
        return Ok(found);
    }
    Err(ProviderError::Tokenizer(format!(
        "ORT library not found after extraction at {expected:?}"
    )))
}

fn first_library_match(dir: &Path, stem: &str) -> Option<PathBuf> {
    let entries = fs::read_dir(dir).ok()?;
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name_str = name.to_string_lossy();
        if name_str.starts_with(stem) || name_str.contains(stem) {
            return Some(entry.path());
        }
    }
    None
}

fn download_and_extract(platform: Platform) -> Result<(), ProviderError> {
    let cache = cache_root()?;
    fs::create_dir_all(&cache).map_err(|source| ProviderError::Io {
        path: cache.clone(),
        source,
    })?;
    let url = archive_url(platform);
    let archive_path = cache.join(format!(
        "onnxruntime-{}.{}",
        platform.archive_slug(),
        platform.archive_extension()
    ));

    download_to_file(&url, &archive_path)?;

    match platform.archive_extension() {
        "zip" => extract_zip(&archive_path, &cache)?,
        "tgz" => extract_tgz(&archive_path, &cache)?,
        other => {
            return Err(ProviderError::Tokenizer(format!(
                "unsupported archive extension: {other}"
            )));
        }
    }
    // Leave the archive in place so a partial extraction can be detected
    // and re-run by wiping the cache directory; remove only on success
    // is a later refinement.
    Ok(())
}

fn download_to_file(url: &str, out: &Path) -> Result<(), ProviderError> {
    let response = ureq::get(url)
        .call()
        .map_err(|err| ProviderError::Tokenizer(format!("GET {url}: {err}")))?;
    let mut body = response.into_body().into_reader();
    let mut file = fs::File::create(out).map_err(|source| ProviderError::Io {
        path: out.to_path_buf(),
        source,
    })?;
    io::copy(&mut body, &mut file).map_err(|source| ProviderError::Io {
        path: out.to_path_buf(),
        source,
    })?;
    Ok(())
}

fn extract_zip(archive: &Path, dest: &Path) -> Result<(), ProviderError> {
    let file = fs::File::open(archive).map_err(|source| ProviderError::Io {
        path: archive.to_path_buf(),
        source,
    })?;
    let mut zip = zip::ZipArchive::new(file)
        .map_err(|err| ProviderError::Tokenizer(format!("open zip {archive:?}: {err}")))?;
    for i in 0..zip.len() {
        let mut entry = zip
            .by_index(i)
            .map_err(|err| ProviderError::Tokenizer(format!("zip entry {i}: {err}")))?;
        let Some(name) = entry.enclosed_name() else {
            continue;
        };
        let out_path = dest.join(&name);
        if entry.is_dir() {
            fs::create_dir_all(&out_path).map_err(|source| ProviderError::Io {
                path: out_path.clone(),
                source,
            })?;
            continue;
        }
        if let Some(parent) = out_path.parent() {
            fs::create_dir_all(parent).map_err(|source| ProviderError::Io {
                path: parent.to_path_buf(),
                source,
            })?;
        }
        let mut out_file = fs::File::create(&out_path).map_err(|source| ProviderError::Io {
            path: out_path.clone(),
            source,
        })?;
        io::copy(&mut entry, &mut out_file).map_err(|source| ProviderError::Io {
            path: out_path,
            source,
        })?;
    }
    Ok(())
}

fn extract_tgz(archive: &Path, dest: &Path) -> Result<(), ProviderError> {
    let file = fs::File::open(archive).map_err(|source| ProviderError::Io {
        path: archive.to_path_buf(),
        source,
    })?;
    let decoder = flate2::read::GzDecoder::new(file);
    let mut tar = tar::Archive::new(decoder);
    tar.unpack(dest).map_err(|source| ProviderError::Io {
        path: dest.to_path_buf(),
        source,
    })?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn archive_url_contains_version_and_platform() {
        let url = archive_url(Platform::WinX64);
        assert!(url.contains(ORT_VERSION));
        assert!(url.contains("win-x64"));
        assert!(url.ends_with(".zip"));
    }

    #[test]
    fn library_filename_matches_platform() {
        assert_eq!(Platform::WinX64.library_filename(), "onnxruntime.dll");
        assert_eq!(Platform::LinuxX64.library_filename(), "libonnxruntime.so");
        assert_eq!(
            Platform::MacArm64.library_filename(),
            "libonnxruntime.dylib"
        );
    }

    #[test]
    fn ort_dll_path_bypasses_cache() {
        // SAFETY: test-local env var manipulation.
        unsafe {
            std::env::set_var("ORT_DLL_PATH", "/tmp/custom-ort.dll");
        }
        let resolved = ensure_runtime().unwrap();
        assert_eq!(resolved, PathBuf::from("/tmp/custom-ort.dll"));
        unsafe {
            std::env::remove_var("ORT_DLL_PATH");
        }
    }
}
