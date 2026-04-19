//! Embedding model: safe wrapper around ONNX Runtime + HuggingFace tokenizer.
//!
//! The RAII types in [`ort`] ensure every `OrtValue` / `OrtSession` /
//! `OrtEnv` etc. is released even on panic paths. Public surface:
//! build an [`EmbeddingModel`], call [`EmbeddingModel::embed`], get
//! vectors back.

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use tokenizers::{
    PaddingDirection, PaddingParams, PaddingStrategy, Tokenizer, TruncationDirection,
    TruncationParams, TruncationStrategy,
};

mod ort;

pub use ort::OrtError;

/// Maximum tokens per sequence. Fixed shape lets ORT's memory pattern
/// caching kick in; Python fastembed uses the same value.
const MAX_SEQUENCE: usize = 128;

/// Hidden dimension for the default `all-MiniLM-L6-v2` model. Actual
/// dimension is auto-detected at first embed call.
const DEFAULT_HIDDEN_DIM: usize = 384;

/// Errors returned from [`EmbeddingModel`] operations.
#[derive(Debug, thiserror::Error)]
pub enum ProviderError {
    /// Underlying ONNX Runtime error.
    #[error("onnx runtime: {0}")]
    Ort(#[from] OrtError),
    /// Tokenizer loading or encoding failure.
    #[error("tokenizer: {0}")]
    Tokenizer(String),
    /// Input/output failure while reading model files.
    #[error("io on {path:?}: {source}")]
    Io {
        /// Path that triggered the failure.
        path: PathBuf,
        /// Underlying IO error.
        #[source]
        source: std::io::Error,
    },
}

/// What kind of model weights the caller provided.
///
/// Different weight types trade off size, speed, and numerical
/// precision. `Fp32` is the reference; quantized variants are faster
/// on CPUs with AVX2 / AVX-512 / VNNI and smaller on disk.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ModelKind {
    /// Full-precision float32 weights. Reference accuracy.
    Fp32,
    /// Symmetric 8-bit quantized weights; needs AVX-512 or VNNI CPU.
    Qint8,
    /// Unsigned 8-bit AVX2 quantized weights; broadly compatible.
    QuInt8Avx2,
}

/// Configuration for building an [`EmbeddingModel`].
#[derive(Debug, Clone)]
pub struct EmbeddingModelConfig {
    /// Absolute path to the `onnxruntime.dll` / `.so` / `.dylib`.
    pub ort_library_path: PathBuf,
    /// Absolute path to the `.onnx` model file.
    pub model_path: PathBuf,
    /// Absolute path to the `tokenizer.json` file.
    pub tokenizer_path: PathBuf,
    /// Which weight encoding the model file uses. Kept for bookkeeping
    /// and potential future dispatch; does not change tokenization.
    pub model_kind: ModelKind,
    /// Disable the CPU memory arena to keep peak RSS low (~170 MB vs
    /// ~1700 MB). Slight throughput cost on tiny inputs; negligible on
    /// batched workloads.
    pub disable_mem_arena: bool,
    /// Let ORT's intra-op thread pool spin while waiting for work
    /// instead of sleeping. Cuts wakeup latency on tiny batches at the
    /// cost of higher CPU-idle percentage.
    pub allow_spinning: bool,
}

impl EmbeddingModelConfig {
    /// Build a config with memory-efficient defaults (arena OFF, spin ON).
    pub fn new(
        ort_library_path: impl Into<PathBuf>,
        model_path: impl Into<PathBuf>,
        tokenizer_path: impl Into<PathBuf>,
    ) -> Self {
        Self {
            ort_library_path: ort_library_path.into(),
            model_path: model_path.into(),
            tokenizer_path: tokenizer_path.into(),
            model_kind: ModelKind::Fp32,
            disable_mem_arena: true,
            allow_spinning: true,
        }
    }
}

/// A loaded embedding model ready to run batched inference.
///
/// `embed` takes a slice of strings and returns one L2-normalised
/// vector per input. Safe to share across threads: the internal
/// [`ort::Session`] is wrapped in a mutex because ORT does not
/// guarantee concurrent `Run` calls on the same session are safe.
pub struct EmbeddingModel {
    runtime: Arc<ort::Runtime>,
    // Env/Options are dropped with the struct but not used after load.
    _env: ort::Env,
    _options: ort::SessionOptions,
    session: Mutex<ort::Session>,
    memory_info: ort::MemoryInfo,
    tokenizer: Tokenizer,
    hidden_dim: Mutex<Option<usize>>,
}

impl EmbeddingModel {
    /// Load model + tokenizer + ONNX Runtime per `config`.
    pub fn load(config: &EmbeddingModelConfig) -> Result<Self, ProviderError> {
        let runtime = ort::Runtime::load(&config.ort_library_path)?;
        let env = ort::create_env(&runtime, "sylvan-embedding")?;
        let options =
            ort::create_session_options(&runtime, config.disable_mem_arena, config.allow_spinning)?;
        let session = ort::create_session(&runtime, &env, &options, &config.model_path)?;
        let memory_info = ort::create_cpu_memory_info(&runtime)?;
        let tokenizer = load_tokenizer(&config.tokenizer_path)?;
        Ok(Self {
            runtime,
            _env: env,
            _options: options,
            session: Mutex::new(session),
            memory_info,
            tokenizer,
            hidden_dim: Mutex::new(None),
        })
    }

    /// Number of dimensions in each output vector.
    ///
    /// Populated on the first call to [`Self::embed`]; returns
    /// `DEFAULT_HIDDEN_DIM` as a best guess until the model has
    /// actually been asked for an inference.
    pub fn dimensions(&self) -> usize {
        self.hidden_dim
            .lock()
            .ok()
            .and_then(|g| *g)
            .unwrap_or(DEFAULT_HIDDEN_DIM)
    }

    /// Embed `texts` as a single batch, returning one vector per input.
    pub fn embed(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>, ProviderError> {
        if texts.is_empty() {
            return Ok(Vec::new());
        }
        let batch = tokenize_batch(&self.tokenizer, texts)?;
        let session = self
            .session
            .lock()
            .map_err(|_| ProviderError::Tokenizer("session mutex poisoned".into()))?;
        let output = ort::run(
            &self.runtime,
            &session,
            &self.memory_info,
            &batch.input_ids,
            &batch.attention_mask,
            &batch.token_type_ids,
            batch.batch_size,
            batch.seq_len,
        )?;

        let mut dim_slot = self
            .hidden_dim
            .lock()
            .map_err(|_| ProviderError::Tokenizer("dim mutex poisoned".into()))?;
        *dim_slot = Some(output.hidden);
        drop(dim_slot);

        Ok(mean_pool_and_normalise(
            &output.values,
            &batch.attention_mask,
            batch.batch_size,
            batch.seq_len,
            output.hidden,
        ))
    }
}

struct TokenizedBatch {
    input_ids: Vec<i64>,
    attention_mask: Vec<i64>,
    token_type_ids: Vec<i64>,
    batch_size: usize,
    seq_len: usize,
}

fn load_tokenizer(path: &std::path::Path) -> Result<Tokenizer, ProviderError> {
    let mut tok =
        Tokenizer::from_file(path).map_err(|e| ProviderError::Tokenizer(e.to_string()))?;
    tok.with_padding(Some(PaddingParams {
        strategy: PaddingStrategy::Fixed(MAX_SEQUENCE),
        direction: PaddingDirection::Right,
        pad_to_multiple_of: None,
        pad_id: 0,
        pad_type_id: 0,
        pad_token: "[PAD]".to_string(),
    }));
    tok.with_truncation(Some(TruncationParams {
        max_length: MAX_SEQUENCE,
        strategy: TruncationStrategy::LongestFirst,
        stride: 0,
        direction: TruncationDirection::Right,
    }))
    .map_err(|e| ProviderError::Tokenizer(e.to_string()))?;
    Ok(tok)
}

fn tokenize_batch(tokenizer: &Tokenizer, texts: &[&str]) -> Result<TokenizedBatch, ProviderError> {
    let encodings = tokenizer
        .encode_batch(texts.to_vec(), true)
        .map_err(|e| ProviderError::Tokenizer(e.to_string()))?;
    let batch_size = encodings.len();
    let seq_len = encodings.first().map(|e| e.len()).unwrap_or(0);

    let total = batch_size * seq_len;
    let mut input_ids = Vec::with_capacity(total);
    let mut attention_mask = Vec::with_capacity(total);
    let mut token_type_ids = Vec::with_capacity(total);
    for enc in &encodings {
        input_ids.extend(enc.get_ids().iter().map(|x| *x as i64));
        attention_mask.extend(enc.get_attention_mask().iter().map(|x| *x as i64));
        token_type_ids.extend(enc.get_type_ids().iter().map(|x| *x as i64));
    }
    Ok(TokenizedBatch {
        input_ids,
        attention_mask,
        token_type_ids,
        batch_size,
        seq_len,
    })
}

fn mean_pool_and_normalise(
    values: &[f32],
    attention_mask: &[i64],
    batch_size: usize,
    seq_len: usize,
    hidden: usize,
) -> Vec<Vec<f32>> {
    let mut out = Vec::with_capacity(batch_size);
    for b in 0..batch_size {
        let mut sum = vec![0.0f32; hidden];
        let mut count = 0.0f32;
        for t in 0..seq_len {
            let mask_bit = attention_mask[b * seq_len + t];
            if mask_bit == 0 {
                continue;
            }
            let weight = mask_bit as f32;
            count += weight;
            let row_off = (b * seq_len + t) * hidden;
            for i in 0..hidden {
                sum[i] += values[row_off + i] * weight;
            }
        }
        let denom = count.max(1e-9);
        for v in &mut sum {
            *v /= denom;
        }
        let norm = sum.iter().map(|x| x * x).sum::<f32>().sqrt().max(1e-12);
        for v in &mut sum {
            *v /= norm;
        }
        out.push(sum);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mean_pool_handles_padding() {
        let values = vec![1.0, 2.0, 3.0, 4.0, 5.0, 6.0];
        let mask = vec![1, 1, 0];
        let pooled = mean_pool_and_normalise(&values, &mask, 1, 3, 2);
        assert_eq!(pooled.len(), 1);
        let expected_norm = (13.0f32).sqrt();
        let expected = [2.0 / expected_norm, 3.0 / expected_norm];
        for (got, want) in pooled[0].iter().zip(expected.iter()) {
            assert!((got - want).abs() < 1e-6, "got={got} want={want}");
        }
    }

    #[test]
    fn mean_pool_handles_all_masked() {
        let values = vec![1.0, 2.0, 3.0, 4.0];
        let mask = vec![0, 0];
        let pooled = mean_pool_and_normalise(&values, &mask, 1, 2, 2);
        assert_eq!(pooled.len(), 1);
        assert!(pooled[0].iter().all(|v| v.is_finite()));
    }

    #[test]
    fn mean_pool_output_is_unit_length() {
        let values = vec![1.0, 2.0, 3.0, 4.0];
        let mask = vec![1, 1];
        let pooled = mean_pool_and_normalise(&values, &mask, 1, 2, 2);
        let norm_sq: f32 = pooled[0].iter().map(|v| v * v).sum();
        assert!((norm_sq - 1.0).abs() < 1e-6, "norm_sq={norm_sq}");
    }
}
