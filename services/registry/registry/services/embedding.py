"""OpenAI embedding generation for semantic search."""

from openai import AsyncOpenAI

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


async def generate_embedding(text: str, client: AsyncOpenAI) -> list[float]:
    """Generate an embedding vector from text using OpenAI's embedding API.

    Args:
        text: The input text to embed.
        client: An initialized AsyncOpenAI client.

    Returns:
        A list of 1536 floats representing the embedding vector.
    """
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding
