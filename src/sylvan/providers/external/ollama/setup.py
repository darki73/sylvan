"""Ollama interactive configuration helpers.

Extracted from ``cli.py`` -- these handle model discovery and embedding
dimension detection during ``sylvan init``.
"""

import typer

from sylvan.config import Config, EmbeddingConfig, SummaryConfig


def configure_ollama(config: Config) -> None:
    """Run the interactive Ollama configuration flow.

    Queries the Ollama server for available models, lets the user pick
    an LLM and optionally an embedding model, and populates the config
    with the resulting settings.

    Args:
        config: The Config instance to populate with Ollama settings.
    """
    endpoint = typer.prompt("Ollama endpoint", default="http://localhost:11434")

    llm_models, embed_models = list_ollama_models(endpoint)

    if not llm_models and not embed_models:
        typer.echo("\n  Could not connect to Ollama or no models found.")
        typer.echo("  Make sure Ollama is running and has models pulled.")
        raise typer.Exit(1)

    if llm_models:
        typer.echo("\nAvailable LLM models:")
        for i, (name, size) in enumerate(llm_models, 1):
            typer.echo(f"  [{i}] {name} ({size})")
        pick = typer.prompt("Select LLM model", default="1")
        try:
            llm_model = llm_models[int(pick) - 1][0]
        except (ValueError, IndexError):
            llm_model = llm_models[0][0]
    else:
        llm_model = typer.prompt("LLM model name")

    config.summary = SummaryConfig(
        provider="ollama",
        endpoint=endpoint,
        model=llm_model,
    )

    if embed_models:
        typer.echo("\nEmbedding provider (for semantic search):")
        typer.echo("  [1] Local sentence-transformers (already enabled) [default]")
        typer.echo("  [2] Ollama")
        embed_choice = typer.prompt("Select", default="1")

        if embed_choice == "2":
            typer.echo("\nAvailable embedding models:")
            for i, (name, size) in enumerate(embed_models, 1):
                typer.echo(f"  [{i}] {name} ({size})")
            pick = typer.prompt("Select embedding model", default="1")
            try:
                embed_model = embed_models[int(pick) - 1][0]
            except (ValueError, IndexError):
                embed_model = embed_models[0][0]

            dims = detect_embedding_dims(endpoint, embed_model)
            config.embedding = EmbeddingConfig(
                provider="ollama",
                endpoint=endpoint,
                model=embed_model,
                dimensions=dims,
            )


def list_ollama_models(endpoint: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Query Ollama for available models.

    Args:
        endpoint: Ollama server URL.

    Returns:
        A ``(llm_models, embedding_models)`` tuple where each entry is
        ``(name, size)``.
    """
    try:
        from ollama import Client

        client = Client(host=endpoint)
        resp = client.list()

        llms: list[tuple[str, str]] = []
        embeds: list[tuple[str, str]] = []
        for m in resp.models:
            name = m.model
            size = m.details.parameter_size if m.details else "?"
            if "embed" in name.lower():
                embeds.append((name, size))
            elif "vl" not in name.lower() and "llava" not in name.lower():
                llms.append((name, size))
        return llms, embeds
    except Exception as e:
        typer.echo(f"  Error connecting to Ollama: {e}")
        return [], []


def detect_embedding_dims(endpoint: str, model: str) -> int:
    """Auto-detect embedding dimensions by running a test embed.

    Args:
        endpoint: Ollama server URL.
        model: Embedding model identifier.

    Returns:
        Detected dimension count, or 768 as a fallback default.
    """
    try:
        from ollama import Client

        client = Client(host=endpoint)
        resp = client.embed(model=model, input="test")
        if resp.embeddings:
            return len(resp.embeddings[0])
    except Exception:  # noqa: S110 -- fallback to default 768 dimensions
        pass
    return 768
