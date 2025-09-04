from pydantic import BaseModel, ConfigDict
from driver.driver import GraphDriver
from llm_client import LLMClient
from embedder import EmbedderClient
from cross_encoder.client import CrossEncoderClient

class GraphAgentClients(BaseModel):
    driver: GraphDriver
    llm_client: LLMClient
    embedder: EmbedderClient
    cross_encoder: CrossEncoderClient
    ensure_ascii: bool = False

    model_config = ConfigDict(arbitrary_types_allowed=True)