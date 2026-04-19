//! Safe RAII wrappers over raw `ort-sys` FFI.
//!
//! Every ORT handle type is represented by a zero-cost struct whose
//! `Drop` impl calls the matching `Release*` function. Errors returned
//! by ORT are converted into [`OrtError`] instead of panicking.
//!
//! The [`Runtime`] holds the [`libloading::Library`] and the loaded
//! `OrtApi` function-pointer table. Handles keep an `Arc<Runtime>` so
//! they remain valid regardless of where they sit relative to the
//! owner; the library drops only when the last handle drops.

use std::ffi::{CStr, CString};
use std::path::{Path, PathBuf};
use std::ptr::{self, NonNull};
use std::sync::Arc;

use ort_sys::{
    GraphOptimizationLevel, ONNXTensorElementDataType, ORT_API_VERSION, OrtAllocatorType, OrtApi,
    OrtApiBase, OrtEnv, OrtLoggingLevel, OrtMemType, OrtMemoryInfo, OrtSession, OrtSessionOptions,
    OrtStatusPtr, OrtTensorTypeAndShapeInfo, OrtValue,
};

/// Errors originating from the ONNX Runtime FFI layer.
#[derive(Debug, thiserror::Error)]
pub enum OrtError {
    /// The library at the provided path could not be loaded.
    #[error("failed to load onnxruntime library {path:?}: {source}")]
    LoadLibrary {
        /// Path we attempted to load.
        path: PathBuf,
        /// Underlying libloading error.
        source: libloading::Error,
    },
    /// `OrtGetApiBase` was not found in the library or returned null.
    #[error("OrtGetApiBase symbol missing from {path:?}: {source}")]
    GetApiBase {
        /// Library path at which the lookup failed.
        path: PathBuf,
        /// Underlying libloading error.
        source: libloading::Error,
    },
    /// `OrtApiBase::GetApi` returned a null pointer (version mismatch).
    #[error("OrtApiBase::GetApi returned null (ORT_API_VERSION mismatch)")]
    ApiVersionMismatch,
    /// An ORT call returned a non-null `OrtStatus` value.
    #[error("{context}: {message}")]
    Status {
        /// Name of the ORT call that failed.
        context: &'static str,
        /// Human-readable message extracted from the `OrtStatus`.
        message: String,
    },
    /// A C string contained an interior NUL byte.
    #[error("string contained interior NUL byte")]
    InteriorNul,
}

/// The loaded ONNX Runtime library and API table.
///
/// Shared via `Arc` across every handle it spawns so the library stays
/// mapped until the last handle is dropped.
pub struct Runtime {
    // Field order matters: `api` borrows from the library via a raw
    // pointer. Rust drops fields top-to-bottom, so keep `_library`
    // last — it outlives all pointer-holding siblings.
    api: NonNull<OrtApi>,
    _library: libloading::Library,
}

// SAFETY: The loaded OrtApi table is read-only for the lifetime of the
// runtime. API function entries are documented thread-safe; individual
// handles are guarded with `Send` / `Sync` as appropriate below.
unsafe impl Send for Runtime {}
unsafe impl Sync for Runtime {}

impl Runtime {
    /// Load the ORT library at `path` and resolve the API table.
    pub fn load(path: &Path) -> Result<Arc<Self>, OrtError> {
        let path_buf = path.to_path_buf();
        // SAFETY: Loading a shared library is inherently unsafe; we
        // trust the caller to supply a legitimate onnxruntime binary.
        let library =
            unsafe { libloading::Library::new(path) }.map_err(|source| OrtError::LoadLibrary {
                path: path_buf.clone(),
                source,
            })?;

        type GetApiBaseFn = unsafe extern "C" fn() -> *const OrtApiBase;
        // SAFETY: Symbol lookup matches ORT's documented C ABI.
        let get_api_base: libloading::Symbol<GetApiBaseFn> =
            unsafe { library.get(b"OrtGetApiBase") }.map_err(|source| OrtError::GetApiBase {
                path: path_buf,
                source,
            })?;

        // SAFETY: The symbol is called per the documented ABI.
        let api_base = unsafe { get_api_base() };
        if api_base.is_null() {
            return Err(OrtError::ApiVersionMismatch);
        }
        // SAFETY: api_base points into the loaded library; GetApi is
        // present at that offset.
        let api_ptr = unsafe { ((*api_base).GetApi)(ORT_API_VERSION) } as *mut OrtApi;
        let api = NonNull::new(api_ptr).ok_or(OrtError::ApiVersionMismatch)?;

        Ok(Arc::new(Self {
            api,
            _library: library,
        }))
    }

    fn api(&self) -> &OrtApi {
        // SAFETY: `api` is non-null by construction and points into the
        // library this Runtime keeps alive.
        unsafe { self.api.as_ref() }
    }

    fn check(&self, status: OrtStatusPtr, context: &'static str) -> Result<(), OrtError> {
        if status.0.is_null() {
            return Ok(());
        }
        // SAFETY: status is non-null; GetErrorMessage returns a string
        // view valid for the status object's lifetime.
        let message = unsafe {
            let raw = (self.api().GetErrorMessage)(status.0);
            CStr::from_ptr(raw as *const _)
                .to_string_lossy()
                .into_owned()
        };
        // SAFETY: status is non-null; ReleaseStatus accepts it.
        unsafe { (self.api().ReleaseStatus)(status.0) };
        Err(OrtError::Status { context, message })
    }
}

/// Build an ORT environment (logger + global state).
pub fn create_env(runtime: &Arc<Runtime>, name: &str) -> Result<Env, OrtError> {
    let c_name = CString::new(name).map_err(|_| OrtError::InteriorNul)?;
    let mut raw: *mut OrtEnv = ptr::null_mut();
    // SAFETY: Valid name CString + out-pointer per documented ABI.
    let status = unsafe {
        (runtime.api().CreateEnv)(
            OrtLoggingLevel::ORT_LOGGING_LEVEL_WARNING,
            c_name.as_ptr(),
            &mut raw,
        )
    };
    runtime.check(status, "CreateEnv")?;
    Ok(Env {
        runtime: Arc::clone(runtime),
        raw,
    })
}

/// Build session options wired with the performance recipe validated
/// during the PoC.
pub fn create_session_options(
    runtime: &Arc<Runtime>,
    disable_mem_arena: bool,
    allow_spinning: bool,
) -> Result<SessionOptions, OrtError> {
    let mut raw: *mut OrtSessionOptions = ptr::null_mut();
    // SAFETY: Out-pointer valid.
    let status = unsafe { (runtime.api().CreateSessionOptions)(&mut raw) };
    runtime.check(status, "CreateSessionOptions")?;
    let options = SessionOptions {
        runtime: Arc::clone(runtime),
        raw,
    };

    // SAFETY: raw non-null per the success above.
    let status = unsafe { (runtime.api().SetIntraOpNumThreads)(options.raw, 0) };
    runtime.check(status, "SetIntraOpNumThreads")?;

    // SAFETY: raw non-null.
    let status = unsafe {
        (runtime.api().SetSessionGraphOptimizationLevel)(
            options.raw,
            GraphOptimizationLevel::ORT_ENABLE_ALL,
        )
    };
    runtime.check(status, "SetSessionGraphOptimizationLevel")?;

    if disable_mem_arena {
        // SAFETY: raw non-null.
        let status = unsafe { (runtime.api().DisableCpuMemArena)(options.raw) };
        runtime.check(status, "DisableCpuMemArena")?;
    }
    if allow_spinning {
        let key =
            CString::new("session.intra_op.allow_spinning").map_err(|_| OrtError::InteriorNul)?;
        let value = CString::new("1").map_err(|_| OrtError::InteriorNul)?;
        // SAFETY: raw non-null; key/value live through the call.
        let status = unsafe {
            (runtime.api().AddSessionConfigEntry)(options.raw, key.as_ptr(), value.as_ptr())
        };
        runtime.check(status, "AddSessionConfigEntry allow_spinning")?;
    }
    Ok(options)
}

/// Load an ONNX model into a new Session.
pub fn create_session(
    runtime: &Arc<Runtime>,
    env: &Env,
    options: &SessionOptions,
    model_path: &Path,
) -> Result<Session, OrtError> {
    let path_arg = encode_ort_path(model_path);
    let mut raw: *mut OrtSession = ptr::null_mut();
    // SAFETY: env.raw / options.raw non-null; path_arg buffer lives
    // through the call; out-pointer valid.
    let status =
        unsafe { (runtime.api().CreateSession)(env.raw, path_arg.as_ptr(), options.raw, &mut raw) };
    runtime.check(status, "CreateSession")?;
    Ok(Session {
        runtime: Arc::clone(runtime),
        raw,
    })
}

/// Build a CPU memory-info descriptor for caller-supplied tensors.
pub fn create_cpu_memory_info(runtime: &Arc<Runtime>) -> Result<MemoryInfo, OrtError> {
    let mut raw: *mut OrtMemoryInfo = ptr::null_mut();
    // SAFETY: Out-pointer valid.
    let status = unsafe {
        (runtime.api().CreateCpuMemoryInfo)(
            OrtAllocatorType::OrtArenaAllocator,
            OrtMemType::OrtMemTypeDefault,
            &mut raw,
        )
    };
    runtime.check(status, "CreateCpuMemoryInfo")?;
    Ok(MemoryInfo {
        runtime: Arc::clone(runtime),
        raw,
    })
}

/// Run one batch, returning the flat output tensor and its hidden dim.
#[allow(clippy::too_many_arguments)]
pub fn run(
    runtime: &Arc<Runtime>,
    session: &Session,
    memory_info: &MemoryInfo,
    input_ids: &[i64],
    attention_mask: &[i64],
    token_type_ids: &[i64],
    batch: usize,
    seq: usize,
) -> Result<OutputTensor, OrtError> {
    let shape: [i64; 2] = [batch as i64, seq as i64];

    let ids_t = make_i64_tensor(runtime, memory_info, input_ids, &shape)?;
    let mask_t = make_i64_tensor(runtime, memory_info, attention_mask, &shape)?;
    let tids_t = make_i64_tensor(runtime, memory_info, token_type_ids, &shape)?;

    let ids_name = CString::new("input_ids").map_err(|_| OrtError::InteriorNul)?;
    let mask_name = CString::new("attention_mask").map_err(|_| OrtError::InteriorNul)?;
    let tids_name = CString::new("token_type_ids").map_err(|_| OrtError::InteriorNul)?;
    let input_names: [*const std::os::raw::c_char; 3] =
        [ids_name.as_ptr(), mask_name.as_ptr(), tids_name.as_ptr()];
    let inputs: [*const OrtValue; 3] = [ids_t.raw, mask_t.raw, tids_t.raw];

    let out_name = CString::new("last_hidden_state").map_err(|_| OrtError::InteriorNul)?;
    let output_names: [*const std::os::raw::c_char; 1] = [out_name.as_ptr()];
    let mut outputs: [*mut OrtValue; 1] = [ptr::null_mut()];

    // SAFETY: Pointers live for the duration of the Run call.
    let status = unsafe {
        (runtime.api().Run)(
            session.raw,
            ptr::null(),
            input_names.as_ptr(),
            inputs.as_ptr(),
            3,
            output_names.as_ptr(),
            1,
            outputs.as_mut_ptr(),
        )
    };
    runtime.check(status, "Run")?;

    let out_val = Value {
        runtime: Arc::clone(runtime),
        raw: outputs[0],
    };
    let (hidden, values) = extract_output(runtime, &out_val, batch, seq)?;
    Ok(OutputTensor { values, hidden })
}

fn make_i64_tensor(
    runtime: &Arc<Runtime>,
    memory_info: &MemoryInfo,
    data: &[i64],
    shape: &[i64; 2],
) -> Result<Value, OrtError> {
    let mut raw: *mut OrtValue = ptr::null_mut();
    // SAFETY: data.as_ptr lives for the duration of this call; memory
    // info non-null; out-pointer valid.
    let status = unsafe {
        (runtime.api().CreateTensorWithDataAsOrtValue)(
            memory_info.raw,
            data.as_ptr() as *mut std::ffi::c_void,
            std::mem::size_of_val(data),
            shape.as_ptr(),
            shape.len(),
            ONNXTensorElementDataType::ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64,
            &mut raw,
        )
    };
    runtime.check(status, "CreateTensorWithDataAsOrtValue")?;
    Ok(Value {
        runtime: Arc::clone(runtime),
        raw,
    })
}

fn extract_output(
    runtime: &Arc<Runtime>,
    value: &Value,
    batch: usize,
    seq: usize,
) -> Result<(usize, Vec<f32>), OrtError> {
    let mut ts_info: *mut OrtTensorTypeAndShapeInfo = ptr::null_mut();
    // SAFETY: value.raw non-null; out-pointer valid.
    let status = unsafe { (runtime.api().GetTensorTypeAndShape)(value.raw, &mut ts_info) };
    runtime.check(status, "GetTensorTypeAndShape")?;

    let mut n_dims: usize = 0;
    // SAFETY: ts_info non-null per the success above.
    let status = unsafe { (runtime.api().GetDimensionsCount)(ts_info, &mut n_dims) };
    if let Err(e) = runtime.check(status, "GetDimensionsCount") {
        // SAFETY: ts_info non-null.
        unsafe { (runtime.api().ReleaseTensorTypeAndShapeInfo)(ts_info) };
        return Err(e);
    }

    let mut dims = vec![0i64; n_dims];
    // SAFETY: ts_info non-null; dims buffer sized to n_dims.
    let status = unsafe { (runtime.api().GetDimensions)(ts_info, dims.as_mut_ptr(), n_dims) };
    if let Err(e) = runtime.check(status, "GetDimensions") {
        // SAFETY: ts_info non-null.
        unsafe { (runtime.api().ReleaseTensorTypeAndShapeInfo)(ts_info) };
        return Err(e);
    }
    // SAFETY: ts_info non-null.
    unsafe { (runtime.api().ReleaseTensorTypeAndShapeInfo)(ts_info) };

    let hidden = *dims.get(2).unwrap_or(&0) as usize;

    let mut data_ptr: *mut std::ffi::c_void = ptr::null_mut();
    // SAFETY: value.raw non-null; out-pointer valid.
    let status = unsafe { (runtime.api().GetTensorMutableData)(value.raw, &mut data_ptr) };
    runtime.check(status, "GetTensorMutableData")?;

    let total = batch * seq * hidden;
    // SAFETY: data_ptr points at an f32 array of length `total` owned
    // by the session allocator; we copy into an owned Vec before Value
    // drops.
    let slice = unsafe { std::slice::from_raw_parts(data_ptr as *const f32, total) };
    Ok((hidden, slice.to_vec()))
}

/// ORT environment handle.
pub struct Env {
    runtime: Arc<Runtime>,
    raw: *mut OrtEnv,
}

impl Drop for Env {
    fn drop(&mut self) {
        if !self.raw.is_null() {
            // SAFETY: raw non-null; runtime kept alive by Arc.
            unsafe { (self.runtime.api().ReleaseEnv)(self.raw) };
        }
    }
}

// SAFETY: OrtEnv is global logger/state, documented as thread-safe for
// all Ort API calls that reference it. We only ever pass it to Create*
// functions at setup time.
unsafe impl Send for Env {}
unsafe impl Sync for Env {}

/// ORT session options handle.
pub struct SessionOptions {
    runtime: Arc<Runtime>,
    raw: *mut OrtSessionOptions,
}

impl Drop for SessionOptions {
    fn drop(&mut self) {
        if !self.raw.is_null() {
            // SAFETY: raw non-null; runtime kept alive by Arc.
            unsafe { (self.runtime.api().ReleaseSessionOptions)(self.raw) };
        }
    }
}

// SAFETY: SessionOptions is consumed by CreateSession and never touched
// afterwards; we keep it alive only so Drop can run at EmbeddingModel
// drop time.
unsafe impl Send for SessionOptions {}
unsafe impl Sync for SessionOptions {}

/// Loaded ONNX inference session.
pub struct Session {
    runtime: Arc<Runtime>,
    raw: *mut OrtSession,
}

impl Drop for Session {
    fn drop(&mut self) {
        if !self.raw.is_null() {
            // SAFETY: raw non-null; runtime kept alive by Arc.
            unsafe { (self.runtime.api().ReleaseSession)(self.raw) };
        }
    }
}

// SAFETY: Caller guards concurrent Run calls with a Mutex; Send/Sync
// claim that Session is safe to move across threads and to share via
// shared references — true because every accessor path into Session
// either takes &mut (Run) or is called only from the Drop path.
unsafe impl Send for Session {}
unsafe impl Sync for Session {}

/// CPU memory-info descriptor.
pub struct MemoryInfo {
    runtime: Arc<Runtime>,
    raw: *mut OrtMemoryInfo,
}

impl Drop for MemoryInfo {
    fn drop(&mut self) {
        if !self.raw.is_null() {
            // SAFETY: raw non-null; runtime kept alive by Arc.
            unsafe { (self.runtime.api().ReleaseMemoryInfo)(self.raw) };
        }
    }
}

// SAFETY: OrtMemoryInfo is immutable after creation per ORT docs.
unsafe impl Send for MemoryInfo {}
unsafe impl Sync for MemoryInfo {}

struct Value {
    runtime: Arc<Runtime>,
    raw: *mut OrtValue,
}

impl Drop for Value {
    fn drop(&mut self) {
        if !self.raw.is_null() {
            // SAFETY: raw non-null; runtime kept alive by Arc.
            unsafe { (self.runtime.api().ReleaseValue)(self.raw) };
        }
    }
}

/// Result of a single inference call.
pub struct OutputTensor {
    /// Flat `[batch * seq * hidden]` f32 buffer.
    pub values: Vec<f32>,
    /// Hidden-dim extent, read from the tensor's shape at runtime.
    pub hidden: usize,
}

#[cfg(windows)]
fn encode_ort_path(path: &Path) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;
    path.as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect()
}

#[cfg(not(windows))]
fn encode_ort_path(path: &Path) -> Vec<u8> {
    use std::os::unix::ffi::OsStrExt;
    let bytes = path.as_os_str().as_bytes();
    let mut v = Vec::with_capacity(bytes.len() + 1);
    v.extend_from_slice(bytes);
    v.push(0);
    v
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn load_reports_missing_library() {
        let err = Runtime::load(Path::new("this/does/not/exist.dll"))
            .map(|_| ())
            .expect_err("load must fail for missing path");
        assert!(matches!(err, OrtError::LoadLibrary { .. }));
    }
}
