//! Rust shadow collector. It intentionally emits the same JSONL contract as
//! `adoptrank export-events`; PostgreSQL remains owned by the Python writer
//! until parity gates are met.

use anyhow::{Context, Result};
use chrono::{DateTime, SecondsFormat, Timelike, Utc};
use clap::Parser;
use reqwest::header::{ACCEPT, AUTHORIZATION, USER_AGENT};
use serde::Serialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    env,
    fs::File,
    io::{BufWriter, Write},
    path::PathBuf,
};

const EVENT_SCHEMA_VERSION: &str = "adoptrank.repository-event.v1";

#[derive(Parser, Debug)]
#[command(
    name = "adoptrank-ingest",
    about = "Emit replayable GitHub repository events"
)]
struct Args {
    /// GitHub repository search expression.
    #[arg(long)]
    query: String,
    /// Maximum repositories to emit (1-100).
    #[arg(long, default_value_t = 50, value_parser = clap::value_parser!(u16).range(1..=100))]
    limit: u16,
    /// JSONL event output. The file is safe to replay because event ids are deterministic.
    #[arg(long)]
    output: PathBuf,
    /// GitHub sort order.
    #[arg(long, default_value = "updated", value_parser = ["updated", "stars"])]
    sort: String,
    /// Pin capture time for deterministic shadow replays (RFC 3339 UTC timestamp).
    #[arg(long)]
    observed_at: Option<DateTime<Utc>>,
}

#[derive(Serialize)]
struct RepositoryIdentity<'a> {
    full_name: &'a str,
    html_url: &'a str,
    commit_sha: Option<String>,
}

#[derive(Serialize)]
struct Provenance<'a> {
    source: &'static str,
    producer: &'static str,
    query: &'a str,
}

#[derive(Serialize)]
struct Event<'a> {
    schema_version: &'static str,
    event_type: &'static str,
    event_id: String,
    observed_at: DateTime<Utc>,
    repository: RepositoryIdentity<'a>,
    payload: Value,
    provenance: Provenance<'a>,
}

fn event_id(observed_at: DateTime<Utc>, full_name: &str, payload: &Value) -> String {
    // serde_json maps are ordered deterministically without the preserve_order feature.
    let body = json!({
        "event_type": "RepositorySnapshotCaptured",
        "observed_at": observed_at.to_rfc3339(),
        "repository": full_name.to_lowercase(),
        "payload": payload,
    });
    let mut hasher = Sha256::new();
    hasher.update(serde_json::to_vec(&body).expect("serializable event body"));
    format!("{:x}", hasher.finalize())
}

fn pydantic_datetime(value: DateTime<Utc>) -> String {
    // Pydantic serializes UTC fields in the payload using the Z suffix. The
    // deterministic id above deliberately uses RFC3339 +00:00, matching
    // Python datetime.isoformat() in events.event_id_for.
    value.to_rfc3339_opts(SecondsFormat::AutoSi, true)
}

fn snapshot(item: &Value, captured_at: DateTime<Utc>, query: &str) -> Result<Value> {
    let full_name = item["full_name"]
        .as_str()
        .context("GitHub result missing full_name")?;
    let html_url = item["html_url"]
        .as_str()
        .context("GitHub result missing html_url")?;
    let license = item["license"]["spdx_id"].as_str().unwrap_or("NOASSERTION");
    Ok(json!({
        "full_name": full_name,
        "html_url": html_url,
        "captured_at": pydantic_datetime(captured_at),
        "description": item["description"].as_str().unwrap_or(""),
        "language": item["language"].as_str().unwrap_or("Unknown"),
        "license_spdx": license,
        "topics": item["topics"].as_array().cloned().unwrap_or_default(),
        "stars": item["stargazers_count"].as_i64().unwrap_or(0),
        "forks": item["forks_count"].as_i64().unwrap_or(0),
        "open_issues": item["open_issues_count"].as_i64().unwrap_or(0),
        "watchers": item["watchers_count"].as_i64().unwrap_or(0),
        "size_kb": item["size"].as_i64().unwrap_or(0),
        "archived": item["archived"].as_bool().unwrap_or(false),
        "fork": item["fork"].as_bool().unwrap_or(false),
        "pushed_at": item["pushed_at"],
        "created_at": item["created_at"],
        "latest_release_at": null,
        "contributors_sampled": 0,
        "pypi_package": null,
        "pypi_downloads_1d": null,
        "pypi_downloads_7d": null,
        "pypi_downloads_30d": null,
        "pypi_latest_release": null,
        "source_query": query,
        "indexed_commit_sha": null,
        "source_file_count": 0,
        "test_file_count": 0,
        "example_file_count": 0,
        "dependency_count": 0,
        "symbol_count": 0,
        "code_terms": [],
        "code_evidence_paths": [],
        "architecture_summary": "",
        "code_chunks": [],
        "quality_score": 0.0,
        "depth_score": 0.0,
        "originality_score": 0.0
    }))
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    let mut headers = reqwest::header::HeaderMap::new();
    headers.insert(ACCEPT, "application/vnd.github+json".parse()?);
    headers.insert(USER_AGENT, "AdoptRank/rust-shadow".parse()?);
    if let Ok(token) = env::var("GITHUB_TOKEN") {
        headers.insert(AUTHORIZATION, format!("Bearer {token}").parse()?);
    }
    let client = reqwest::Client::builder()
        .default_headers(headers)
        .build()?;
    let response: Value = client
        .get("https://api.github.com/search/repositories")
        .query(&[
            ("q", &args.query),
            ("sort", &args.sort),
            ("order", &"desc".to_string()),
            ("per_page", &args.limit.to_string()),
        ])
        .send()
        .await?
        .error_for_status()?
        .json()
        .await?;
    let items = response["items"]
        .as_array()
        .context("GitHub search missing items")?;
    let requested_at = args.observed_at.unwrap_or_else(Utc::now);
    // Python's datetime has microsecond precision, so normalize the Rust clock
    // before it becomes an event id or a payload field.
    let observed_at = requested_at
        .with_nanosecond(requested_at.timestamp_subsec_micros() * 1_000)
        .expect("valid microsecond timestamp");
    let file = File::create(&args.output)
        .with_context(|| format!("creating {}", args.output.display()))?;
    let mut writer = BufWriter::new(file);
    for item in items {
        let payload = snapshot(item, observed_at, &args.query)?;
        let full_name = payload["full_name"]
            .as_str()
            .expect("snapshot full_name")
            .to_owned();
        let html_url = payload["html_url"]
            .as_str()
            .expect("snapshot html_url")
            .to_owned();
        let event = Event {
            schema_version: EVENT_SCHEMA_VERSION,
            event_type: "RepositorySnapshotCaptured",
            event_id: event_id(observed_at, &full_name, &payload),
            observed_at,
            repository: RepositoryIdentity {
                full_name: &full_name,
                html_url: &html_url,
                commit_sha: None,
            },
            payload,
            provenance: Provenance {
                source: "github",
                producer: "rust-shadow-collector",
                query: &args.query,
            },
        };
        writeln!(writer, "{}", serde_json::to_string(&event)?)?;
    }
    writer.flush()?;
    eprintln!("emitted={} output={}", items.len(), args.output.display());
    Ok(())
}
